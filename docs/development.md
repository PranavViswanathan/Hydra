# Development

How to work on this: the commands, the testing approach, and the conventions
the code already follows.

- [Commands](#commands)
- [Repository layout](#repository-layout)
- [The testing approach](#the-testing-approach)
- [Test doubles](#test-doubles)
- [Conventions](#conventions)
- [Adding a feature](#adding-a-feature)
- [CI](#ci)

## Commands

`make` on its own lists everything. The ones you will actually use:

| Command | Does |
|---|---|
| `make install` | Backend and dashboard dependencies |
| `make demo` | Dashboard on demo data at :5173 |
| `make hackathon-demo` | The demo opened in a browser, with a presenter walkthrough |
| `make check` | Everything CI runs: lint, types, both test suites |
| `make test-backend` | 667 Python tests, about a second |
| `make test-ui` | 16 dashboard tests |
| `make test-ui-watch` | Vitest in watch mode |
| `make format` | ruff fix and reformat, backend and scripts |
| `make cov` | Coverage with missing lines |
| `make doctor` | What is installed, what is configured |
| `make clean` | Build output and caches |

Run `make check` before committing. It is what CI runs, so a green local run
means a green pipeline.

## Repository layout

```
backend/src/vulnagent/
├── core/              models, protocols, safety, purl, errors — no I/O
├── adapters/npm/      parser, planner, applier, registry
├── osv/               client, severity, fixes, models
├── github/            auth, client, pr_body, webhooks
├── agent/             state_machine (pure), steps (effects), ci_logs
├── scanning/          scan (orchestration), reconcile (pure)
├── memory/            base, vectors, tables, embeddings
├── llm/               base, schemas, anthropic_provider, prompts/
├── db/                rows, repositories
├── config/            schema (repo config), settings (environment)
├── services/          triggers, installations, linking
└── runtime.py         composition root
```

Two rules hold the structure together:

1. **`core/` imports nothing external.** No Appwrite, no httpx, no GitHub. If
   you find yourself wanting one there, the logic belongs elsewhere.
2. **No raw Appwrite SDK call outside `db/` and `memory/`.** Everything else
   uses typed repositories.

## The testing approach

667 backend tests run in about a second, because almost nothing touches a
network or a database.

**Tests describe behavior, not methods.** Names are sentences:

```python
def test_a_nested_dependency_resolves_to_the_copy_beside_its_parent()
def test_refuses_a_patch_that_would_disable_a_test()
def test_an_ignored_vulnerability_is_not_reopened_by_a_scan()
```

A failing test should tell you what broke without opening the file. There is
no one-to-one mapping between test files and modules; tests are grouped by the
behavior they cover.

**The pure core is tested directly.** `next_state`, `reconcile`,
`plan_upgrades`, `error_signature`, `review_edits` are all functions over
values, so their tests are fast and exhaustive.

**I/O is tested through its seam.** HTTP with `respx`, Appwrite with
`FakeTablesDB`, the model with a scripted stub. What is being checked is the
request we build and the response we interpret, which is the part we own.

**Integration tests are thin and few.** `test_scan_integration.py` runs a whole
scan against recorded GitHub and OSV responses and checks the outcome the spec
names: a transitive vulnerability traces back to ROOT through the edges.

| Suite | Count | Covers |
|---|---|---|
| `test_npm_parser.py` | 40 | Lockfile v2/v3, nesting, scopes, workspaces, rejects |
| `test_npm_planner.py` | 27 | Direct, parent, override, major, merging, conflicts |
| `test_npm_applier.py` | 21 | Formatting preservation, each action, regeneration |
| `test_safety.py` | 57 | Every rule from §11 |
| `test_state_machine.py` | 55 | Every transition and interrupt |
| `test_agent_steps.py` | 38 | Each step's effects, including the repair loop |
| `test_services.py` | 38 | Triggers, installation sync, linking |
| `test_scan_integration.py` | 17 | The whole scan path |
| others | — | OSV, config, settings, memory, GitHub, PR body, webhooks, repositories |

## Test doubles

| Double | Stands in for | Where |
|---|---|---|
| `FakeTablesDB` | Appwrite TablesDB | `tests/fakes.py` |
| `respx` | Any HTTP service | GitHub, OSV, npm registry tests |
| `FakeRegistry` | The npm registry | Planner tests, with a fixed catalogue |
| `FakeRegenerator` | The Node lockfile function | Applier and step tests |
| `FakeLLM` | The model | Scripted replies, including bad ones |
| `FakeMemory` | The failure memory | Records what was added |
| `StubVectors` / `StubTables` | Appwrite services | Memory tests |
| `mockBackend` | The entire backend | Dashboard demo mode and tests |

`FakeTablesDB` understands the query shapes the repositories actually send:
`equal` with a scalar or a list, `lessThanEqual`, `orderAsc`/`orderDesc`,
`limit` and `offset`. It is not a general Appwrite emulator, and it should
grow only when a repository starts sending something new.

## Conventions

**Python.** 3.12, full type hints, `mypy --strict` clean, ruff for lint and
format, 100 columns. PEP 695 `type` aliases rather than `TypeAlias`.

**Protocols over inheritance.** `EcosystemAdapter`, `FailureMemory`,
`LLMProvider`, `RegistryClient`, `LockfileRegenerator`, and the narrow
`TablesDbService` / `VectorsDbService` slices are all `Protocol`. Nothing
subclasses a framework type, which is why the doubles above are plain classes.

**Pydantic at the boundaries.** Config, LLM responses, OSV records and
database rows are models. Internal functions pass plain values.

**Errors are specific.** `ConfigError`, `UnsupportedLockfileError`,
`PurlError`, `SafetyViolationError`, all under `VulnAgentError`. A message
should name the thing that was wrong and, where possible, what to do:

```
lockfileVersion 1 is not supported; run `npm install` with npm 7 or newer
to upgrade to lockfileVersion 3
```

**Comments explain why.** The code says what it does. A comment earns its place
by recording a decision or a trap:

```python
# The lowest permitted version is the conservative one to test: npm installs
# the highest, but a fresh resolve elsewhere could pick any of them, and a
# parent that merely *allows* a fixed version is not a fix.
```

**Commits are Conventional Commits**, imperative mood, body explaining why.
No em dashes. No AI attribution.

## Adding a feature

The loop this codebase was built with, and the one to keep:

1. **Write the test first.** Name it after the behavior.
2. **Watch it fail.** A test that passes before the code exists is testing
   nothing.
3. **Make it pass simply.** Simplest thing that works.
4. **Run `make check`.** Lint, types, everything.
5. **Refactor if it helps.** Only if it does.
6. **Record non-obvious decisions** in `docs/DECISIONS.md`.
7. **Commit.** Small, working increments.

Where new code goes:

| Change | Where | Also update |
|---|---|---|
| New ecosystem | `adapters/<id>/` | [adapters.md](adapters.md) |
| New agent state | `agent/state_machine.py` then `steps.py` | [agent.md](agent.md) |
| New safety rule | `core/safety.py` + a test | [safety.md](safety.md) |
| New table | `db/rows.py`, `db/repositories.py`, `scripts/bootstrap_db.py` | [data-model.md](data-model.md) |
| New config field | `config/schema.py` | [configuration.md](configuration.md) |
| New trigger | `services/triggers.py` | [agent.md](agent.md) |
| New page | `apps/dashboard/src/pages/` | [dashboard.md](dashboard.md) |

Documentation is updated in the same commit as the code it describes.

## CI

`.github/workflows/ci.yml` runs two jobs on every push and pull request:

**backend** — `uv sync`, ruff check and format check on `src` and `tests`,
ruff on `scripts`, `mypy --strict`, pytest with coverage.

**dashboard** — `npm ci`, `tsc --noEmit`, Vitest, production build.

Both have to pass. `make check` runs the same gates locally, minus the
dependency install.
