"""The normalised advisory stored in the `advisories` table (§7.6)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

from vulnagent.core.models import Severity
from vulnagent.osv.severity import cvss_score_of, severity_of


class Advisory(BaseModel):
    osv_id: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    details: str = ""
    severity: Severity = "unknown"
    cvss_score: float | None = None
    affected: list[dict[str, Any]] = Field(default_factory=list)
    osv_modified: dt.datetime | None = None


def advisory_from_osv(raw: dict[str, Any]) -> Advisory:
    return Advisory(
        osv_id=str(raw["id"]),
        aliases=[str(alias) for alias in raw.get("aliases", []) if isinstance(alias, str)],
        summary=str(raw.get("summary", "")),
        details=str(raw.get("details", "")),
        severity=severity_of(raw),
        cvss_score=cvss_score_of(raw),
        affected=[entry for entry in raw.get("affected", []) if isinstance(entry, dict)],
        osv_modified=_timestamp(raw.get("modified")),
    )


def _timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
