# VulnAgent

An autonomous dependency-security agent for GitHub repositories. It scans your
dependency tree against OSV, opens one pull request that fixes what it can, and
when CI breaks on the upgrade it reads the logs, recalls how a similar failure
was fixed before, and pushes a patch. When the PR merges, it goes back to sleep.

## Quickstart

```bash
cd backend && uv sync --extra dev        # install the backend
uv run pytest                            # run the test suite
cd ../apps/dashboard && npm install      # install the dashboard
npm run dev                              # open http://localhost:5173
```

The dashboard runs on demo data until `VITE_APPWRITE_PROJECT_ID` is set, so you
can see the whole interface, including a scripted agent run, before any
credentials exist.

## Setting it up for real

```bash
cp .env.example .env                                  # fill in the values
uv run python scripts/bootstrap_db.py                 # create the tables
uv run python scripts/bootstrap_vectors.py            # create the vector store
uv run python scripts/seed_memory.py                  # seed the failure memory
uv run python scripts/build_functions.py              # vendor the shared package
appwrite push functions                               # deploy
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
