# Safety rules

Nine rules from §11 of the specification. Each is enforced in code rather than
asked for in a prompt, and each has tests in
`backend/tests/test_safety.py`.

The repair prompt also states most of these in English. That is not redundancy
for its own sake: the prompt reduces how often a model tries something
forbidden, and the code decides what actually happens when it does.

## The rules

| # | Rule | Enforced in | Effect when violated |
|---|---|---|---|
| 1 | Never push to the default branch | `github/client.py` | The call raises before any request is sent |
| 2 | The model may not edit CI config, the agent's config, manifests or lockfiles | `core/safety.py:review_edits` | The run gives up |
| 3 | The model may not delete or weaken tests | `core/safety.py:review_edits` | The run gives up |
| 4 | At most 200 changed lines and 10 files per repair | `core/safety.py:review_edits` | The run gives up |
| 5 | Never execute target-repo code; `npm install --ignore-scripts` | `functions-node/npm_lockfile` | Scripts never run |
| 6 | No tokens or secrets reach the model | `core/safety.py:redact_secrets` | Replaced with `[redacted]` |
| 7 | Retry cap from config, hard ceiling 5 | `core/safety.py:capped_retries` | Clamped silently |
| 8 | Major bumps only with `allow_major_bumps` | `adapters/npm/planner.py` | Reported `needs_major` |
| 9 | Verify `X-Hub-Signature-256` before processing | `core/safety.py:verify_webhook_signature` | 401, nothing is read |

## 1. Only the agent's own branches

```python
def is_agent_branch(branch: str) -> bool
```

A branch qualifies only when it starts with `vulnagent/`, has something after
the prefix, and contains no `..`. The last check stops `vulnagent/../main` from
walking out of the namespace.

The check lives **inside** `GitHubClient`, not in the calling step:
`create_branch`, `commit_files` and `open_pull_request` all refuse before
issuing a request. Putting it at the boundary means no future caller can forget
it.

```python
client.commit_files(repo, branch="main", ...)
# VulnAgentError: refusing to write to 'main': not a branch the agent created
```

## 2. Files the model may not touch

| Protected | Why |
|---|---|
| `.github/**` | Editing CI to make CI pass is the oldest trick there is |
| `.vulnagent.yml` / `.yaml` / `.json` | The model does not get to raise its own retry budget |
| Any `adapter.is_manifest_path(path)` | Versions are planned deterministically, not negotiated |
| Anything outside the repository | `../`, absolute paths, `~` |

The manifest check goes through the adapter rather than a hard-coded list, so
a new ecosystem's manifests are protected the moment the adapter declares them.

The path check rejects `/etc/passwd`, `../outside.ts` and `src/../../escape.ts`
alike, by looking for `..` in the parsed path components rather than by string
matching.

## 3. Tests may not be weakened

Two separate checks.

**Added markers.** A replacement that introduces any of these, when the search
text did not already contain it, is refused:

```
it.skip   test.only   describe.skip   it.todo   it.failing
xit   xtest   xdescribe   fit   fdescribe
@ts-ignore   @ts-expect-error   @ts-nocheck
eslint-disable   istanbul ignore
```

The "when the search text did not already contain it" part matters: an edit
that moves an existing `@ts-ignore` around is fine, and only *introducing* one
is refused.

**Removed declarations.** The number of `it(`, `test(`, `describe(` and
`context(` occurrences is counted in both the search and the replacement. If
the replacement has fewer, the edit is deleting a test and is refused.

This allows the thing you want:

```diff
- it('signs a token', () => { sign(payload) })
+ it('signs a token', async () => { await sign(payload) })
```

and refuses the thing you do not:

```diff
- it('rejects an expired token', () => { expect(verify(expired)).toThrow() })
+
```

## 4. Diff caps

200 changed lines and 10 files, counted **across the whole attempt** rather
than per edit, because ten edits of 30 lines each is still a 300-line change.

A file edited several times counts once toward the file cap. Lines are counted
in both the search and the replacement, so a large deletion is as expensive as
a large addition.

A dependency upgrade that needs more than 200 lines of application changes is
not something an agent should be landing unattended.

## 5. Target code never runs

VulnAgent never executes anything from a target repository. The nearest it
comes is resolving a lockfile, and that happens in one place:

```js
const NPM_ARGS = [
  'install',
  '--package-lock-only',   // resolve only, download nothing into node_modules
  '--ignore-scripts',      // never run preinstall/postinstall/prepare
  '--no-audit',
  '--no-fund',
]
```

`--ignore-scripts` is the load-bearing flag. Without it, `npm install` on an
untrusted `package.json` runs that project's lifecycle scripts inside the
function, with the function's environment.

Whether an upgrade actually works is answered by the repository's own CI, in
the repository's own sandbox, which is where that question belongs.

## 6. Secrets never reach the model

`redact_secrets` runs over CI logs and over the assembled prompt, since a
source file can contain a hard-coded credential.

| Pattern | Matches |
|---|---|
| `gh[pousr]_[A-Za-z0-9]{16,}` | GitHub personal, OAuth, user, server and refresh tokens |
| `github_pat_[A-Za-z0-9_]{20,}` | Fine-grained PATs |
| `sk-[A-Za-z0-9-]{12,}` | Anthropic and OpenAI style keys |
| `AKIA[0-9A-Z]{16}` | AWS access key ids |
| `ey…\.…\.…` | JWTs |
| `-----BEGIN … PRIVATE KEY-----` | PEM blocks |
| `*_TOKEN=`, `*_SECRET=`, `*_PASSWORD=`, `*API_KEY=`, `*CREDENTIAL=` | Environment assignments with a value |

Each match becomes `[redacted]`. Ordinary log output passes through untouched,
which the tests check explicitly: a redactor that mangles stack traces makes
the repair step worse.

## 7. The retry ceiling

```python
capped_retries(configured) == max(0, min(configured, 5))
```

A repository asking for 99 retries gets 5. A repository asking for -1 gets 0.
Applied when the run is created and again when the prompt is built, so a
config edited mid-run cannot extend a budget that is already spent.

## 8. Major bumps are opt-in

Covered in [Upgrade planning](upgrade-planning.md#major-bumps). The rule also
applies to parent bumps: the agent will not cross a major on `express` to fix
`qs` unless the repository allowed it, and falls back to an override instead.

`0.x` minors count as major, because npm treats them that way.

## 9. Webhook signatures

```python
def verify_webhook_signature(body: bytes, header: str | None, secret: bytes) -> bool
```

HMAC-SHA256 over the raw body, compared with `hmac.compare_digest`. A missing
header, an algorithm other than `sha256=`, a malformed header, a tampered body
or the wrong secret all return `False`, and the function returns 401 before
reading the payload.

The comparison is constant-time. A naive `==` on a signature leaks timing
information that can be used to forge one.

## What is not covered

These are real risks the rules do not address, listed so they are not mistaken
for solved:

- **A malicious advisory.** OSV is trusted. A poisoned advisory could direct an
  upgrade to a malicious version.
- **A malicious package version.** The agent upgrades to the fix OSV names; it
  does not audit that version's contents.
- **A compromised model response within the rules.** An edit that is small,
  touches only application code and removes no tests can still be wrong. CI is
  the check, which is why `auto_merge` is off by default.
- **Permissions beyond ownership.** Anyone who can see a repository in the
  dashboard can press *Fix now* on it. There is no per-user role model.
