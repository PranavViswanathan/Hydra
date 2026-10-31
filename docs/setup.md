# Setup

A walkthrough from nothing to a working agent. For the reference tables, see
[Configuration](configuration.md); for what gets pushed where, see
[Deployment](deployment.md).

Budget about an hour, most of it waiting on GitHub and Appwrite consoles.

- [Before you start](#before-you-start)
- [1. Appwrite project](#1-appwrite-project)
- [2. The schema](#2-the-schema)
- [3. GitHub App](#3-github-app)
- [4. Environment](#4-environment)
- [5. Deploy](#5-deploy)
- [6. Close the loop](#6-close-the-loop)
- [7. Dashboard](#7-dashboard)
- [8. Test repository](#8-test-repository)
- [9. The first end-to-end run](#9-the-first-end-to-end-run)

## Before you start

```bash
make doctor
```

You need `uv`, `python3`, `node`, `npm`, and the Appwrite CLI. `gh` is only
needed for the test-repo reset script.

```bash
npm install -g appwrite-cli
appwrite login
```

## 1. Appwrite project

Create a project and note its ID. Then create a **server API key** with:

```
databases.read    databases.write
documents.read    documents.write
functions.read    functions.write
execution.write   users.read
```

This key is the one every function uses. It never reaches the browser.

Copy the project's **API Endpoint** from its Settings page too. Newer Appwrite
Cloud projects are regional (`https://nyc.cloud.appwrite.io/v1` and so on),
and the generic `https://cloud.appwrite.io/v1` answers them with "Project is
not accessible in this region". It goes in both `APPWRITE_ENDPOINT` and
`VITE_APPWRITE_ENDPOINT`.

## 2. The schema

```bash
make env     # creates .env from the example
# fill in APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID, APPWRITE_API_KEY
make bootstrap
```

That runs two scripts:

**`bootstrap_db.py`** creates the database, eleven tables, their columns and
indexes. One of them, `ci_failures`, is the failure memory's TablesDB fallback.
It is idempotent: anything already present is left alone, so re-run it after
pulling a schema change. `make bootstrap-check` reports drift without touching
anything.

Being idempotent by existence, it never resizes a column that is already
there. If a run fails partway on a fresh project, delete the `vulnagent`
database in the console and run it again rather than patching columns.

**`bootstrap_vectors.py`** creates the vector store. This is M0 spike A, and
it is allowed to fail.

> **If it exits 2**, VectorsDB needs a dedicated database on your plan. Your
> options are self-hosting, paying for one dedicated database, or doing
> nothing and letting `TablesDBMemory` take over, which happens automatically
> with no code change. See [Failure memory](memory.md#two-implementations).

Then seed the memory so the first repair has something to recall:

```bash
make seed
```

## 3. GitHub App

Create one at <https://github.com/settings/apps/new>.

**Repository permissions**

| Permission | Level | Why |
|---|---|---|
| Contents | read & write | Read manifests, push branches and commits |
| Pull requests | read & write | Open, label, comment, merge |
| Checks | read | See whether CI passed |
| Actions | read | Download job logs for the repair step |
| Metadata | read | Mandatory |
| Commit statuses | read | Older CI integrations report here |

**Do not** request Workflows write. The agent must not be able to edit CI, and
not holding the permission is a stronger guarantee than a code rule.

**Subscribe to events**

Installation · Installation repositories · Push · Pull request ·
Workflow run · Check suite

**Other settings**

| Setting | Value |
|---|---|
| Webhook URL | `github_webhook`'s domain, which does not exist yet — see step 6 |
| Webhook secret | Something long and random; it goes in `GITHUB_WEBHOOK_SECRET` |
| Setup URL | `<dashboard>/setup`, with "Redirect on update" enabled |

Generate a private key and download the PEM.

For local development, point the webhook at a [smee.io](https://smee.io)
channel and forward it to your machine, rather than deploying on every change.

## 4. Environment

Fill in the rest of `.env`. Full reference in
[Configuration](configuration.md#environment-variables); the ones that matter
now:

```bash
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
GITHUB_WEBHOOK_SECRET=the-secret-you-invented
GITHUB_APP_SLUG=your-app-slug

LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-opus-5

EMBEDDING_MODEL=all-minilm
EMBEDDING_DIM=384
```

The PEM can be one line with `\n` escapes; it is unescaped on load.
`EMBEDDING_API_KEY` stays empty: Appwrite provides embeddings itself.

```bash
make doctor   # confirms what is still blank
```

## 5. Deploy

```bash
make deploy
```

Runs the checks, vendors the shared package into each function, and pushes.
Fill in `projectId` in `appwrite.config.json` before the first push.

Then set each function's environment variables in the Appwrite console. The
per-function list is in [Deployment](deployment.md#deploying); `agent_step`
needs all of them, the others need a subset.

## 6. Close the loop

Now that the functions exist, `github_webhook` has a domain. Copy it into the
GitHub App's **Webhook URL** field.

Set `NPM_LOCKFILE_FUNCTION_ID` to the deployed Node function's id, and
`SCAN_REPO_FUNCTION_ID` / `AGENT_STEP_FUNCTION_ID` if your function ids differ
from the defaults (`scan_repo`, `agent_step`).

## 7. Dashboard

Add the public values to `.env`:

```bash
VITE_APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
VITE_APPWRITE_PROJECT_ID=your-project-id
VITE_API_FUNCTION_ID=api
VITE_GITHUB_APP_SLUG=your-app-slug
```

```bash
make build-ui   # → apps/dashboard/dist
```

These are inlined at build time, so a change means a rebuild. Host `dist/`
anywhere that serves `index.html` for unknown paths.

Enable the **GitHub OAuth provider** in Appwrite's Auth settings, which is
separate from the GitHub App and is what signs users in.

## 8. Test repository

The end-to-end flow needs a repository that is genuinely vulnerable in three
different ways. Create a public `vulnagent-test-app`:

- A small Express + TypeScript API
- A real Vitest suite that exercises the code being upgraded
- A workflow running `npm ci && npm test` on pull requests

Pinned to three deliberate problems:

| Problem | Example | Exercises |
|---|---|---|
| Direct, non-breaking patch | old `lodash` | `BumpDirect` |
| Transitive, fixable by a parent | `qs` via `express` | `BumpParent` |
| Major bump that **breaks a test** | `jsonwebtoken` 8 → 9 | The whole repair loop |

Verify the advisories and the breaking behavior against OSV and the changelog
before relying on them. The third one is the point of the exercise: if the
test suite does not actually fail on the upgrade, the repair loop never runs
and the end-to-end flow proves nothing.

Its `.vulnagent.yml`:

```yaml
version: 1
agent:
  allow_major_bumps: true
  severity_threshold: medium
  auto_merge: true
  max_ci_retries: 3
```

Tag the vulnerable state so it can be restored:

```bash
git tag vulnerable-baseline && git push --tags
```

Then reset between runs with:

```bash
make reset TEST_REPO=you/vulnagent-test-app
```

## 9. The first end-to-end run

1. Install the app on the test repository.
2. Confirm `installations` and `repos` rows appeared.
3. Sign in to the dashboard. The repository should be listed, possibly with no
   counts yet.
4. Press **Scan now**. Counts appear within a few seconds.
5. Press **Fix now** and watch the timeline.

What you are looking for, in order:

```
Run queued (manual)
Selected N vulnerabilities to fix
Planned N dependency changes
Pushed 2 files
Opened pull request #1
CI failed: TypeError: jwt.sign is not a function
Found a past fix for a similar failure (similarity 0.9x)   ← the memory hit
jsonwebtoken 9 removed the callable default export ...      ← the repair
CI passed
Pull request #1 merged
N vulnerabilities marked fixed
```

Counts drop to zero and the repository returns to Sleeping 😴.

If any step stalls, [Troubleshooting](troubleshooting.md) is organised by
symptom. The run that most often needs attention is the first one, because it
is the first time the webhook URL, the function ids and the Node helper are
all exercised together.
