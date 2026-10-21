"""Derive a severity band from an OSV advisory (§10).

Order of preference: the publisher's own rating in ``database_specific``, then
the highest-version CVSS vector it ships, then ``unknown``. A malformed vector
is never fatal: an advisory we cannot score still has to reach the dashboard.
"""

from __future__ import annotations

from typing import Any, Final

from cvss import CVSS2, CVSS3, CVSS4
from cvss.exceptions import CVSSError

from vulnagent.core.models import Severity

_PUBLISHED_RATINGS: Final[dict[str, Severity]] = {
    "LOW": "low",
    "MODERATE": "medium",
    "MEDIUM": "medium",
    "HIGH": "high",
    "CRITICAL": "critical",
}

# CVSS v3/v4 qualitative bands.
_BANDS: Final[tuple[tuple[float, Severity], ...]] = (
    (9.0, "critical"),
    (7.0, "high"),
    (4.0, "medium"),
    (0.1, "low"),
)

_PARSERS: Final[dict[str, type[CVSS2] | type[CVSS3] | type[CVSS4]]] = {
    "CVSS_V2": CVSS2,
    "CVSS_V3": CVSS3,
    "CVSS_V4": CVSS4,
}

# Highest wins when an advisory publishes several vectors.
_PRECEDENCE: Final[dict[str, int]] = {"CVSS_V2": 2, "CVSS_V3": 3, "CVSS_V4": 4}


def severity_of(advisory: dict[str, Any]) -> Severity:
    published = _published_rating(advisory)
    if published is not None:
        return published
    score = cvss_score_of(advisory)
    return _band(score) if score is not None else "unknown"


def cvss_score_of(advisory: dict[str, Any]) -> float | None:
    """The base score of the highest-version CVSS vector, if there is one."""
    entries = advisory.get("severity")
    if not isinstance(entries, list):
        return None

    best: tuple[int, float] | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type", ""))
        parser = _PARSERS.get(kind)
        vector = entry.get("score")
        if parser is None or not isinstance(vector, str):
            continue
        try:
            score = float(parser(vector).scores()[0])
        except (CVSSError, ValueError, IndexError, TypeError):
            continue
        rank = _PRECEDENCE.get(kind, 0)
        if best is None or rank > best[0]:
            best = (rank, score)
    return best[1] if best is not None else None


def _published_rating(advisory: dict[str, Any]) -> Severity | None:
    specific = advisory.get("database_specific")
    if not isinstance(specific, dict):
        return None
    rating = specific.get("severity")
    if not isinstance(rating, str):
        return None
    return _PUBLISHED_RATINGS.get(rating.upper())


def _band(score: float) -> Severity:
    for threshold, severity in _BANDS:
        if score >= threshold:
            return severity
    return "unknown"  # a 0.0 base score tells us nothing useful
