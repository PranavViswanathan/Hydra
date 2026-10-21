"""Read-only access to the npm registry, for planning parent bumps.

Planning asks the same questions repeatedly while walking candidate versions,
so each package document is fetched once and kept for the life of the client
(one agent step).
"""

from __future__ import annotations

from typing import Any, Final
from urllib.parse import quote

import httpx
import nodesemver

DEFAULT_BASE_URL: Final = "https://registry.npmjs.org"
DEFAULT_TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)


class NpmRegistryClient:
    def __init__(self, *, base_url: str = DEFAULT_BASE_URL, http: httpx.Client) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._documents: dict[str, dict[str, Any] | None] = {}

    def list_versions(self, name: str) -> list[str]:
        versions = self._versions_of(name)
        return [str(version) for version in nodesemver.sort(list(versions), loose=True)]

    def get_dependencies(self, name: str, version: str) -> dict[str, str]:
        release = self._versions_of(name).get(version)
        if not isinstance(release, dict):
            return {}
        dependencies = release.get("dependencies")
        if not isinstance(dependencies, dict):
            return {}
        return {str(key): str(value) for key, value in dependencies.items()}

    def _versions_of(self, name: str) -> dict[str, Any]:
        document = self._document(name)
        if document is None:
            return {}
        versions = document.get("versions")
        if not isinstance(versions, dict):
            return {}
        return {
            str(version): release
            for version, release in versions.items()
            if nodesemver.valid(str(version), loose=True) is not None
        }

    def _document(self, name: str) -> dict[str, Any] | None:
        if name in self._documents:
            return self._documents[name]

        response = self._http.get(
            f"{self._base_url}/{quote(name, safe='@')}", timeout=DEFAULT_TIMEOUT
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            self._documents[name] = None
            return None
        response.raise_for_status()

        body = response.json()
        document = body if isinstance(body, dict) else None
        self._documents[name] = document
        return document
