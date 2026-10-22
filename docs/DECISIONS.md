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

### `apply_upgrades` takes the lockfile regenerator as an argument

§6.2 writes `apply_upgrades(self, plan, files)`, with the adapter reaching a
`LockfileRegenerator` on its own. Passing it in keeps adapters stateless and
makes the dependency visible at the only call site that has it (the PATCHING
step, which holds the Appwrite client). Same protocol otherwise.

### Parent bumps are judged by the lowest version a range permits

A parent version counts as a fix only when every version its dependency range
permits is at or above the fixed version, not merely when the range allows one.
Bumping express to a version whose range still permits the vulnerable qs is not
a fix, even though npm would probably install a patched copy today. Testing the
lowest permitted version is what makes that distinction, so planning asks the
registry for the full version list and uses `min_satisfying`.

### Chain search for parent bumps stops at depth 2

Verifying that a candidate parent pulls in a fixed copy costs registry calls per
level. In practice the vulnerable package is a direct dependency of the parent
being bumped, so the search goes one level deeper than that and then falls back
to an override.

### `conflict` means an override would contradict the manifest

npm's `overrides` can pin almost anything, so the planner's fallback nearly
always succeeds and `conflict` would otherwise be unreachable. It is reported
for the one case that is genuinely contradictory: the manifest declares its own
range for the package and the override target falls outside it.

### Embeddings come from Appwrite, not a third-party API

§3 left this open ("check whether VectorsDB offers built-in embeddings; else a
hosted embedding API"). The installed server SDK ships an `embeddings` service
with `create_text_embeddings(texts, model)` and two models: `all-minilm` (384
dimensions) and `nomic-embed-text` (768). So no third-party embedding key is
needed, and `EMBEDDING_API_KEY` stays unused. `EMBEDDING_MODEL` must be one of
those two names and `EMBEDDING_DIM` must match, because the dimension fixes the
width of the VectorsDB column at creation time. Defaulting to `all-minilm`:
smaller vectors, and error signatures are short text where the larger model
buys little.

### Vector search applies its similarity threshold client-side

The SDK has `Query.vector_cosine(attribute, vector)` for ranking, but its
`distance_less_than` is a geospatial query in meters, not a vector-distance
filter. So the query asks for the top k ranked rows and the 0.80 threshold is
applied to what comes back. Rows carry their score under one of several keys
depending on the server; when none is present the similarity is recomputed
locally from the stored embedding.

### The TablesDB memory fallback uses pure Python, not numpy

§8 suggests numpy for brute-force cosine. At the scale this runs at (hundreds
of rows for one ecosystem) a plain comprehension is fast enough, and it keeps a
large wheel out of every vendored function bundle.

### GitHub access is a thin httpx client, not `githubkit`

`githubkit` was the spec's primary choice and the earlier entry above recorded
it. Replaced with a small httpx client plus `pyjwt[crypto]` for the app JWT.
Two reasons: every Appwrite function vendors its dependencies, and githubkit
carries generated pydantic models for the whole GitHub API, which is a large
bundle for the dozen endpoints this uses; and the hand-written client keeps
`mypy --strict` clean without casts around generated overloads. The endpoints
used are the ones named in §4.3 and §9.3.

### Safety rule 1 is enforced inside the GitHub client

`create_branch`, `commit_files` and `open_pull_request` refuse any branch
outside `vulnagent/*`. Putting the check at the boundary rather than in the
calling step means no future caller can forget it.

## Pending (blocked on credentials)

- **Spike A (VectorsDB)**, **Spike B (`npm_lockfile` Node function)** and
  **Spike C (vendored Python function deploy)** need a live Appwrite project and
  the Appwrite CLI, neither of which is set up in this environment. Outcomes get
  recorded here once they run.
