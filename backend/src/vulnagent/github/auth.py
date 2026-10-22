"""GitHub App authentication: app JWT, then per-installation access tokens.

Installation tokens last an hour; they are cached until shortly before expiry
so a run that makes many calls does not mint one per call.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any, Final

import httpx
import jwt

API_ROOT: Final = "https://api.github.com"
ACCEPT: Final = "application/vnd.github+json"
API_VERSION: Final = "2022-11-28"

# GitHub rejects an app JWT older than 10 minutes; 9 leaves room for clock skew.
_JWT_LIFETIME_SECONDS: Final = 9 * 60
_JWT_BACKDATE_SECONDS: Final = 60
_TOKEN_REFRESH_MARGIN: Final = dt.timedelta(minutes=5)

DEFAULT_TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)


@dataclass(frozen=True, slots=True)
class InstallationToken:
    token: str
    expires_at: dt.datetime

    def is_usable(self, *, now: dt.datetime) -> bool:
        return now + _TOKEN_REFRESH_MARGIN < self.expires_at


def app_jwt(*, app_id: int, private_key: str, now: float | None = None) -> str:
    """A short-lived JWT identifying the app itself."""
    issued_at = int(now if now is not None else time.time())
    return jwt.encode(
        {
            "iat": issued_at - _JWT_BACKDATE_SECONDS,
            "exp": issued_at + _JWT_LIFETIME_SECONDS,
            "iss": str(app_id),
        },
        private_key,
        algorithm="RS256",
    )


@dataclass
class GitHubAppAuth:
    app_id: int
    private_key: str
    http: httpx.Client
    api_root: str = API_ROOT
    _tokens: dict[int, InstallationToken] = field(default_factory=dict, repr=False)

    def token_for(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        now = dt.datetime.now(dt.UTC)
        if cached is not None and cached.is_usable(now=now):
            return cached.token

        minted = self._mint(installation_id)
        self._tokens[installation_id] = minted
        return minted.token

    def _app_jwt(self) -> str:
        return app_jwt(app_id=self.app_id, private_key=self.private_key)

    def _mint(self, installation_id: int) -> InstallationToken:
        response = self.http.post(
            f"{self.api_root}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self._app_jwt()}",
                "Accept": ACCEPT,
                "X-GitHub-Api-Version": API_VERSION,
            },
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return InstallationToken(
            token=str(body["token"]),
            expires_at=_parse_expiry(body.get("expires_at")),
        )


def _parse_expiry(value: Any) -> dt.datetime:
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
