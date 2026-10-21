"""Read fixed versions and affected ranges out of an OSV advisory (§10).

An OSV ``affected`` entry describes one package in one ecosystem. Its
``ranges`` carry ``introduced`` / ``fixed`` / ``last_affected`` events in
version order; only ``fixed`` tells us what to upgrade to, and only
version-typed ranges are usable (a GIT range's "fix" is a commit hash).
"""

from __future__ import annotations

from typing import Any, Final

import nodesemver

_VERSION_RANGE_TYPES: Final = frozenset({"SEMVER", "ECOSYSTEM"})


def affected_versions_fixed_in(
    advisory: dict[str, Any], package_name: str, ecosystem: str
) -> list[str]:
    """Every version that fixes ``package_name``, lowest first."""
    fixes: list[str] = []
    for entry in _entries_for(advisory, package_name, ecosystem):
        for range_ in _version_ranges(entry):
            for event in _events(range_):
                fixed = event.get("fixed")
                if isinstance(fixed, str) and _is_version(fixed) and fixed not in fixes:
                    fixes.append(fixed)
    return sort_versions(fixes)


def is_version_affected(
    advisory: dict[str, Any], package_name: str, ecosystem: str, version: str
) -> bool:
    if not _is_version(version):
        return False
    for entry in _entries_for(advisory, package_name, ecosystem):
        listed = entry.get("versions")
        if isinstance(listed, list) and version in listed:
            return True
        if any(_range_covers(range_, version) for range_ in _version_ranges(entry)):
            return True
    return False


def sort_versions(versions: list[str]) -> list[str]:
    usable = [version for version in versions if _is_version(version)]
    return list(nodesemver.sort(usable, loose=True))


def _entries_for(
    advisory: dict[str, Any], package_name: str, ecosystem: str
) -> list[dict[str, Any]]:
    affected = advisory.get("affected")
    if not isinstance(affected, list):
        return []
    return [
        entry
        for entry in affected
        if isinstance(entry, dict) and _matches(entry.get("package"), package_name, ecosystem)
    ]


def _matches(package: Any, package_name: str, ecosystem: str) -> bool:
    if not isinstance(package, dict):
        return False
    return (
        str(package.get("name", "")) == package_name
        and str(package.get("ecosystem", "")).casefold() == ecosystem.casefold()
    )


def _version_ranges(entry: dict[str, Any]) -> list[dict[str, Any]]:
    ranges = entry.get("ranges")
    if not isinstance(ranges, list):
        return []
    return [
        range_
        for range_ in ranges
        if isinstance(range_, dict) and str(range_.get("type", "")).upper() in _VERSION_RANGE_TYPES
    ]


def _events(range_: dict[str, Any]) -> list[dict[str, Any]]:
    events = range_.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def _range_covers(range_: dict[str, Any], version: str) -> bool:
    """Walk the range's events in order, tracking whether `version` is inside it."""
    inside = False
    for event in _events(range_):
        if "introduced" in event:
            introduced = str(event["introduced"])
            inside = introduced == "0" or _at_least(version, introduced)
        elif "fixed" in event and inside and _at_least(version, str(event["fixed"])):
            inside = False
        elif "last_affected" in event and inside:
            inside = not _greater_than(version, str(event["last_affected"]))
    return inside


def _at_least(version: str, other: str) -> bool:
    return _is_version(other) and nodesemver.gte(version, other, loose=True)


def _greater_than(version: str, other: str) -> bool:
    return _is_version(other) and nodesemver.gt(version, other, loose=True)


def _is_version(value: str) -> bool:
    return nodesemver.valid(value, loose=True) is not None
