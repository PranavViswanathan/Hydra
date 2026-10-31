# Architecture

How the pieces fit, why the boundaries are where they are, and what happens
between a webhook arriving and a pull request merging.

- [The shape of the system](#the-shape-of-the-system)
- [Layering](#layering)
- [What runs where](#what-runs-where)
- [A run, end to end](#a-run-end-to-end)
- [The four design principles](#the-four-design-principles)
- [Where state lives](#where-state-lives)
- [Failure handling](#failure-handling)

## The shape of the system

```mermaid
flowchart TB
    subgraph GH["GitHub (target repository)"]
        CONFIG[".vulnagent.yml"]
        CODE["source + manifests"]
        ACTIONS["Actions CI"]
    end

    subgraph AW["Appwrite project"]
        subgraph FN["Functions"]
            WEBHOOK["github_webhook<br/>HTTP, public"]
            SCHED["scheduler<br/>cron */15"]
            SCAN["scan_repo<br/>async"]
            STEP["agent_step<br/>async"]
            VULNEV["on_vuln_created<br/>DB event"]
            API["api<br/>HTTP, user JWT"]
            LOCK["npm_lockfile<br/>Node, sync"]
        end
        TABLES[("TablesDB<br/>11 tables")]
        VECTORS[("VectorsDB<br/>ci_failures")]
        EMBED["Embeddings service"]
    end

    DASH["Dashboard<br/>React SPA"]
    OSV["api.osv.dev"]
    NPM["registry.npmjs.org"]
    LLM["Anthropic"]

    GH -- "webhooks" --> WEBHOOK
    WEBHOOK --> SCAN
    WEBHOOK --> STEP
    SCHED --> SCAN
    SCAN --> OSV
    SCAN --> TABLES
    TABLES -. "row created" .-> VULNEV
    VULNEV --> STEP
    STEP --> NPM
    STEP --> LLM
    STEP --> VECTORS
    STEP --> TABLES
    STEP --> LOCK
    STEP -- "branches, commits, PRs" --> GH
    ACTIONS -- "results and logs" --> STEP
    VECTORS <--> EMBED
    DASH -- "Web SDK + Realtime" --> TABLES
    DASH --> API
    API --> SCAN
    API --> STEP
```

Nothing polls GitHub. Every transition is driven by a webhook, a cron tick, a
database event, or a dashboard button.

## Layering

The dependency arrows all point one way. Nothing in `core/` imports Appwrite,
GitHub or httpx, which is why most of the system can be tested without them.

```mermaid
flowchart TD
    FUNCTIONS["functions/*/src/main.py<br/><i>parse the request, call the core, return</i>"]
    RUNTIME["runtime.py<br/><i>composition root</i>"]
    SERVICES["services/<br/><i>triggers, installation sync, linking</i>"]
    AGENT["agent/ · scanning/<br/><i>orchestration</i>"]
    IO["github/ · osv/ · db/ · memory/ · llm/<br/><i>the outside world, behind protocols</i>"]
    ADAPTERS["adapters/npm/<br/><i>ecosystem specifics</i>"]
    CORE["core/<br/><i>models, protocols, safety, purl</i>"]

    FUNCTIONS --> RUNTIME
    FUNCTIONS --> SERVICES
    RUNTIME --> IO
    SERVICES --> AGENT
    AGENT --> IO
    AGENT --> ADAPTERS
    IO --> CORE
    ADAPTERS --> CORE
    AGENT --> CORE
```

| Layer | Rule it follows | Why it matters |
|---|---|---|
| `core/` | No I/O, no vendor SDKs | The rules and models stay testable and reusable |
| `adapters/` | Knows one ecosystem, implements `EcosystemAdapter` | Adding Maven touches nothing else |
| `db/`, `github/`, `osv/`, `memory/`, `llm/` | One module per external system, behind a protocol | Each is swappable and stubbable |
| `agent/`, `scanning/` | Orchestration only, no vendor calls of their own | Decisions stay separable from effects |
| `services/` | The decisions a function would otherwise inline | Trigger logic is unit-tested, not deploy-tested |
| `functions/` | Parse, delegate, return | Nothing worth testing lives in a file you cannot import |

The one rule with teeth: **no raw Appwrite SDK call exists outside `db/` and
`memory/`**. Everything else works with the typed models in `db/rows.py`.

## What runs where

| Function | Trigger | Timeout | Does |
|---|---|---|---|
| `github_webhook` | HTTP, public | 30s | Verify the signature, claim the delivery, route, return |
| `scheduler` | cron `*/15 * * * *` | 120s | Find repos whose `next_scan_at` has passed, enqueue scans |
| `scan_repo` | async execution | 900s | Manifests to findings to rows to counts |
| `agent_step` | async execution | 900s | Advance one run by exactly one transition |
| `on_vuln_created` | DB row-create event | 30s | Maybe start a run for a newly discovered advisory |
| `api` | HTTP, user JWT | 30s | Dashboard actions: link, scan now, fix now |
| `npm_lockfile` | sync execution (Node) | 300s | `npm install --package-lock-only --ignore-scripts` |

`github_webhook` never does real work itself. It returns inside its 30 seconds
and hands everything heavier to an async execution, because GitHub will retry a
delivery that takes too long.

## A run, end to end

```mermaid
sequenceDiagram
    autonumber
    participant D as Dashboard
    participant API as api
    participant S as agent_step
    participant G as GitHub
    participant R as registry.npmjs.org
    participant N as npm_lockfile
    participant M as Failure memory
    participant L as LLM

    D->>API: POST /repos/{id}/fix
    API->>S: async execution (QUEUED)

    Note over S: QUEUED
    S->>S: select open vulns above the threshold with a known fix
    S->>S: mark them in_progress

    Note over S: PLANNING
    S->>G: read package.json and package-lock.json at the default branch head
    S->>R: which versions of express admit a fixed qs?
    S->>S: plan: bump lodash, bump express for qs, override minimist

    Note over S: PATCHING
    S->>N: regenerate the lockfile from the rewritten manifest
    N-->>S: new package-lock.json
    S->>G: create vulnagent/{run id}, commit both files

    Note over S: PR_OPEN
    S->>G: open the pull request, add the vulnagent label

    Note over S: AWAITING_CI
    G-->>S: workflow_run completed, conclusion failure

    Note over S: REPAIRING
    S->>G: download the failed job logs
    S->>S: extract the excerpt, normalise an error signature
    S->>M: search by signature, ecosystem npm, outcome success
    M-->>S: a past fix at 0.93 similarity
    S->>G: fetch the repo files named in the stack
    S->>L: plan + logs + past fix + files + attempt 1 of 3
    L-->>S: search/replace edits
    S->>S: check the edits against the safety rules
    S->>G: commit the repair, attempt becomes 1

    Note over S: AWAITING_CI
    G-->>S: workflow_run completed, conclusion success

    Note over S: READY_TO_MERGE → MERGED
    S->>G: squash merge (auto_merge is on)
    G-->>S: pull_request closed, merged true
    S->>S: mark the vulnerabilities fixed, recompute counts
    S->>M: record what worked

    Note over S: COMPLETED — the repo goes back to sleep
```

Each numbered step above is a separate function execution wherever an arrow
leaves the diagram and comes back. Nothing waits in memory for GitHub.

## The four design principles

### 1. The core is ecosystem-agnostic

Nothing outside `adapters/npm/` knows what a `package.json` is. The scanner and
the agent call `EcosystemAdapter` methods and work with `DepGraph`,
`VulnFinding` and `UpgradePlan`. See [Adding an ecosystem](adapters.md).

### 2. The agent is a persisted state machine

One execution loads a run, performs one transition, saves, and exits. There is
no long-running process, so there is nothing to lose when a function restarts,
and any step can be retried. The decision is a pure function
(`agent/state_machine.py`), the effects are separate (`agent/steps.py`).
See [The agent](agent.md).

### 3. Manifest changes are deterministic; the model only fixes breakage

Which version to upgrade to is computed from OSV data and the registry, never
guessed by a model. The LLM is reached for only after CI fails, and only to
change application code. See [Upgrade planning](upgrade-planning.md) and
[CI repair](ci-repair.md).

### 4. CI is the test runner

VulnAgent never executes a target repository's code. The only place `npm` runs
is the Node helper function, always with `--ignore-scripts`, and it only ever
resolves a lockfile. Whether an upgrade actually works is answered by the
repository's own CI.

## Where state lives

```mermaid
flowchart LR
    subgraph Durable["TablesDB"]
        R["repos<br/>agent_state, active_run_id, counts"]
        RUN["agent_runs<br/>state, attempt, plan_json"]
        V["vulnerabilities<br/>status per advisory"]
        E["agent_events<br/>the timeline"]
    end
    subgraph Derived["Rebuilt every scan"]
        P["repo_packages"]
        ED["dependency_edges"]
    end
    subgraph Cached["Shared cache"]
        A["advisories<br/>OSV records"]
        CF["ci_failures<br/>what fixed what"]
    end

    R --> RUN --> E
    R --> V
```

- **`repos.active_run_id`** is the concurrency lock. At most one run per repo.
- **`agent_runs.state`** is the resume point. A function execution is stateless;
  the row is the truth.
- **`repo_packages` and `dependency_edges`** are a snapshot, deleted and
  rewritten on every scan rather than merged.
- **`advisories`** is a global cache keyed by OSV id, shared across every repo.
- **`ci_failures`** is the only state that improves with age.

## Failure handling

| Failure | What happens |
|---|---|
| Webhook redelivered | `webhook_deliveries` claims the id; the second attempt returns 200 and stops |
| Two CI events for the same run | Events for any SHA other than `head_sha` are ignored |
| Stale async execution | `agent_step` compares `expected_state` with the stored state and exits if they differ |
| A step raises | The run moves to `ERRORED`, the repo is released, the error is on the timeline |
| CI never goes green | The attempt budget runs out, the run gives up, the PR is labelled for a human |
| Model returns nonsense | Reparsed once with the validation error, then the run gives up |
| Model returns something unsafe | Refused by `core/safety.py` before anything is committed |
| Appwrite is down mid-run | The run stays where it was; the next trigger resumes it from the row |

The common thread: no failure leaves a repository stuck with
`agent_state: working` and no run to advance it. Every terminal state releases
the lock.
