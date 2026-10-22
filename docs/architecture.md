# Architecture

## Components

```mermaid
flowchart TB
    subgraph GH["GitHub (target repository)"]
        CONFIG[".vulnagent.yml"]
        ACTIONS["Actions CI"]
    end

    subgraph AW["Appwrite project"]
        subgraph FN["Functions"]
            WEBHOOK["github_webhook (HTTP)"]
            SCHED["scheduler (cron */15)"]
            SCAN["scan_repo (async)"]
            STEP["agent_step (async)"]
            VULNEV["on_vuln_created (DB event)"]
            API["api (HTTP, user JWT)"]
            LOCK["npm_lockfile (Node)"]
        end
        TABLES[("TablesDB")]
        VECTORS[("VectorsDB: ci_failures")]
    end

    DASH["Dashboard"]
    OSV["api.osv.dev"]
    NPM["registry.npmjs.org"]
    LLM["Anthropic"]

    GH -- webhooks --> WEBHOOK
    WEBHOOK --> SCAN & STEP
    SCHED --> SCAN
    SCAN --> OSV & TABLES
    TABLES -. row created .-> VULNEV
    VULNEV --> STEP
    STEP --> NPM & LLM & VECTORS & TABLES
    STEP --> LOCK
    STEP -- "PRs, commits" --> GH
    ACTIONS -- "results, logs" --> STEP
    DASH -- "Web SDK + Realtime" --> TABLES
    DASH --> API
    API --> SCAN & STEP
```

The core never parses `package.json`. It calls `EcosystemAdapter` methods, so
adding Maven or PyPI means adding a module under `adapters/` and registering
it: no change to the agent, the scanner or the database.

## The agent state machine

```mermaid
stateDiagram-v2
    [*] --> QUEUED: trigger
    QUEUED --> PLANNING: vulnerabilities selected
    QUEUED --> NOTHING_TO_DO: nothing eligible
    PLANNING --> PATCHING: plan ready
    PLANNING --> NOTHING_TO_DO: nothing upgradable
    PATCHING --> PR_OPEN: branch pushed
    PR_OPEN --> AWAITING_CI: pull request opened
    AWAITING_CI --> READY_TO_MERGE: CI passed
    AWAITING_CI --> REPAIRING: CI failed, attempts left
    AWAITING_CI --> GAVE_UP: CI failed, no attempts left
    REPAIRING --> AWAITING_CI: patch pushed
    REPAIRING --> GAVE_UP: unsafe patch or model gave up
    READY_TO_MERGE --> MERGED: merged
    MERGED --> COMPLETED: vulnerabilities marked fixed
    AWAITING_CI --> CANCELLED: PR closed unmerged
    PLANNING --> ERRORED: unexpected error
    COMPLETED --> [*]
    GAVE_UP --> [*]
    CANCELLED --> [*]
    ERRORED --> [*]
    NOTHING_TO_DO --> [*]
```

Terminal states release the repository: `active_run_id` goes back to null and
`agent_state` to `idle`. That is what "sleeping" means.

The decision half is a pure function, `agent/state_machine.py:next_state`. The
side effects live in `agent/steps.py`. Keeping them apart is what makes the
attempt accounting that stops the repair loop testable on its own.

## A run, end to end

```mermaid
sequenceDiagram
    participant D as Dashboard
    participant A as agent_step
    participant G as GitHub
    participant M as Failure memory
    participant L as LLM

    D->>A: Fix now
    A->>G: read manifests at the default branch head
    A->>A: plan upgrades (direct, parent bump, override)
    A->>G: commit to vulnagent/<run id>
    A->>G: open the pull request
    G-->>A: workflow_run completed (failure)
    A->>G: download the failed job logs
    A->>A: extract the excerpt, normalise a signature
    A->>M: search for a similar past failure
    M-->>A: a fix that worked (similarity 0.93)
    A->>L: upgrade plan, logs, past fix, the files in the stack
    L-->>A: search/replace edits
    A->>A: check the edits against the safety rules
    A->>G: push the repair
    G-->>A: workflow_run completed (success)
    A->>G: merge
    A->>M: record what worked
```

## Why these boundaries

**The agent is a persisted state machine, not a long-running process.** Each
execution loads a run, performs one transition, saves and exits, so nothing
depends on a process staying alive and any step can be retried.

**Manifest changes are deterministic; the model only fixes breakage.** Which
version to upgrade to is computed from OSV data and the registry. The LLM is
reached for only when CI breaks, and only to change application code.

**CI is the test runner.** VulnAgent never executes a target repository's code;
`npm install` always runs with `--ignore-scripts`, in the one Node function
that exists for that purpose.

**Safety rules are code, not prompt text.** `core/safety.py` enforces them and
`tests/test_safety.py` covers each one. The prompt asks the model to behave;
the rules are what stop it when it does not.
