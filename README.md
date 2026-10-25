# VulnAgent

An autonomous dependency-security agent for GitHub repositories. It scans your
dependency tree against OSV, opens one pull request that fixes what it can, and
when CI breaks on the upgrade it reads the logs, recalls how a similar failure
was fixed before, and pushes a patch. When the PR merges, it goes back to sleep.

## Quickstart

```bash
make install    # backend and dashboard dependencies
make demo       # open http://localhost:5173
make check      # lint, type-check and test everything
```

`make demo` runs the dashboard on demo data, so you can see the whole
interface before any credentials exist. Press **Fix now** on the test
repository to watch an agent run play out: plan, pull request, CI failure,
memory hit, repair, merge, counts back to zero.

Run `make` on its own for every target.

## Setting it up for real

```bash
make env        # create .env from the example, then fill it in
make doctor     # check the toolchain and which variables are still empty
make bootstrap  # create the TablesDB schema and the vector store
make seed       # seed the failure memory
make deploy     # run the checks, package the functions and push them
```

## Docs

- [Architecture](docs/architecture.md) — components, the agent state machine, how a run flows
- [Setup](docs/setup.md) — Appwrite, the GitHub App, and every environment variable
- [Decisions](docs/DECISIONS.md) — every deviation from the spec, with its reason
- [PROJECT.md](PROJECT.md) — the original specification

## Layout

| Path | What lives there |
|---|---|
| `backend/src/vulnagent/` | All shared logic: adapters, OSV, GitHub, the agent, the database |
| `backend/functions/` | Appwrite function entry points, each a thin `main.py` |
| `functions-node/npm_lockfile/` | The one Node function, which owns `npm install` |
| `apps/dashboard/` | Vite + React + TypeScript dashboard |
| `scripts/` | Bootstrap, seeding, packaging and test-repo reset |
