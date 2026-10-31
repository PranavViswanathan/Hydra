# VulnAgent. Run `make` on its own to see everything available.
#
# Backend commands run through uv against backend/, dashboard commands through
# npm against apps/dashboard/, and the operational scripts run from this
# directory so they read the .env sitting next to this file.

SHELL := /bin/bash
.DEFAULT_GOAL := help
.ONESHELL:

BACKEND := backend
DASHBOARD := apps/dashboard
UV := uv run --project $(BACKEND)
NPM := npm --prefix $(DASHBOARD)
TEST_REPO ?= $(VULNAGENT_TEST_REPO)

# Dependency sentinels, so targets only reinstall when the manifests change.
BACKEND_DEPS := $(BACKEND)/.venv/pyvenv.cfg
DASHBOARD_DEPS := $(DASHBOARD)/node_modules/.package-lock.json

# Demo targets blank the project id even when the shell exports .env, since
# a project id is what switches the dashboard from demo data to Appwrite.
DEMO_ENV := VITE_APPWRITE_PROJECT_ID= VITE_API_FUNCTION_ID= VITE_GITHUB_APP_SLUG=

##@ Getting started

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nVulnAgent\n\nUsage:\n  make \033[36m<target>\033[0m\n"} \
	/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
	/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
	@echo

.PHONY: install
install: $(BACKEND_DEPS) $(DASHBOARD_DEPS) ## Install backend and dashboard dependencies

$(BACKEND_DEPS): $(BACKEND)/pyproject.toml
	@cd $(BACKEND) && uv sync --extra dev

$(DASHBOARD_DEPS): $(DASHBOARD)/package.json
	@$(NPM) install

.PHONY: env
env: ## Create .env from the example (does not overwrite an existing one)
	@if [ -f .env ]; then \
		echo ".env already exists, leaving it alone"; \
	else \
		cp .env.example .env && echo "created .env, now fill it in"; \
	fi

.PHONY: doctor
doctor: ## Check the toolchain and report what is missing
	@echo "Tooling"
	@for tool in uv python3 node npm appwrite gh; do \
		printf "  %-10s " "$$tool"; \
		if command -v $$tool >/dev/null 2>&1; then $$tool --version 2>&1 | head -1; \
		else echo "MISSING"; fi; \
	done
	@echo
	@echo "Configuration"
	@if [ -f .env ]; then \
		echo "  .env       present"; \
		for key in APPWRITE_PROJECT_ID APPWRITE_API_KEY GITHUB_APP_ID \
		           GITHUB_APP_PRIVATE_KEY GITHUB_WEBHOOK_SECRET LLM_API_KEY; do \
			if grep -qE "^$$key=.+" .env; then printf "  %-26s set\n" "$$key"; \
			else printf "  %-26s EMPTY\n" "$$key"; fi; \
		done; \
	else \
		echo "  .env       missing (run: make env)"; \
	fi

##@ Running it

.PHONY: demo
demo: $(DASHBOARD_DEPS) ## Run the dashboard on demo data, no credentials needed
	@echo "Starting the dashboard with demo data."
	@echo "Press Fix now on vulnagent-test-app to watch a full agent run."
	@$(DEMO_ENV) $(NPM) run dev

.PHONY: hackathon-demo
hackathon-demo: $(DASHBOARD_DEPS) ## Open the demo in your browser with a presenter walkthrough
	@echo ""
	@echo "Hydra demo: sample data, no credentials, nothing leaves this machine."
	@echo ""
	@echo "  1. Overview: four repositories, the exposure strip shows open severity."
	@echo "  2. Open pranav/vulnagent-test-app: a critical jsonwebtoken advisory,"
	@echo "     high lodash and qs, medium minimist and semver."
	@echo "  3. Press Fix now and narrate the run as it plays (about 17 seconds):"
	@echo "     queued, plan, branch committed, PR #42 opened,"
	@echo "     CI fails on jwt.sign, memory recalls a past fix (0.93),"
	@echo "     patch pushed, CI passes, PR merged, 4 vulnerabilities fixed."
	@echo "  4. Reload the page to reset and run it again."
	@echo ""
	@$(DEMO_ENV) VITE_DEMO_BADGE=off $(NPM) run dev -- --open

.PHONY: dev
dev: demo ## Alias for demo

.PHONY: preview
preview: build-ui ## Serve the production dashboard build
	@$(NPM) run preview

##@ Checks

.PHONY: check
check: lint typecheck test ## Everything CI runs: lint, types and tests

.PHONY: test
test: test-backend test-ui ## Run every test

.PHONY: test-backend
test-backend: $(BACKEND_DEPS) ## Run the Python test suite
	@cd $(BACKEND) && uv run pytest

.PHONY: test-ui
test-ui: $(DASHBOARD_DEPS) ## Run the dashboard test suite
	@$(NPM) run test

.PHONY: watch
watch: $(BACKEND_DEPS) ## Re-run the Python tests on every change
	@cd $(BACKEND) && uv run pytest -f 2>/dev/null || \
		(echo "install pytest-watch for this, or use: make test-ui-watch"; exit 1)

.PHONY: test-ui-watch
test-ui-watch: $(DASHBOARD_DEPS) ## Re-run the dashboard tests on every change
	@$(NPM) run test:watch

.PHONY: cov
cov: $(BACKEND_DEPS) ## Python tests with a coverage report
	@cd $(BACKEND) && uv run pytest --cov=vulnagent --cov-report=term-missing

.PHONY: cov-html
cov-html: $(BACKEND_DEPS) ## Coverage as a browsable HTML report
	@cd $(BACKEND) && uv run pytest --cov=vulnagent --cov-report=html
	@echo "open $(BACKEND)/htmlcov/index.html"

.PHONY: lint
lint: $(BACKEND_DEPS) ## Lint and format-check everything
	@cd $(BACKEND) && uv run ruff check src tests && uv run ruff format --check src tests
	@$(UV) ruff check scripts && $(UV) ruff format --check scripts

.PHONY: format
format: $(BACKEND_DEPS) ## Reformat and auto-fix what can be fixed
	@cd $(BACKEND) && uv run ruff check src tests --fix && uv run ruff format src tests
	@$(UV) ruff check scripts --fix && $(UV) ruff format scripts

.PHONY: typecheck
typecheck: $(BACKEND_DEPS) $(DASHBOARD_DEPS) ## mypy --strict and tsc --noEmit
	@cd $(BACKEND) && uv run mypy
	@$(NPM) run typecheck

##@ Building and deploying

.PHONY: build
build: build-ui build-functions ## Build the dashboard and package the functions

.PHONY: build-ui
build-ui: $(DASHBOARD_DEPS) ## Build the dashboard for production
	@$(NPM) run build

.PHONY: build-functions
build-functions: $(BACKEND_DEPS) ## Vendor the shared package into each function folder
	@$(UV) python scripts/build_functions.py

.PHONY: deploy
deploy: check build-functions ## Push the functions to Appwrite (runs the checks first)
	@command -v appwrite >/dev/null || { echo "appwrite CLI is missing: npm i -g appwrite-cli"; exit 1; }
	@appwrite push functions

##@ Appwrite setup

.PHONY: bootstrap
bootstrap: bootstrap-db bootstrap-vectors ## Create every table and the vector store

.PHONY: bootstrap-db
bootstrap-db: $(BACKEND_DEPS) ## Create the TablesDB schema (idempotent)
	@$(UV) python scripts/bootstrap_db.py

.PHONY: bootstrap-check
bootstrap-check: $(BACKEND_DEPS) ## Report schema drift without changing anything
	@$(UV) python scripts/bootstrap_db.py --check

.PHONY: bootstrap-vectors
bootstrap-vectors: $(BACKEND_DEPS) ## Create the VectorsDB store (M0 spike A)
	@$(UV) python scripts/bootstrap_vectors.py

.PHONY: seed
seed: $(BACKEND_DEPS) ## Seed the failure memory with known fixes
	@$(UV) python scripts/seed_memory.py

.PHONY: push-env
push-env: $(BACKEND_DEPS) ## Copy the server settings from .env onto the hydra function
	@$(UV) python scripts/push_env.py

##@ End-to-end testing

.PHONY: reset
reset: reset-repo reset-rows ## Put the test repo and its rows back to the vulnerable state

.PHONY: reset-repo
reset-repo: ## Reset the GitHub side of the test repo (TEST_REPO=owner/name)
	@test -n "$(TEST_REPO)" || { echo "set TEST_REPO=owner/name or VULNAGENT_TEST_REPO"; exit 1; }
	@./scripts/reset_test_repo.sh $(TEST_REPO)

.PHONY: reset-rows
reset-rows: $(BACKEND_DEPS) ## Clear the test repo's Appwrite rows (TEST_REPO=owner/name)
	@test -n "$(TEST_REPO)" || { echo "set TEST_REPO=owner/name or VULNAGENT_TEST_REPO"; exit 1; }
	@$(UV) python scripts/reset_test_rows.py $(TEST_REPO)

##@ Housekeeping

.PHONY: clean
clean: ## Remove build output and caches, keeping dependencies
	@rm -rf $(DASHBOARD)/dist $(BACKEND)/htmlcov $(BACKEND)/.coverage
	@rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
	@rm -rf $(BACKEND)/functions/*/src/vulnagent
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "cleaned"

.PHONY: clean-all
clean-all: clean ## Also remove installed dependencies
	@rm -rf $(BACKEND)/.venv $(DASHBOARD)/node_modules
	@echo "removed the virtualenv and node_modules; run make install"

.PHONY: tree
tree: ## Show the project layout
	@git ls-files | awk -F/ '{print (NF>1 ? $$1"/"$$2 : $$1)}' | sort -u
