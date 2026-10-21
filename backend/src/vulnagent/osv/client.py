"""Client for the free OSV API (https://api.osv.dev).

``querybatch`` answers "which advisories affect these exact versions" for up to
a thousand packages at a time and returns only ids; the full advisory comes
from ``/v1/vulns/{id}`` and is cached in the `advisories` table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx

from vulnagent.core.models import Purl
from vulnagent.core.purl import make_purl

BATCH_SIZE: Final = 1000
DEFAULT_TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)


@dataclass(frozen=True, slots=True)
class PackageQuery:
    name: str
    ecosystem: str
    version: str

    @property
    def purl(self) -> Purl:
        return make_purl(self.ecosystem.casefold(), self.name, self.version)

    def as_payload(self) -> dict[str, Any]:
        return {
            "package": {"name": self.name, "ecosystem": self.ecosystem},
            "version": self.version,
        }


class OsvClient:
    def __init__(self, *, base_url: str, http: httpx.Client) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

    def query_batch(self, queries: list[PackageQuery]) -> dict[Purl, list[str]]:
        """Map each queried package's purl to the advisory ids affecting it."""
        found: dict[Purl, list[str]] = {}
        for start in range(0, len(queries), BATCH_SIZE):
            chunk = queries[start : start + BATCH_SIZE]
            results = self._post_batch(chunk)
            for query, result in zip(chunk, results, strict=False):
                ids = _advisory_ids(result)
                if ids:
                    found[query.purl] = ids
        return found

    def get_vulnerability(self, osv_id: str) -> dict[str, Any] | None:
        """The full advisory, or None if OSV no longer serves it."""
        response = self._http.get(f"{self._base_url}/v1/vulns/{osv_id}", timeout=DEFAULT_TIMEOUT)
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else None

    def _post_batch(self, chunk: list[PackageQuery]) -> list[dict[str, Any]]:
        response = self._http.post(
            f"{self._base_url}/v1/querybatch",
            json={"queries": [query.as_payload() for query in chunk]},
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
        results = body.get("results") if isinstance(body, dict) else None
        return [result for result in results if isinstance(result, dict)] if results else []


def _advisory_ids(result: dict[str, Any]) -> list[str]:
    vulns = result.get("vulns")
    if not isinstance(vulns, list):
        return []
    return [
        str(vuln["id"])
        for vuln in vulns
        if isinstance(vuln, dict) and isinstance(vuln.get("id"), str)
    ]
