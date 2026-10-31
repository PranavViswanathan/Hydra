# Hydra

An autonomous dependency-security agent for GitHub repositories. It scans your
dependency tree against OSV, opens one pull request that fixes what it can, and
when CI breaks on the upgrade it reads the logs, recalls how a similar failure
was fixed before, and pushes a patch. When the PR merges, it goes back to sleep.

<img width="1422" height="802" alt="image" src="https://github.com/user-attachments/assets/7e7d3502-c271-415e-a8e0-3d13773ef3d1" />

```
Dashboard shows 4 open vulns  →  Fix now  →  PR #42 opens  →  CI fails on a breaking change
       ↑                                                              ↓
   counts drop to 0  ←  merged  ←  CI passes  ←  patch pushed  ←  memory hit (0.93)
```

## Quickstart

```bash
make install    # backend and dashboard dependencies
make demo       # open http://localhost:5173
make check      # lint, type-check and test everything
```

`make demo` runs the dashboard on demo data, so you can see the whole interface
before any credentials exist. Press **Fix now** on the test repository to watch
an agent run play out. Run `make` on its own for every target.

## Setting it up for real

```bash
make env        # create .env from the example, then fill it in
make doctor     # check the toolchain and which variables are still empty
make bootstrap  # create the TablesDB schema and the vector store
make seed       # seed the failure memory
make deploy     # run the checks, package the functions and push them
```

Full walkthrough in [docs/setup.md](docs/setup.md).

## Documentation

**Understanding it**

| Document | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | Components, layering, how a request becomes a pull request |
| [The agent](docs/agent.md) | The state machine, every transition, idempotency and concurrency |
| [Scanning](docs/scanning.md) | Manifests to findings: OSV, severity, reconciliation |
| [Upgrade planning](docs/upgrade-planning.md) | Direct bumps, parent bumps, overrides, and why each is chosen |
| [CI repair](docs/ci-repair.md) | Logs to signature to memory to patch, and what stops a bad one |
| [Failure memory](docs/memory.md) | Embeddings, vector search, the TablesDB fallback |
| [Safety rules](docs/safety.md) | All nine rules, where each is enforced and tested |
| [Data model](docs/data-model.md) | Every table, column, index and relationship |

**Working on it**

| Document | What it covers |
|---|---|
| [Setup](docs/setup.md) | Appwrite, the GitHub App, the test repository |
| [Configuration](docs/configuration.md) | `.vulnagent.yml` and every environment variable |
| [Development](docs/development.md) | Make targets, testing approach, conventions |
| [Adding an ecosystem](docs/adapters.md) | What a new adapter has to implement |
| [Dashboard](docs/dashboard.md) | Pages, demo mode, live updates |
| [Deployment](docs/deployment.md) | Function packaging, timeouts, what runs where |
| [Troubleshooting](docs/troubleshooting.md) | Symptoms, causes and fixes |
| [Decisions](docs/DECISIONS.md) | Every deviation from the spec, with its reason |

[PROJECT.md](PROJECT.md) is the original specification the build follows.

## Layout

```
backend/
  src/vulnagent/        all shared logic, importable and unit-testable
    core/               models, adapter protocol, safety rules, purl, errors
    adapters/npm/       lockfile parsing, planning, applying, the registry
    osv/                advisory client, severity banding, fixed versions
    github/             app auth, REST client, PR body, webhook parsing
    agent/              state machine (pure), steps (effects), CI log analysis
    scanning/           scan orchestration and reconciliation
    memory/             failure memory: protocol, VectorsDB, TablesDB fallback
    llm/                provider protocol, repair prompt, response schema
    db/                 typed repositories, one per table
    config/             repo config schema, process settings
    services/           triggers, installation sync, account linking
    runtime.py          composition root
  functions/            Appwrite entry points, one thin main.py each
  tests/                667 tests, mirroring behavior rather than modules
functions-node/
  npm_lockfile/         the one Node function, which owns `npm install`
apps/dashboard/         Vite + React + TypeScript, with a demo mode
scripts/                bootstrap, seeding, packaging, test-repo reset
```

## Status

| Area | State |
|---|---|
| Core, adapters, agent, scanning, safety | Built and tested (667 tests) |
| Dashboard | Built and tested (16 tests), demo mode works |
| Appwrite calls | Written against the installed SDK, **never run live** |
| `npm_lockfile` Node function | Written, **never executed** |
| End-to-end flow | Not yet run; needs credentials and the test repository |

The two unverified areas are M0 spikes A and B from the spec. See
[Troubleshooting](docs/troubleshooting.md) for what to expect the first time
they run.
