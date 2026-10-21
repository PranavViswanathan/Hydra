# INITIALPROJECT.md — VulnAgent

> **Audience:** Claude Code. This file is the source of truth for building the code: scope, architecture, data model, and build order.
> **Working name:** `VulnAgent` (rename freely; keep it consistent across the repo, GitHub App, and Appwrite project).
> **Backend:** Python. **Dashboard:** React + TypeScript.
> **Hard deadline for working code:** Oct 30, 2026.

---

## 0. How Claude Code should work on this repo

1. **Read this whole file before writing code.** Follow the milestone order in §17.
2. **Appwrite APIs are new.** VectorsDB and DocumentsDB are beta, and TablesDB replaced the old "collections/documents" naming. **Always check current Appwrite docs** (https://appwrite.io/docs), including the Python server SDK reference and the Python Functions runtime docs, or use the Appwrite MCP server, before calling an SDK method. Do not rely on memory for Appwrite SDK signatures.
3. **Keep a decision log.** Append every non-trivial deviation from this spec to `docs/DECISIONS.md` (date, decision, reason).
4. **Ask before:** changing database choices, adding a paid service, changing the safety rules (§11), adding a non-Python backend component beyond the one allowed in §6.4, or expanding scope beyond §2.
5. **Small, working increments.** Each milestone ends in a runnable state with tests passing.
6. **Never commit secrets.** All secrets live in env vars (§13.2). Add `.env*` to `.gitignore` on the first commit.
7. **Python quality bar:** Python 3.12, full type hints, `mypy --strict` (or pyright strict) clean, `ruff` for lint and format. Dashboard: TypeScript strict.
8. **Commit often, never push.**
   - Make a local git commit after each meaningful unit of work (a working feature, a passing test suite, a spike result, a refactor). Don't let more than roughly an hour of work go uncommitted, and always commit at the end of each milestone.
   - Write descriptive messages in Conventional Commits style: a short summary line (≤ 72 chars), a blank line, then a body explaining what changed and why. Example: `feat(npm-adapter): parse lockfile v3 into dependency graph`.
   - **Never use em dashes or en dashes in commit messages.** Use plain hyphens, commas, colons, or separate sentences instead.
   - Run lint, type-check, and tests before committing. Commit only when they pass, unless the commit is an explicit `wip:` checkpoint.
   - **Never run `git push`** or push to any remote. Pranav pushes to origin himself.

---

## 1. What we're building

An autonomous dependency-security agent you add to a GitHub repo by installing a GitHub App and dropping a `.vulnagent.yml` (or `.vulnagent.json`) in the repo root. It:

1. Scans the repo's dependency tree (direct and transitive) against the free **OSV** vulnerability database.
2. Stores vulnerabilities, packages, and the dependency graph in **Appwrite TablesDB**.
3. Computes a safe upgrade plan, including transitive upgrades (bump the parent, or fall back to an override).
4. Opens a PR with the changes.
5. Watches CI. On failure, it reads the logs, searches **Appwrite VectorsDB** for similar past failures and the fixes that worked, asks an LLM for a patch, and pushes it. Retries up to N times.
6. When the PR merges (or the agent gives up), it **goes to sleep** until the next trigger.

A **dashboard** lets a user sign in with GitHub, link the repos they manage, see open-vulnerability counts by severity, watch the agent's progress live, and press **Fix now** to wake the agent immediately.

**Target end-to-end flow (used for manual testing):** Dashboard shows open vulns → press *Fix now* → PR opens → CI fails on a breaking change → agent reads logs, gets a VectorsDB memory hit, pushes a patch → CI passes → PR merges → counts drop live → agent state returns to sleeping.

---

## 2. Scope

### 2.1 In scope (MVP)

- **GitHub only**, via a GitHub App.
- **One ecosystem adapter: npm** (`package.json` + `package-lock.json`, lockfileVersion 2 or 3). Adding Maven, PyPI, etc. must only require one new adapter module (§6).
- Vulnerability source: **OSV API** (https://api.osv.dev). No paid scanners.
- Scan triggers: **schedule** (cron in config), **push** (manifest/lockfile changed on default branch), **new advisory** (DB event on new vulnerability rows), **manual** (dashboard button).
- Upgrade planning for direct and transitive vulnerabilities.
- One PR per agent run containing all fixes (`grouping: single_pr`).
- CI repair loop using GitHub Actions results and logs, with a hard retry cap.
- VectorsDB-backed failure memory.
- Dashboard: GitHub login, installation linking, repo list with severity counts, repo detail with vulnerabilities and a live agent timeline, *Scan now* and *Fix now*.
- Live updates via **Appwrite Realtime**.

### 2.2 Stretch (only after MVP works end to end)

- `grouping: per_package`.
- Maven adapter.
- DocumentsDB for raw scan reports and full LLM transcripts.
- Ignore rules with expiry, editable from the dashboard.
- Notifications via Appwrite Messaging.

### 2.3 Non-goals

- GitLab, Bitbucket, self-hosted Git.
- CI systems other than GitHub Actions.
- Multiple lockfiles per repo (only `paths: ["."]` for MVP; keep the field).
- Executing the target repo's code. **CI is the test runner.**
- Billing, teams, or RBAC beyond "user sees repos in installations they can access".
- Vulnerabilities with no fixed version (mark `unfixable`, show on the dashboard).

---

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend language | Python 3.12 | All functions and shared logic |
| Dependency management | `uv` (workspace) | `pyproject.toml` at root |
| Backend runtime | Appwrite Functions, Python runtime | Event-driven; no long-running server |
| Appwrite SDK | `appwrite` (Python server SDK) | Confirm the version supports TablesDB and VectorsDB (server API 1.9.x+) |
| HTTP client | `httpx` | Sync client is fine; use timeouts everywhere |
| Models and validation | `pydantic` v2 | Domain models, config, LLM output |
| Config parsing | `PyYAML` (safe_load) + `json` | |
| npm semver ranges | `node-semver` (`import nodesemver`) | Python's `semver` package does not handle npm ranges |
| Cron | `croniter` | |
| CVSS scoring | `cvss` | |
| GitHub | `githubkit` (App auth + REST) | Fallback: `PyGithub` + `PyJWT`. Record the choice in DECISIONS.md |
| Webhook verification | stdlib `hmac` | constant-time compare |
| LLM | `anthropic` SDK behind an `LLMProvider` protocol | Model from env var |
| Embeddings | behind an `EmbeddingProvider` protocol | Check whether VectorsDB offers built-in embeddings; else a hosted embedding API from env vars |
| Tests | `pytest`, `respx` (mock httpx), `pytest-cov` | |
| Lint/types | `ruff`, `mypy --strict` | |
| Dashboard | Vite + React + TypeScript + Tailwind + TanStack Query + Appwrite Web SDK | Plain SPA |
| Dashboard hosting | Appwrite Sites | Optional |

---

## 4. Architecture

### 4.1 Components

```
                 ┌──────────────────────────────┐
                 │        GitHub (target repo)  │
                 │ .vulnagent.yml, Actions CI   │
                 └───────┬───────────────▲──────┘
         webhooks        │               │ PRs, commits, comments (GitHub App)
                         ▼               │
┌──────────────────────────────────────────────────────────────────────┐
│                         Appwrite Project                             │
│                                                                      │
│  Functions (Python unless noted)                                     │
│   ├─ github_webhook   (HTTP)  verify signature → route events        │
│   ├─ scheduler        (cron */15) find repos due for scan            │
│   ├─ scan_repo        (async) fetch lockfile → adapter → OSV → DB    │
│   ├─ agent_step       (async) advance one agent run by one state     │
│   ├─ on_vuln_created  (DB event) maybe auto-start agent              │
│   ├─ api              (HTTP, user JWT) dashboard actions             │
│   └─ npm_lockfile     (Node runtime, tiny) regenerate lockfile §6.4  │
│                                                                      │
│  TablesDB:  installations, repos, scans, repo_packages,              │
│             dependency_edges, advisories, vulnerabilities,           │
│             agent_runs, agent_events, webhook_deliveries             │
│  VectorsDB: ci_failures                                              │
│  Auth: GitHub OAuth      Realtime: agent_events, repos, vulns        │
│  Sites: dashboard                                                    │
└──────────────────────────────────────────────────────────────────────┘
                         ▲
                         │ Appwrite Web SDK + Realtime
                 ┌───────┴────────┐
                 │   Dashboard    │
                 └────────────────┘
External: api.osv.dev, registry.npmjs.org, LLM API, embedding API
```

### 4.2 Design principles

1. **The core is ecosystem-agnostic.** It never parses `package.json` or `pom.xml`; it only calls `EcosystemAdapter` methods (§6).
2. **The agent is a persisted state machine.** Each function execution loads an `agent_run`, performs one transition, saves, and exits. Webhooks and async executions drive progress. "Sleeping" = no active run.
3. **Manifest changes are deterministic; the LLM only fixes breakage.**
4. **Idempotency everywhere.** Webhooks deduped by delivery ID; agent steps check current state before acting.
5. **CI is the test runner.** VulnAgent never executes target-repo code.
6. **Pure core, thin functions.** Business logic lives in the `vulnagent` package and is unit-testable without Appwrite or GitHub. Each Appwrite function's `main.py` only parses the request, builds dependencies, and calls into the core.

### 4.3 GitHub interaction without cloning

Use the GitHub REST API (Contents API and Git Data API: blobs, trees, commits, refs) to read files and commit. No `git` binary.

---

## 5. Python package layout and function packaging

- Shared code lives in one installable package: `backend/src/vulnagent/`.
- Each Appwrite function is a thin folder under `backend/functions/<name>/` with `src/main.py` and `requirements.txt`.
- **Packaging:** Appwrite builds each function from its own folder, so it cannot see the workspace package. `scripts/build_functions.py` copies (vendors) `backend/src/vulnagent` into each function's `src/` before deploy and writes a merged `requirements.txt`. Deploy with the Appwrite CLI (`appwrite.config.json`). **Verify** the current Python runtime entrypoint and request/response API in Appwrite's docs (expected shape: `def main(context):` using `context.req` and `context.res.json(...)`).
- Function timeouts: check the platform maximum and set each function's timeout explicitly.

---

## 6. Ecosystem adapter design

### 6.1 Models (`vulnagent/core/models.py`)

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Purl = str  # "pkg:npm/lodash@4.17.20", "pkg:npm/%40scope/name@1.2.3"
Severity = Literal["low", "medium", "high", "critical", "unknown"]
FileMap = dict[str, str]  # repo-relative path -> contents

class DepNode(BaseModel):
    purl: Purl
    name: str
    version: str
    is_direct: bool
    is_dev: bool

class DepEdge(BaseModel):
    parent: Purl | Literal["ROOT"]
    child: Purl
    requested_range: str

class DepGraph(BaseModel):
    ecosystem: str
    nodes: dict[Purl, DepNode]
    edges: list[DepEdge]

class VulnFinding(BaseModel):
    osv_id: str
    aliases: list[str]
    purl: Purl
    fixed_versions: list[str]  # ascending
    severity: Severity

class BumpDirect(BaseModel):
    kind: Literal["bump_direct"] = "bump_direct"
    name: str
    from_version: str
    to_version: str
    manifest_path: str

class BumpParent(BaseModel):
    kind: Literal["bump_parent"] = "bump_parent"
    parent_name: str
    from_version: str
    to_version: str
    reason: Purl
    manifest_path: str

class Override(BaseModel):
    kind: Literal["override"] = "override"
    name: str
    to_version: str
    reason: Purl
    manifest_path: str

UpgradeAction = BumpDirect | BumpParent | Override

class Unresolved(BaseModel):
    osv_id: str
    reason: Literal["no_fix", "needs_major", "conflict"]

class UpgradePlan(BaseModel):
    ecosystem: str
    actions: list[UpgradeAction] = Field(discriminator="kind")
    resolves: list[str]
    unresolved: list[Unresolved]
    major_bumps: list[str]

class FilePatch(BaseModel):
    path: str
    new_contents: str
```

### 6.2 Adapter protocol (`vulnagent/core/adapter.py`)

```python
from typing import Protocol

class RegistryClient(Protocol):
    def list_versions(self, name: str) -> list[str]: ...
    def get_dependencies(self, name: str, version: str) -> dict[str, str]: ...

class EcosystemAdapter(Protocol):
    id: str                    # "npm"
    osv_ecosystem: str         # "npm" | "Maven" | "PyPI"
    manifest_files: list[str]  # ["package.json", "package-lock.json"]

    def detect(self, repo_file_paths: list[str]) -> bool: ...
    def parse_dependencies(self, files: FileMap) -> DepGraph: ...
    def plan_upgrades(
        self,
        findings: list[VulnFinding],
        graph: DepGraph,
        *,
        allow_major_bumps: bool,
        registry: RegistryClient,
    ) -> UpgradePlan: ...
    def apply_upgrades(self, plan: UpgradePlan, files: FileMap) -> list[FilePatch]: ...  # also updates lockfile
    def is_manifest_path(self, path: str) -> bool: ...
    def ci_hints(self) -> list[str]: ...
```

### 6.3 Registry (`vulnagent/adapters/__init__.py`)

```python
ADAPTERS: list[EcosystemAdapter] = [NpmAdapter()]  # MavenAdapter() later

def detect_adapters(paths: list[str], configured: Literal["auto"] | list[str]) -> list[EcosystemAdapter]: ...
```

Adding an ecosystem = new module `vulnagent/adapters/<id>/`, register it, add fixtures and tests. **No core changes.**

### 6.4 npm adapter (`vulnagent/adapters/npm/`)

- **detect:** `package.json` and `package-lock.json` exist at the root.
- **parse_dependencies:** use lockfile v2/v3 `packages`. Key `""` is the root. Keys like `node_modules/a/node_modules/b` encode nesting. Nodes come from each entry's `version`, `dev` flag, and name (from the path, or `name` when present). Edges come from `dependencies`, `optionalDependencies`, and `peerDependencies`; resolve children with Node's resolution rules (walk up `node_modules` ancestors). Lockfile v1 → raise `UnsupportedLockfileError`.
- **plan_upgrades**, per finding:
  1. Minimal fixed version greater than current. None → `no_fix`.
  2. Crosses a major and `allow_major_bumps` is false → `needs_major`.
  3. Direct → `BumpDirect`, preserving range style (`^`, `~`, exact).
  4. Transitive → walk edges to direct ancestors; query the registry for the lowest ancestor version whose chain admits the fixed version → `BumpParent`; otherwise → `Override` in `package.json#overrides`.
  5. Merge actions on the same package (highest target wins); conflicts → `conflict`.
- **apply_upgrades:**
  1. Edit `package.json` preserving key order and detected indentation (`json.loads` keeps order; re-dump with the detected indent and trailing newline).
  2. **Regenerate the lockfile.** The Python runtime does not ship `npm`, so this is delegated to the **`npm_lockfile` helper function** (Node runtime, ~50 lines, no other logic): input `{package_json, package_lock}`, runs `npm install --package-lock-only --ignore-scripts --no-audit --no-fund` in a temp dir, returns the new lockfile. The Python adapter calls it via Appwrite `functions.create_execution` (sync) through a `LockfileRegenerator` protocol. **`--ignore-scripts` is mandatory.**
  3. Return patches for both files.
- **ci_hints:** e.g. "Errors referencing `node_modules` paths usually mean an API change in a bumped package; check its changelog for breaking changes."

> **Spike required (M0):** confirm the Node-runtime `npm_lockfile` function can reach registry.npmjs.org and finish within its timeout. **Fallback:** a `worker/` Docker container (Python + Node) that polls `agent_runs` in state `PATCHING` and runs the adapter locally; it uses the same `LockfileRegenerator` protocol with a subprocess implementation. Record the outcome in DECISIONS.md.

### 6.5 Maven adapter (stretch, design only)

`pom.xml` parsing; transitive tree from `mvn dependency:tree` (or a resolver); `BumpDirect` edits `<version>` or `<properties>`; `Override` → `<dependencyManagement>`. Same protocol.

---

## 7. Data model — Appwrite TablesDB

Database ID: `vulnagent`. Timestamps ISO datetime. **Check current TablesDB column types and index APIs** and map these logical types. `scripts/bootstrap_db.py` creates every table, column, and index idempotently.

Severity enum: `low | medium | high | critical | unknown`.

### 7.1 `installations`
| Column | Type | Notes |
|---|---|---|
| github_installation_id | integer | unique index |
| account_login | string | |
| account_type | enum `User`/`Organization` | |
| owner_user_id | string (nullable) | Appwrite user ID once linked |
| suspended | boolean | |

### 7.2 `repos`
| Column | Type | Notes |
|---|---|---|
| installation_id | string | |
| github_repo_id | integer | unique index |
| full_name | string | index |
| default_branch | string | |
| owner_user_id | string | index; used for permissions |
| has_config | boolean | |
| config_json | long string | normalized, validated config |
| config_error | string (nullable) | |
| ecosystems | string[] | |
| agent_state | enum `idle`/`scanning`/`working`/`error` | |
| active_run_id | string (nullable) | at most one active run |
| next_scan_at | datetime (nullable) | |
| last_scan_at | datetime (nullable) | |
| open_critical, open_high, open_medium, open_low, open_unknown | integer | denormalized counts |

Row permissions: read for `user:<owner_user_id>`. Writes server-only.

### 7.3 `scans`
| Column | Type | Notes |
|---|---|---|
| repo_id | string | index |
| trigger | enum `schedule`/`push`/`new_advisory`/`manual` | |
| status | enum `running`/`succeeded`/`failed` | |
| commit_sha | string | |
| packages_scanned | integer | |
| vulns_found | integer | |
| error | string (nullable) | |
| started_at, finished_at | datetime | |

### 7.4 `repo_packages` (latest snapshot)
| Column | Type | Notes |
|---|---|---|
| repo_id | string | |
| purl | string | unique index (repo_id, purl) |
| ecosystem | string | |
| name | string | index |
| version | string | |
| is_direct | boolean | |
| is_dev | boolean | |
| scan_id | string | |

Upsert current nodes each scan; delete rows not seen in the latest scan.

### 7.5 `dependency_edges` (latest snapshot)
| Column | Type | Notes |
|---|---|---|
| repo_id | string | index |
| parent_purl | string | `ROOT` for direct |
| child_purl | string | index (repo_id, child_purl) |
| requested_range | string | |
| ecosystem | string | |
| scan_id | string | |

### 7.6 `advisories` (global OSV cache)
| Column | Type | Notes |
|---|---|---|
| osv_id | string | unique index |
| aliases | string[] | |
| summary | string | |
| details | long string | |
| severity | enum | |
| cvss_score | float (nullable) | |
| affected_json | long string | raw OSV `affected` |
| osv_modified | datetime | refetch when OSV's is newer |

### 7.7 `vulnerabilities` (per repo)
| Column | Type | Notes |
|---|---|---|
| repo_id | string | index |
| osv_id | string | |
| purl | string | unique index (repo_id, osv_id, purl) |
| package_name | string | |
| installed_version | string | |
| fixed_version | string (nullable) | |
| severity | enum | index (repo_id, status, severity) |
| status | enum `open`/`in_progress`/`fixed`/`ignored`/`unfixable`/`needs_major` | |
| is_direct | boolean | |
| first_seen_at, last_seen_at | datetime | |
| resolved_at | datetime (nullable) | |
| resolved_by_run_id | string (nullable) | |

### 7.8 `agent_runs`
| Column | Type | Notes |
|---|---|---|
| repo_id | string | index |
| trigger | enum `auto`/`manual` | |
| state | enum (§9) | index |
| attempt | integer | |
| max_attempts | integer | |
| vuln_ids | string[] | |
| plan_json | long string | `UpgradePlan` |
| branch | string (nullable) | `vulnagent/<run_id>` |
| base_sha, head_sha | string (nullable) | |
| pr_number | integer (nullable) | |
| pr_url | string (nullable) | |
| last_error | string (nullable) | |
| created_at, updated_at, completed_at | datetime | |

### 7.9 `agent_events` (timeline; Realtime source)
| Column | Type | Notes |
|---|---|---|
| run_id | string | index |
| repo_id | string | index |
| type | enum `state_change`/`info`/`pr_opened`/`ci_failed`/`ci_passed`/`memory_hit`/`patch_pushed`/`gave_up`/`merged`/`error` | |
| message | string | human-readable |
| data_json | string (nullable) | |
| created_at | datetime | |

### 7.10 `webhook_deliveries`
| Column | Type | Notes |
|---|---|---|
| delivery_id | string | unique index |
| event | string | |
| received_at | datetime | |

Data access goes through typed repository classes in `vulnagent/db/` (one module per table) that convert rows to pydantic models. No raw SDK calls outside `vulnagent/db/` and `vulnagent/memory/`.

---

## 8. Data model — Appwrite VectorsDB

Database ID: `vulnagent_vectors`. Collection: `ci_failures`.

| Field | Type | Notes |
|---|---|---|
| embedding | vector(D) | D from `EMBEDDING_DIM` |
| ecosystem | string | **always filter on this** |
| error_signature | string | normalized first error lines |
| log_excerpt | string | ≤ 4 KB |
| package_changes | string | e.g. `jsonwebtoken 8.5.1→9.0.2` |
| fix_diff | string | unified diff that turned CI green |
| outcome | enum `success`/`failed` | only `success` used as hints |
| repo_full_name | string | |
| run_id | string | |
| created_at | datetime | |

**Embedded text:** `error_signature + "\n" + package_changes`.

**Write path:** CI turns green after ≥ 1 repair → insert one `success` row per repaired failure. Run gives up → insert `failed` rows.

**Read path:** on CI failure, embed the signature, query top-k = 3 with `ecosystem = adapter.id` and `outcome = success`, similarity threshold 0.80 (tunable). Each hit writes an `agent_events` row of type `memory_hit`.

**Seed data:** `scripts/seed_memory.py` inserts realistic npm failure→fix pairs, including one matching the test target repo's breaking change.

**Interface:** `vulnagent/memory/base.py` defines a `FailureMemory` protocol (`add(record)`, `search(signature, ecosystem, k) -> list[Hit]`). Implementation: `VectorsDBMemory`.

> **Spike required (M0):** confirm a VectorsDB database can be created in the project. If it fails with `dedicated_database_required` or a plan error, **stop and tell Pranav.** Options: self-host Appwrite via Docker, pay for one dedicated database, or fall back to `TablesDBMemory` (embeddings in a float-array column, brute-force cosine with `numpy`). The agent must not depend on which implementation is used.

---

## 9. Agent state machine

### 9.1 States

```
IDLE (no run)
  └─(trigger)→ QUEUED
QUEUED → PLANNING → PATCHING → PR_OPEN → AWAITING_CI
AWAITING_CI ─(ci success)→ READY_TO_MERGE ─(merged)→ MERGED → COMPLETED
AWAITING_CI ─(ci failure, attempt < max)→ REPAIRING → AWAITING_CI
AWAITING_CI ─(ci failure, attempt = max)→ GAVE_UP
Any ─(PR closed without merge)→ CANCELLED
Any ─(unexpected error)→ ERRORED
PLANNING ─(no actions)→ NOTHING_TO_DO
```

Terminal: `COMPLETED`, `GAVE_UP`, `CANCELLED`, `ERRORED`, `NOTHING_TO_DO`. On terminal: `repos.active_run_id = None`, `repos.agent_state = idle` (or `error`). That is "sleep".

Implement transitions as a **pure function** `next_state(run, event) -> Transition` in `vulnagent/agent/state_machine.py`; side effects live in `vulnagent/agent/steps.py`.

### 9.2 Transitions

| From | Action | To |
|---|---|---|
| QUEUED | Load open vulns ≥ threshold, not ignored. None → NOTHING_TO_DO. Mark `in_progress`. | PLANNING |
| PLANNING | Fetch manifests at default-branch head; `parse_dependencies` + `plan_upgrades`; save `plan_json`; mark unresolved vulns `unfixable`/`needs_major`. | PATCHING or NOTHING_TO_DO |
| PATCHING | `apply_upgrades`; create branch `vulnagent/<run_id>`; commit via Git Data API with message `fix(deps): resolve N vulnerabilities [vulnagent]`. | PR_OPEN |
| PR_OPEN | Open PR (§9.4), label `vulnagent`. | AWAITING_CI |
| AWAITING_CI | On `workflow_run`/`check_suite` completed for `head_sha`: all pass → READY_TO_MERGE; any fail → REPAIRING or GAVE_UP. No workflows in repo → treat as success after 2 min and note it in the PR. | … |
| REPAIRING | §9.3 | AWAITING_CI (attempt += 1) |
| READY_TO_MERGE | `auto_merge` → enable GitHub auto-merge (squash) or merge; else comment "Ready for review ✅". | wait for `pull_request.closed` |
| MERGED | Mark vulns `fixed` (`resolved_by_run_id`), write success memories, trigger confirmation scan, recompute counts. | COMPLETED |

### 9.3 CI repair step

1. List failed jobs; download logs (`GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs`).
2. Extract relevant lines (`error`, `Error:`, `FAIL`, `TypeError`, `npm ERR!`, stack traces), capped at 4 KB per job. Build `error_signature` by stripping timestamps, absolute paths, line/column numbers, and hex hashes.
3. Query `FailureMemory`.
4. Collect code context: repo files referenced in stack traces (not `node_modules`), max 5 files × 300 lines.
5. Call the LLM (§12); parse into a pydantic model.
6. Validate against safety rules (§11). Invalid → retry the LLM once with the validation error; still invalid → GAVE_UP.
7. Apply search/replace edits (each `search` must match exactly once), commit, update `head_sha`, `attempt += 1`, log `patch_pushed`.
8. `give_up: true` → GAVE_UP.

On GAVE_UP: comment a summary on the PR, add label `vulnagent:needs-human`, set vulns back to `open`, write `failed` memories.

### 9.4 PR body template

```
## 🔒 VulnAgent: dependency security update

Resolves **{n}** vulnerabilities ({critical} critical, {high} high, …).

| Advisory | Package | From → To | Severity | Type |
|---|---|---|---|---|
| GHSA-… / CVE-… | lodash | 4.17.20 → 4.17.21 | high | direct |
| GHSA-… | qs (via express) | 6.5.2 → 6.5.3 | medium | transitive (parent bump) |

### Not fixed
- CVE-… in `foo`: no fixed version available

### Agent log
_Updated automatically as CI runs._

<sub>Generated by VulnAgent. Config: `.vulnagent.yml`. Max CI repair attempts: {max}.</sub>
```

Update the "Agent log" section on each repair attempt.

### 9.5 Concurrency and idempotency

- One active run per repo: check `repos.active_run_id` before creating a run. If set, *Fix now* returns "Agent already working" with the run link. Note the race window in DECISIONS.md.
- `agent_step` payload: `{run_id, expected_state}`. If the stored state differs, exit without action.
- Webhooks: insert `delivery_id` first; on unique-constraint failure, return 200 and stop.
- Ignore CI events for SHAs other than `head_sha`.

---

## 10. Functions and triggers

| Function | Trigger | Responsibility |
|---|---|---|
| `github_webhook` | HTTP (public) | Verify signature, dedupe, route: `installation` / `installation_repositories` → upsert installations and repos, read config; `push` to default branch → reload config if changed, and if a manifest changed and `on_push` → async `scan_repo`; `workflow_run` / `check_suite` completed → async `agent_step`; `pull_request.closed` → MERGED or CANCELLED. Return quickly; heavy work runs async. |
| `scheduler` | Cron `*/15 * * * *` | Repos with `next_scan_at <= now` and valid config → async `scan_repo`; recompute `next_scan_at` with `croniter`. Refresh `advisories` whose OSV `modified` changed (batched, rate-limited). |
| `scan_repo` | Async execution | Fetch manifests → adapters → `DepGraph` → OSV `querybatch` (chunks of 1000) → fetch and cache missing advisories → severity → upsert `repo_packages`, `dependency_edges`, `vulnerabilities` (new → `open`, gone → `fixed`) → update counts → if new vulns and `auto_start` → create run. |
| `on_vuln_created` | Appwrite DB event (row create on `vulnerabilities`) | If `on_new_advisory` and `auto_start`, no active run, severity ≥ threshold → create run. Debounce: skip if a run was created in the last 5 min. |
| `agent_step` | Async execution | Advance one run by one transition. Re-enqueue itself for immediate next states (QUEUED → PLANNING → PATCHING → PR_OPEN); wait for webhooks in AWAITING_CI and READY_TO_MERGE. |
| `api` | HTTP (user JWT) | `POST /link-installation` (verify with the user's GitHub token that they can access the installation, then set `owner_user_id`), `POST /repos/{id}/scan`, `POST /repos/{id}/fix`, `POST /vulns/{id}/ignore` (stretch). Always verify repo ownership. |
| `npm_lockfile` | Sync execution (Node runtime) | §6.4 only. |

**Severity:** prefer OSV `database_specific.severity` → enum; else compute from the CVSS vector with `cvss`; else `unknown`.

**Fixed versions:** from `affected[].ranges[].events[].fixed` where package name and ecosystem match.

---

## 11. Safety rules (enforced in code)

1. Never push to the default branch; only to `vulnagent/*` branches the agent created.
2. LLM may not edit `.github/**`, `.vulnagent.*`, lockfiles, manifest files (`adapter.is_manifest_path`), or paths outside the repo.
3. LLM may not delete or skip tests: reject edits that remove `it(` / `test(` / `describe(` blocks or add `.skip`, `.only`, `xit`, `@ts-ignore`, or `eslint-disable`.
4. Diff cap: max 200 changed lines and 10 files per repair attempt.
5. Never execute target-repo code; `npm install` always uses `--ignore-scripts`.
6. Never send tokens, env vars, or `.env*` contents to the LLM; redact common secret patterns from logs first.
7. Retry cap from config, hard ceiling 5.
8. Major bumps only when `allow_major_bumps: true`.
9. Verify `X-Hub-Signature-256` with `hmac.compare_digest` before any processing.

Unit-test every rule in `backend/tests/test_safety.py`.

---

## 12. LLM prompt contract (REPAIRING)

**System prompt (summary; full text in `vulnagent/llm/prompts/repair.py`):** You are a senior engineer fixing a CI failure caused by a dependency security upgrade. Change application or test code to work with the new versions. Do not downgrade dependencies, edit manifests, lockfiles, or CI config, or weaken tests. Output strict JSON only.

**User content sections:** `UPGRADE_PLAN`, `CI_LOG_EXCERPT`, `SIMILAR_PAST_FIXES` (0–3), `FILES`, `ECOSYSTEM_HINTS`, `ATTEMPT` (n of max), `PREVIOUS_ATTEMPTS`.

**Output (pydantic model `RepairResponse`):**
```json
{
  "analysis": "short root-cause explanation (≤ 3 sentences)",
  "edits": [
    { "path": "src/auth.ts", "search": "exact existing text", "replace": "new text" }
  ],
  "confidence": 0.0,
  "give_up": false,
  "give_up_reason": null
}
```

`analysis` is posted to the PR agent log and the dashboard timeline. Model from `LLM_MODEL`, temperature 0. Strip markdown fences before parsing.

---

## 13. Configuration

### 13.1 Repo config: `.vulnagent.yml` (or `.vulnagent.json`)

```yaml
version: 1
enabled: true
ecosystems: auto            # "auto" or a list, e.g. [npm]
paths: ["."]                # MVP: only "."

scan:
  schedule: "0 6 * * *"     # cron, UTC; null disables
  on_push: true
  on_new_advisory: true

agent:
  auto_start: true          # false = only "Fix now" starts the agent
  severity_threshold: high  # low | medium | high | critical
  max_ci_retries: 3         # hard ceiling 5
  auto_merge: false
  allow_major_bumps: false
  grouping: single_pr       # single_pr | per_package (stretch)
  ignore:
    - id: GHSA-xxxx-xxxx-xxxx
      reason: "Not reachable in our usage"
      expires: 2026-12-31   # optional
```

- Pydantic model in `vulnagent/config/schema.py` with defaults; `yaml.safe_load` only.
- Invalid config → store `config_error`, show it on the dashboard, don't run the agent.
- No config → repo shows as "Not configured" with a copyable sample.

### 13.2 Environment variables

| Name | Used by | Notes |
|---|---|---|
| `APPWRITE_ENDPOINT`, `APPWRITE_PROJECT_ID`, `APPWRITE_API_KEY` | functions, scripts | TablesDB + VectorsDB + functions scopes |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` | functions | handle escaped newlines in the PEM |
| `GITHUB_APP_SLUG` | dashboard | install URL |
| `LLM_API_KEY`, `LLM_MODEL` | functions | |
| `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIM` | functions, bootstrap | |
| `OSV_BASE_URL` | functions | default `https://api.osv.dev` |
| `NPM_LOCKFILE_FUNCTION_ID` | functions | ID of the helper function |
| `VITE_APPWRITE_ENDPOINT`, `VITE_APPWRITE_PROJECT_ID`, `VITE_API_FUNCTION_ID` | dashboard | public values only |

Load backend settings with a pydantic `Settings` class (`pydantic-settings`). Provide `.env.example` with every variable.

---

## 14. Dashboard

### 14.1 Pages

1. **`/login`** — Sign in with GitHub (Appwrite OAuth).
2. **`/` Repos overview**
   - Totals: open vulns across all repos by severity.
   - **Install GitHub App** button → `https://github.com/apps/<slug>/installations/new`. The app's setup URL returns to `/setup?installation_id=…`, which calls `api /link-installation`.
   - Table: repo, ecosystem badges, severity counts, agent state badge (Sleeping 😴 / Scanning / Working / Needs human / Error), last scan, **Scan now**, **Fix now**.
   - Unconfigured repos show "Add `.vulnagent.yml`" with a copy button.
3. **`/repos/:id` Repo detail**
   - Vulns table: advisory ID + CVE aliases (link to osv.dev), package, installed → fixed, severity, direct/transitive, status; filters.
   - Clicking a transitive vuln shows its dependency path from `dependency_edges`.
   - Agent panel: step indicator (Planning → PR → CI → Repair → Merge), PR link, attempt `n/max`, live `agent_events` timeline; `memory_hit` events highlighted.
   - Past runs list.
4. **`/setup`** — completes linking, redirects to `/`.

### 14.2 Realtime

Subscribe to `repos`, `vulnerabilities`, and `agent_events` changes the user can read; invalidate TanStack Query caches on events. Counts and timeline update without refresh.

### 14.3 Look

Dark theme by default, monospace for package names and versions. Severity colors: critical red, high orange, medium amber, low gray-blue. Must look good at 1280×720.

---

## 15. Repository layout

```
vulnagent/
├── INITIALPROJECT.md
├── .env.example
├── .gitignore
├── appwrite.config.json          # Appwrite CLI: functions, settings
├── docs/
│   ├── DECISIONS.md
│   └── ARCHITECTURE.md           # Mermaid diagrams of components + state machine
├── backend/
│   ├── pyproject.toml            # uv; ruff + mypy config
│   ├── src/vulnagent/
│   │   ├── core/                 # models, adapter protocol, safety rules, errors
│   │   ├── adapters/
│   │   │   ├── __init__.py       # ADAPTERS registry, detect_adapters
│   │   │   └── npm/              # parser, planner, applier, registry client
│   │   ├── osv/                  # client, severity, fixed-version extraction
│   │   ├── github/               # app auth, contents/git data, PRs, checks, logs, webhooks
│   │   ├── llm/                  # LLMProvider, EmbeddingProvider, prompts, schemas
│   │   ├── memory/               # FailureMemory protocol, VectorsDB + TablesDB impls
│   │   ├── db/                   # typed repositories, one module per table
│   │   ├── config/               # repo config schema + parsing; Settings
│   │   ├── agent/                # state_machine.py (pure), steps.py (side effects)
│   │   └── scanning/             # scan orchestration
│   ├── functions/
│   │   ├── github_webhook/src/main.py
│   │   ├── scheduler/src/main.py
│   │   ├── scan_repo/src/main.py
│   │   ├── on_vuln_created/src/main.py
│   │   ├── agent_step/src/main.py
│   │   └── api/src/main.py
│   └── tests/
│       ├── fixtures/npm/         # real lockfiles: v2, v3, nested, scoped
│       └── test_*.py
├── functions-node/
│   └── npm_lockfile/             # the only Node function (§6.4)
├── apps/
│   └── dashboard/                # Vite + React + TS
├── worker/                       # only if the npm_lockfile spike fails
└── scripts/
    ├── bootstrap_db.py           # idempotent TablesDB + VectorsDB schema
    ├── seed_memory.py
    ├── build_functions.py        # vendor vulnagent/ into each function
    └── reset_test_repo.sh        # reset the test target repo (§16)
```

---

## 16. Test target repo

A separate public repo `vulnagent-test-app` used for end-to-end testing:

- Small Express + TypeScript API with a real Vitest suite and a GitHub Actions workflow (`npm ci && npm test`).
- Pinned to old versions with known OSV advisories:
  - one **direct** dependency with a non-breaking patch fix (e.g. old `lodash`);
  - one **transitive** vulnerability fixable by a parent bump;
  - one dependency whose fix is a **major bump with a breaking change the tests exercise** (e.g. `jsonwebtoken` 8.x → 9.x; **verify the advisories and breaking behavior via OSV and the changelog first**).
- `.vulnagent.yml` with `allow_major_bumps: true`, `severity_threshold: medium`, `auto_merge: true`, `max_ci_retries: 3`.
- `scripts/reset_test_repo.sh`: force-reset the repo to the vulnerable state, close open agent PRs, delete `vulnagent/*` branches, and reset the repo's rows in Appwrite.

---

## 17. Milestones (build in this order)

Today is **Oct 21**.

### M0 — Foundations and spikes (Oct 21–22)
- Repo scaffold: uv workspace, ruff, mypy strict, pytest; dashboard scaffold; GitHub Actions for this repo (lint, type-check, test).
- Appwrite project; `bootstrap_db.py` creates all TablesDB tables.
- **Spike A:** create VectorsDB and `ci_failures`; insert and query one vector (§8).
- **Spike B:** `npm_lockfile` Node function regenerates a lockfile (§6.4).
- **Spike C:** a hello-world Python function deployed with vendored `vulnagent` via `build_functions.py`.
- GitHub App registered (§18); `github_webhook` verifies signatures and dedupes.
- **Done when:** installing the app on the test repo creates `installations` and `repos` rows.

### M1 — Scanning (Oct 22–23)
- `config`, `osv`, npm `detect` + `parse_dependencies` with fixture tests.
- `scan_repo` end to end; severity counts on `repos`.
- `scheduler` (cron) and `on_push` trigger.
- **Done when:** scanning the test repo fills `vulnerabilities` correctly and a transitive vuln traces to ROOT through `dependency_edges`.

### M2 — Planning and PR (Oct 24–25)
- `plan_upgrades` (direct, parent bump, override) with tests, including transitive.
- `apply_upgrades` with lockfile regeneration.
- State machine QUEUED → AWAITING_CI; PR with the §9.4 body.
- `pull_request.closed` → MERGED/CANCELLED → COMPLETED.
- **Done when:** a run opens a correct PR, and merging it marks vulns `fixed` and returns the repo to idle.

### M3 — CI repair loop and memory (Oct 26–27)
- Log fetch and extraction; error signatures.
- `llm` with the repair prompt and `RepairResponse`.
- Safety rules with tests.
- `memory` read and write paths; `seed_memory.py`.
- **Done when:** on the test repo, CI fails on the breaking change, a `memory_hit` is logged, the fix is pushed, and CI passes.

### M4 — Dashboard (Oct 28–29)
- Auth, installation linking, overview, repo detail, agent panel, Realtime.
- *Scan now* / *Fix now* through `api`.
- Optional deploy to Appwrite Sites.
- **Done when:** the §1 end-to-end flow works from the dashboard without touching GitHub manually.

### M5 — Hardening (Oct 30)
- Run the end-to-end flow three times from `reset_test_repo.sh`; fix flakiness.
- `docs/ARCHITECTURE.md` with Mermaid diagrams.

**Cut order if behind:** `on_vuln_created` → past runs list → advisory refresh → dependency path UI → Appwrite Sites deploy. **Never cut:** PR creation, CI repair loop, VectorsDB memory, live dashboard updates.

---

## 18. GitHub App configuration

- **Repository permissions:** Contents read & write · Pull requests read & write · Checks read · Actions read · Metadata read · Commit statuses read.
- **Do not request** Workflows write.
- **Events:** Installation, Installation repositories, Push, Pull request, Workflow run, Check suite.
- **Webhook URL:** `github_webhook` function's public domain.
- **Setup URL:** `<dashboard>/setup`, with "Redirect on update" enabled.
- Commits authored by the app bot (`vulnagent[bot]`).

---

## 19. Testing

- **Unit (required):** npm lockfile parsing (v2, v3, nested, scoped), OSV fixed-version and severity extraction, planner (direct, parent bump, override, needs_major, no_fix, conflict), config validation and defaults, safety rules, error-signature normalization, `next_state` transitions, webhook signature verification.
- **Integration (light):** `scan_repo` against recorded OSV and GitHub responses (`respx`).
- **Manual end-to-end:** the §1 flow on the test target repo.
- Coverage target for `vulnagent/core`, `adapters`, `agent`: ≥ 80%.

---

## 20. Definition of done (code)

- [ ] §1 end-to-end flow works three times in a row from a reset.
- [ ] `ruff`, `mypy --strict`, and `pytest` pass in CI; dashboard type-checks and builds.
- [ ] No secrets in git history.
- [ ] `docs/DECISIONS.md` records the outcome of all M0 spikes.