"""Work out what a scan changed, without touching the database.

A scan produces the set of vulnerabilities that exist right now. Reconciling
means deciding which rows are new, which are still there, and which have
disappeared because someone upgraded the package.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from vulnagent.core.models import Severity, VulnFinding, severity_rank
from vulnagent.db.rows import Vulnerability, VulnStatus

# A vulnerability the agent is working on must not be reopened mid-run, and a
# deliberately ignored one must not come back on the next scan.
_PRESERVED_STATUSES = frozenset({"ignored", "in_progress"})


@dataclass(frozen=True, slots=True)
class Reconciliation:
    created: list[Vulnerability] = field(default_factory=list)
    still_present: list[tuple[str, dict[str, object]]] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)

    @property
    def new_count(self) -> int:
        return len(self.created)


def reconcile(
    *,
    repo_id: str,
    existing: list[Vulnerability],
    found: list[VulnFinding],
    package_names: dict[str, str],
    installed_versions: dict[str, str],
    direct_purls: set[str],
    ignored: set[str],
    now: dt.datetime,
) -> Reconciliation:
    by_key = {(row.osv_id, row.purl): row for row in existing}
    seen: set[tuple[str, str]] = set()

    created: list[Vulnerability] = []
    still_present: list[tuple[str, dict[str, object]]] = []

    for finding in found:
        key = (finding.osv_id, finding.purl)
        seen.add(key)
        row = by_key.get(key)
        status: VulnStatus = "ignored" if finding.osv_id in ignored else "open"

        if row is None:
            created.append(
                Vulnerability(
                    repo_id=repo_id,
                    osv_id=finding.osv_id,
                    purl=finding.purl,
                    package_name=package_names.get(finding.purl, ""),
                    installed_version=installed_versions.get(finding.purl, ""),
                    fixed_version=finding.fixed_versions[0] if finding.fixed_versions else None,
                    severity=finding.severity,
                    status=status if finding.fixed_versions else "unfixable",
                    is_direct=finding.purl in direct_purls,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            continue

        changes: dict[str, object] = {"last_seen_at": now}
        if row.status not in _PRESERVED_STATUSES and row.status != status:
            changes["status"] = status
        if row.severity != finding.severity:
            changes["severity"] = finding.severity
        still_present.append((row.id, changes))

    resolved = [
        row.id
        for key, row in by_key.items()
        if key not in seen and row.status in {"open", "in_progress", "unfixable", "needs_major"}
    ]
    return Reconciliation(created=created, still_present=still_present, resolved=resolved)


def severity_counts(vulnerabilities: list[Vulnerability]) -> dict[Severity, int]:
    """Open counts per severity, for the dashboard badges."""
    counts: dict[Severity, int] = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "unknown": 0,
    }
    for row in vulnerabilities:
        if row.status in {"open", "in_progress"}:
            counts[row.severity] = counts.get(row.severity, 0) + 1
    return counts


def worst_severity(findings: list[VulnFinding]) -> Severity:
    if not findings:
        return "unknown"
    return max((finding.severity for finding in findings), key=severity_rank)
