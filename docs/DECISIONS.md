# Decision log

Every non-trivial deviation from `PROJECT.md`, with date and reason.

## 2026-10-21

### Repository is standalone; the Python package keeps the name `vulnagent`

The working directory is `Hydra/`, which previously sat inside the catch-all
`Programming` git repo. Initialized `Hydra/` as its own repo, matching how
Jobinator was split out. The spec is written end to end around the name
`vulnagent` (package, config file `.vulnagent.yml`, branch prefix
`vulnagent/*`, bot name `vulnagent[bot]`), so the code keeps that name and
`Hydra` is only the repo/directory name. Renaming the product to Hydra later is
a mechanical find-and-replace plus a GitHub App rename.

### `unknown` severity ranks alongside `low`

OSV entries without severity data are common. Ranking `unknown` below `low`
would hide them from every threshold, including `severity_threshold: low`;
ranking it higher would let unscored advisories trigger the agent on repos that
asked for `high` only. Ranking it equal to `low` means an unscored advisory is
picked up only when the user asked for everything.

### `UpgradeAction` discriminator lives in `Annotated`, not in a field default

`PROJECT.md` §6.1 writes `actions: list[UpgradeAction] = Field(discriminator="kind")`.
In pydantic v2 the discriminator must annotate the union itself, otherwise it is
ignored and the field has no default. Implemented as
`type UpgradeAction = Annotated[BumpDirect | BumpParent | Override, Field(discriminator="kind")]`
with `actions: list[UpgradeAction] = Field(default_factory=list)`. Behavior is
what the spec intended: round-tripping a plan through JSON preserves action types.

### GitHub client: `githubkit`

Taking the spec's primary choice rather than the `PyGithub` + `PyJWT` fallback.
It ships App (JWT -> installation token) auth and fully typed REST models, which
suits `mypy --strict`. Revisit only if the Appwrite Python runtime cannot
install it.

### PEP 695 `type` aliases

Ruff's `UP040` flags `X: TypeAlias = ...` on Python 3.12. Using the `type`
keyword instead; verified pydantic v2 resolves the discriminated union through
the lazy alias (`tests/test_models.py`).

### Repo config rejects unknown keys

`extra="forbid"` on every config model. A typo like `enabeld: false` would
otherwise silently keep the agent enabled, which is worse than showing the user
a `config_error` on the dashboard. `paths` beyond `["."]` is rejected for the
same reason: §2.3 makes it a non-goal for the MVP, so accepting the value and
ignoring it would mislead.

### Settings do not read `.env` unless a caller asks

Deployed functions get their variables from Appwrite, so `load_settings()`
reads only the process environment; local scripts opt in with
`load_settings(dotenv=".env")`. Reading `.env` by default would have made the
test suite depend on whether the developer happened to have one on disk.

### Only Appwrite and GitHub credentials are required to boot

`LLM_*`, `EMBEDDING_*` and `NPM_LOCKFILE_FUNCTION_ID` are optional on
`Settings`, so a scan-only deployment starts without them. The code that needs
them calls `require_llm()` / `require_embeddings()` /
`require_npm_lockfile_function_id()` and fails with the missing variable's
name instead of a `None` surfacing somewhere deep in a request.

## Pending (blocked on credentials)

- **Spike A (VectorsDB)**, **Spike B (`npm_lockfile` Node function)** and
  **Spike C (vendored Python function deploy)** need a live Appwrite project and
  the Appwrite CLI, neither of which is set up in this environment. Outcomes get
  recorded here once they run.
