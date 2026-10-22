"""Keep `installations` and `repos` in step with GitHub (§10)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

from croniter import croniter

from vulnagent.config.schema import CONFIG_FILENAMES, parse_repo_config
from vulnagent.core.errors import ConfigError
from vulnagent.db.repositories import Database
from vulnagent.db.rows import Installation, Repo
from vulnagent.github.client import Repository
from vulnagent.github.webhooks import InstallationChange, PushToDefaultBranch


class HasDb(Protocol):
    db: Database

    def github_for(self, installation_id: int) -> Any: ...


def apply_installation_change(app: HasDb, change: InstallationChange) -> list[Repo]:
    """Upsert the installation and the repositories it covers, reading each config."""
    if change.removed:
        _forget(app, change.installation_id)
        return []

    installation = app.db.installations.by_github_id(change.installation_id)
    if installation is None:
        installation = app.db.installations.create(
            Installation(
                github_installation_id=change.installation_id,
                account_login=change.account_login,
                account_type=change.account_type,  # type: ignore[arg-type]
                suspended=change.suspended,
            )
        )
    else:
        app.db.installations.update(installation.id, {"suspended": change.suspended})

    github = app.github_for(change.installation_id)
    saved: list[Repo] = []
    for entry in change.repositories:
        saved.append(_upsert_repo(app, github, installation.id, entry))
    return saved


def reload_config(app: HasDb, push: PushToDefaultBranch) -> bool:
    """Re-read `.vulnagent.yml` when a push touched it."""
    if not any(path in CONFIG_FILENAMES for path in push.changed_paths):
        return False

    repo = app.db.repos.by_full_name(push.repo_full_name)
    if repo is None:
        return False

    github = app.github_for(push.installation_id)
    app.db.repos.update(repo.id, _config_fields(github, repo.full_name, repo.default_branch))
    return True


def _upsert_repo(app: HasDb, github: Any, installation_id: str, entry: dict[str, Any]) -> Repo:
    full_name = str(entry.get("full_name", ""))
    github_repo_id = int(entry.get("id", 0))
    default_branch = str(entry.get("default_branch") or "main")

    fields = {
        "installation_id": installation_id,
        "full_name": full_name,
        "default_branch": default_branch,
        **_config_fields(github, full_name, default_branch),
    }

    existing = app.db.repos.by_github_id(github_repo_id)
    if existing is not None:
        app.db.repos.update(existing.id, fields)
        return app.db.repos.get(existing.id) or existing

    return app.db.repos.create(Repo(github_repo_id=github_repo_id, **fields))


def _config_fields(github: Any, full_name: str, default_branch: str) -> dict[str, Any]:
    """Read the repo's config, recording the error rather than raising on bad input."""
    target = Repository.from_full_name(full_name)
    for filename in CONFIG_FILENAMES:
        contents = github.get_file(target, filename, default_branch)
        if contents is None:
            continue
        try:
            config = parse_repo_config(contents, path=filename)
        except ConfigError as error:
            return {"has_config": True, "config_json": contents, "config_error": str(error)}
        return {
            "has_config": True,
            "config_json": contents,
            "config_error": None,
            "next_scan_at": _first_scan(config.scan.schedule),
        }
    return {"has_config": False, "config_json": "", "config_error": None, "next_scan_at": None}


def _first_scan(schedule: str | None) -> dt.datetime | None:
    if not schedule:
        return None
    now = dt.datetime.now(dt.UTC)
    following: dt.datetime = croniter(schedule, now).get_next(dt.datetime)
    return following


def _forget(app: HasDb, github_installation_id: int) -> None:
    installation = app.db.installations.by_github_id(github_installation_id)
    if installation is None:
        return
    for repo in app.db.repos.find([]):
        if repo.installation_id == installation.id:
            app.db.repos.delete(repo.id)
    app.db.installations.delete(installation.id)
