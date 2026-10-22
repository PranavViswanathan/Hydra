"""Link a GitHub App installation to the signed-in dashboard user (§10).

The claim is verified against GitHub with the user's own token: whoever is
signed in must actually be able to see the installation before its repositories
become theirs.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from vulnagent.db.repositories import Database
from vulnagent.github.auth import ACCEPT, API_ROOT, API_VERSION, DEFAULT_TIMEOUT


class HasDb(Protocol):
    db: Database
    http: httpx.Client


def link_installation(app: HasDb, *, user_id: str, installation_id: int, user_token: str) -> bool:
    if not user_id or not installation_id or not user_token:
        return False
    if not user_can_see_installation(app.http, token=user_token, installation_id=installation_id):
        return False

    installation = app.db.installations.by_github_id(installation_id)
    if installation is None:
        return False

    app.db.installations.update(installation.id, {"owner_user_id": user_id})
    for repo in app.db.repos.find([]):
        if repo.installation_id == installation.id:
            app.db.repos.update(repo.id, {"owner_user_id": user_id})
    return True


def user_can_see_installation(http: httpx.Client, *, token: str, installation_id: int) -> bool:
    """`GET /user/installations` lists only what this user may access."""
    response = http.get(
        f"{API_ROOT}/user/installations",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": ACCEPT,
            "X-GitHub-Api-Version": API_VERSION,
        },
        params={"per_page": "100"},
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code != httpx.codes.OK:
        return False

    body = response.json()
    installations = body.get("installations") if isinstance(body, dict) else None
    if not isinstance(installations, list):
        return False
    return any(
        isinstance(entry, dict) and int(entry.get("id", 0)) == installation_id
        for entry in installations
    )
