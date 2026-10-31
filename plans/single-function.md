# One Python function instead of six

Appwrite's free plan allows two functions. Hydra had seven: six Python entry
points and the Node lockfile helper. This merges the six into one, `hydra`,
and keeps `npm_lockfile` separate because it needs the Node runtime.

## Routing

| Call | Recognised by | Handler |
|---|---|---|
| Cron | `x-appwrite-trigger: schedule` | scheduler |
| Database event | `x-appwrite-trigger: event` | vulnerability created |
| Internal task | path `/tasks/scan` or `/tasks/agent-step` | scan, agent step |
| GitHub | `x-github-event` header | webhook |
| Everything else | | dashboard API |

## Internal tasks are signed

`hydra` must be executable by anyone so GitHub can reach it, which would let
anyone start a scan or advance a run. Each task body carries an HMAC-SHA256
signature keyed with `APPWRITE_API_KEY`; the router refuses a task path without
a valid one. No new secret is needed: only holders of the server key can sign.

## Steps

1. Task signing in `core/safety.py`, next to webhook verification.
2. A pure `destination()` that picks the handler from trigger, path and headers.
3. `TaskQueue` that enqueues a task as a signed async execution of `hydra`
   itself; `Context.enqueue` and `services/triggers.py` take a task name
   instead of a function id.
4. Move the six handlers into `vulnagent/entrypoints/` unchanged, plus the
   router's `main`. One folder, `backend/functions/hydra`.
5. Pin the function's requirements to `uv.lock`, with a test that they match.
6. Fix `api` reading `account.get()` as a dict (SDK models again).
7. `appwrite.config.json`, `.env.example` and the docs.

## Deploy consequences

- The GitHub App's webhook URL becomes `hydra`'s domain.
- `VITE_API_FUNCTION_ID` becomes `hydra`.
- `SCAN_REPO_FUNCTION_ID` and `AGENT_STEP_FUNCTION_ID` go away.
- The two functions already created (`agent_step`, `github_webhook`) must be
  deleted to free the slots.
