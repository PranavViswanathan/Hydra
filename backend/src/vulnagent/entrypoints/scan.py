"""Async entry point: scan one repository (§10)."""

from __future__ import annotations

from typing import Any

from vulnagent.runtime import build_context
from vulnagent.scanning.scan import RepoScanner
from vulnagent.services.triggers import maybe_start_agent


def handle(context: Any) -> Any:
    payload = context.req.body_json or {}
    repo_id = str(payload.get("repo_id", ""))
    trigger = str(payload.get("trigger", "manual"))

    app = build_context()
    try:
        repo = app.db.repos.get(repo_id)
        if repo is None:
            return context.res.json({"error": f"no repository {repo_id}"}, 404)

        installation = app.db.installations.get(repo.installation_id)
        if installation is None:
            return context.res.json({"error": "the installation is gone"}, 409)

        app.db.repos.update(repo.id, {"agent_state": "scanning"})
        try:
            scanner = RepoScanner(
                db=app.db,
                github=app.github_for(installation.github_installation_id),
                osv=app.osv,
            )
            result = scanner.scan(repo, trigger=trigger)  # type: ignore[arg-type]
        finally:
            app.db.repos.update(repo.id, {"agent_state": "idle"})

        context.log(f"{repo.full_name}: {result.vulns_found} vulnerabilities")
        maybe_start_agent(app, repo, result)
        return context.res.json({"scan_id": result.scan_id, "vulns_found": result.vulns_found})
    finally:
        app.close()
