"""HTTP entry point for the dashboard, authenticated with the user's JWT (§10)."""

from __future__ import annotations

from typing import Any

from appwrite.client import Client
from appwrite.services.account import Account

from vulnagent.db.responses import plain
from vulnagent.runtime import build_context
from vulnagent.services.linking import link_installation
from vulnagent.services.triggers import start_agent_run


def handle(context: Any) -> Any:
    app = build_context()
    try:
        user_id = _user_id(app, context)
        if user_id is None:
            return context.res.json({"error": "not signed in"}, 401)

        path = context.req.path.rstrip("/")
        payload = context.req.body_json or {}

        if path == "/link-installation":
            linked = link_installation(
                app,
                user_id=user_id,
                installation_id=int(payload.get("installation_id", 0)),
                user_token=str(payload.get("github_token", "")),
            )
            return context.res.json({"linked": linked})

        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "repos":
            repo = app.db.repos.get(parts[1])
            if repo is None or repo.owner_user_id != user_id:
                return context.res.json({"error": "not found"}, 404)

            if parts[2] == "scan":
                app.enqueue("scan", {"repo_id": repo.id, "trigger": "manual"})
                return context.res.json({"status": "scanning"})

            if parts[2] == "fix":
                if repo.active_run_id:
                    return context.res.json(
                        {"status": "already working", "run_id": repo.active_run_id}
                    )
                run = start_agent_run(app, repo, trigger="manual")
                return context.res.json({"run_id": run.id})

        return context.res.json({"error": "unknown route"}, 404)
    finally:
        app.close()


def _user_id(app: Any, context: Any) -> str | None:
    """Resolve the caller from the JWT the dashboard sent."""
    jwt = context.req.headers.get("x-appwrite-user-jwt") or context.req.headers.get(
        "x-appwrite-jwt"
    )
    if not jwt:
        return None
    try:
        account = Account(
            Client()
            .set_endpoint(app.settings.appwrite_endpoint)
            .set_project(app.settings.appwrite_project_id)
            .set_jwt(jwt)
        )
        user = plain(account.get())
    except Exception:
        return None
    user_id = user.get("$id") if isinstance(user, dict) else None
    return str(user_id) if user_id else None
