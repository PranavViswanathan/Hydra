# Setup

Everything VulnAgent needs before it can run against a real repository.

## 1. Appwrite

1. Create a project, note its ID.
2. Create a server API key with these scopes: `databases.read`,
   `databases.write`, `documents.read`, `documents.write`, `functions.read`,
   `functions.write`, `execution.write`, `users.read`.
3. Install the CLI and sign in:

   ```bash
   npm install -g appwrite-cli
   appwrite login
   ```

4. Create the schema:

   ```bash
   cd backend
   uv run python ../scripts/bootstrap_db.py          # tables, columns, indexes
   uv run python ../scripts/bootstrap_vectors.py     # vector store (spike A)
   ```

   `bootstrap_db.py --check` reports what is missing without changing anything.

**If `bootstrap_vectors.py` exits 2**, VectorsDB needs a dedicated database on
your plan. Three options: self-host Appwrite with Docker, pay for one dedicated
database, or do nothing and let the agent use `TablesDBMemory`, which it falls
back to automatically. The agent works either way.

## 2. GitHub App

Create one at <https://github.com/settings/apps/new>.

| Setting | Value |
|---|---|
| Repository permissions | Contents **read & write**, Pull requests **read & write**, Checks **read**, Actions **read**, Metadata **read**, Commit statuses **read** |
| Do **not** request | Workflows write |
| Subscribe to events | Installation, Installation repositories, Push, Pull request, Workflow run, Check suite |
| Webhook URL | the deployed `github_webhook` function's domain |
| Webhook secret | anything long and random; it goes in `GITHUB_WEBHOOK_SECRET` |
| Setup URL | `<dashboard>/setup`, with "Redirect on update" enabled |

Generate a private key and download the PEM.

The webhook URL is a chicken-and-egg: deploy the functions once to get the
domain, then come back and fill it in. For local development, point the webhook
at a [smee.io](https://smee.io) channel and forward it to your machine.

## 3. Environment

Copy `.env.example` to `.env` and fill it in.

| Variable | Notes |
|---|---|
| `APPWRITE_ENDPOINT` | `https://cloud.appwrite.io/v1` unless self-hosting |
| `APPWRITE_PROJECT_ID`, `APPWRITE_API_KEY` | from step 1 |
| `GITHUB_APP_ID` | the numeric id, not the slug |
| `GITHUB_APP_PRIVATE_KEY` | the PEM; one line with `\n` escapes is accepted |
| `GITHUB_WEBHOOK_SECRET` | must match the app |
| `GITHUB_APP_SLUG` | used to build the install link in the dashboard |
| `LLM_API_KEY`, `LLM_MODEL` | Anthropic; `claude-opus-5` by default |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `all-minilm`/384 or `nomic-embed-text`/768. Appwrite provides the embeddings, so `EMBEDDING_API_KEY` stays empty |
| `NPM_LOCKFILE_FUNCTION_ID` | the deployed Node function's id |
| `VITE_*` | public values for the dashboard only |

Only the Appwrite and GitHub variables are required to boot. A deployment
without `LLM_*` scans and opens pull requests but cannot repair CI.

## 4. Deploy

```bash
uv run python scripts/build_functions.py   # vendor vulnagent/ into each function
appwrite push functions
```

`build_functions.py` exists because Appwrite builds each function from its own
folder and cannot see the uv workspace. Re-run it after any change to
`backend/src/vulnagent/`.

## 5. Dashboard

```bash
cd apps/dashboard
npm install
npm run dev
```

With no `VITE_APPWRITE_PROJECT_ID` it runs on demo data. Set the three `VITE_`
variables to point it at your project. Deploying to Appwrite Sites is optional;
any static host works.

## 6. Test repository

The end-to-end flow needs a repository that is actually vulnerable. Create a
public `vulnagent-test-app` with a small Express + TypeScript API, a real
Vitest suite, and a workflow running `npm ci && npm test`, pinned to:

- a **direct** dependency with a non-breaking patch fix (old `lodash`)
- a **transitive** vulnerability fixable by bumping its parent (`qs` via `express`)
- a dependency whose fix is a **major bump that breaks a test**
  (`jsonwebtoken` 8 to 9) — verify the advisory and the breaking behavior
  against OSV and the changelog first

Tag the vulnerable state `vulnerable-baseline`, then reset between runs with:

```bash
./scripts/reset_test_repo.sh pranav/vulnagent-test-app
uv run python scripts/reset_test_rows.py pranav/vulnagent-test-app
```
