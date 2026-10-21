"""Work out the smallest set of manifest changes that clears a set of findings (§6.4).

Per finding: take the lowest published fix above what is installed, refuse it
if it crosses a major and the repo has not opted in, then either bump the
direct dependency, bump the parent that pulls the vulnerable copy in, or pin
the package through `overrides`.
"""

from __future__ import annotations

from typing import Final

import nodesemver

from vulnagent.core.adapter import RegistryClient
from vulnagent.core.models import (
    ROOT,
    BumpDirect,
    BumpParent,
    DepGraph,
    DepNode,
    Override,
    Purl,
    Unresolved,
    UnresolvedReason,
    UpgradeAction,
    UpgradePlan,
    VulnFinding,
)

MANIFEST_PATH: Final = "package.json"

# How far below a candidate parent version we will look for the vulnerable
# package. Each level costs registry calls, and in practice the vulnerable
# package is a direct dependency of the parent being bumped.
_MAX_CHAIN_DEPTH: Final = 2


def plan_upgrades(
    findings: list[VulnFinding],
    graph: DepGraph,
    *,
    allow_major_bumps: bool,
    registry: RegistryClient,
) -> UpgradePlan:
    builder = _PlanBuilder(graph, allow_major_bumps=allow_major_bumps, registry=registry)
    for found in findings:
        builder.consider(found)
    return builder.build()


class _PlanBuilder:
    def __init__(
        self, graph: DepGraph, *, allow_major_bumps: bool, registry: RegistryClient
    ) -> None:
        self._graph = graph
        self._allow_major_bumps = allow_major_bumps
        self._registry = registry
        self._actions: dict[str, UpgradeAction] = {}  # package name -> action
        self._resolved: dict[str, list[str]] = {}  # package name -> advisory ids
        self._unresolved: list[tuple[str, UnresolvedReason]] = []
        self._major_bumps: list[str] = []

    def consider(self, found: VulnFinding) -> None:
        node = self._graph.nodes.get(found.purl)
        if node is None:
            return  # the advisory is for a version this repo does not install

        target = _lowest_fix_above(found.fixed_versions, node.version)
        if target is None:
            self._unresolved.append((found.osv_id, "no_fix"))
            return

        if node.is_direct:
            self._plan_direct(found, node, target)
        else:
            self._plan_transitive(found, node, target)

    def build(self) -> UpgradePlan:
        resolves = [osv_id for ids in self._resolved.values() for osv_id in ids]
        return UpgradePlan(
            ecosystem="npm",
            actions=list(self._actions.values()),
            resolves=resolves,
            unresolved=[
                Unresolved(osv_id=osv_id, reason=reason) for osv_id, reason in self._unresolved
            ],
            major_bumps=self._major_bumps,
        )

    def _plan_direct(self, found: VulnFinding, node: DepNode, target: str) -> None:
        if _crosses_major(node.version, target):
            if not self._allow_major_bumps:
                self._unresolved.append((found.osv_id, "needs_major"))
                return
            if node.name not in self._major_bumps:
                self._major_bumps.append(node.name)

        self._record(
            found,
            node.name,
            target,
            BumpDirect(
                name=node.name,
                from_version=node.version,
                to_version=target,
                manifest_path=MANIFEST_PATH,
            ),
        )

    def _plan_transitive(self, found: VulnFinding, node: DepNode, target: str) -> None:
        for parent in self._direct_ancestors_of(node.purl):
            bumped = self._lowest_parent_version_admitting(parent, node.name, target)
            if bumped is not None:
                self._record(
                    found,
                    parent.name,
                    bumped,
                    BumpParent(
                        parent_name=parent.name,
                        from_version=parent.version,
                        to_version=bumped,
                        reason=found.purl,
                        manifest_path=MANIFEST_PATH,
                    ),
                )
                return

        if self._contradicts_manifest(node.name, target):
            self._unresolved.append((found.osv_id, "conflict"))
            return

        self._record(
            found,
            node.name,
            target,
            Override(
                name=node.name,
                to_version=target,
                reason=found.purl,
                manifest_path=MANIFEST_PATH,
            ),
        )

    def _record(self, found: VulnFinding, package: str, target: str, action: UpgradeAction) -> None:
        """Keep the highest target per package; several advisories can share one action."""
        existing = self._actions.get(package)
        if existing is None or nodesemver.gt(target, existing.to_version, loose=True):
            self._actions[package] = action
        self._resolved.setdefault(package, []).append(found.osv_id)

    def _direct_ancestors_of(self, purl: Purl) -> list[DepNode]:
        """The direct dependencies through which `purl` ends up installed."""
        parents = {edge.parent for edge in self._graph.edges if edge.child == purl}
        ancestors = [
            node
            for parent in parents
            if parent != ROOT and (node := self._graph.nodes.get(parent)) is not None
        ]
        return [node for node in ancestors if node.is_direct]

    def _lowest_parent_version_admitting(
        self, parent: DepNode, package: str, target: str
    ) -> str | None:
        candidates = [
            version
            for version in nodesemver.sort(
                [v for v in self._registry.list_versions(parent.name) if nodesemver.valid(v, True)],
                loose=True,
            )
            if nodesemver.gt(version, parent.version, loose=True)
            and (self._allow_major_bumps or not _crosses_major(parent.version, version))
        ]
        for candidate in candidates:
            if self._admits(parent.name, candidate, package, target, _MAX_CHAIN_DEPTH):
                if (
                    _crosses_major(parent.version, candidate)
                    and parent.name not in self._major_bumps
                ):
                    self._major_bumps.append(parent.name)
                return str(candidate)
        return None

    def _admits(self, name: str, version: str, package: str, target: str, depth: int) -> bool:
        """Would `name@version` pull in a copy of `package` at or above `target`?"""
        requirements = self._registry.get_dependencies(name, version)
        requested = requirements.get(package)
        if requested is not None and self._only_resolves_at_or_above(package, requested, target):
            return True
        if depth <= 1:
            return False
        for dependency, dependency_range in requirements.items():
            resolved = self._resolve_range(dependency, dependency_range)
            if resolved is not None and self._admits(
                dependency, resolved, package, target, depth - 1
            ):
                return True
        return False

    def _only_resolves_at_or_above(self, package: str, requested: str, target: str) -> bool:
        """True when no version `requested` permits is still vulnerable.

        The lowest permitted version is the conservative one to test: npm
        installs the highest, but a fresh resolve elsewhere could pick any of
        them, and a parent that merely *allows* a fixed version is not a fix.
        """
        available = [v for v in self._registry.list_versions(package) if nodesemver.valid(v, True)]
        if available:
            try:
                lowest = nodesemver.min_satisfying(available, requested, loose=True)
            except ValueError:
                return False
            return lowest is not None and bool(nodesemver.gte(str(lowest), target, loose=True))
        if nodesemver.valid(requested.strip(), loose=True) is not None:
            return bool(nodesemver.gte(requested.strip(), target, loose=True))  # an exact pin
        return False

    def _resolve_range(self, name: str, requested: str) -> str | None:
        available = [v for v in self._registry.list_versions(name) if nodesemver.valid(v, True)]
        if not available:
            return None
        try:
            best = nodesemver.max_satisfying(available, requested, loose=True)
        except ValueError:
            return None
        return str(best) if best is not None else None

    def _contradicts_manifest(self, package: str, target: str) -> bool:
        """An override cannot stand against a range the manifest itself declares."""
        for edge in self._graph.edges:
            if edge.parent != ROOT:
                continue
            node = self._graph.nodes.get(edge.child)
            if node is not None and node.name == package:
                return not _range_admits(edge.requested_range, target)
        return False


def manifest_range_for(declared: str, version: str) -> str:
    """Rewrite a declared range to point at `version`, keeping its operator."""
    stripped = declared.strip()
    for operator in ("^", "~"):
        if stripped.startswith(operator):
            return f"{operator}{version}"
    if stripped.startswith("="):
        return version
    if nodesemver.valid(stripped, loose=True) is not None:
        return version
    return f"^{version}"  # a range we cannot mirror; caret is npm's own default


def _lowest_fix_above(fixed_versions: list[str], installed: str) -> str | None:
    usable = [
        version
        for version in fixed_versions
        if nodesemver.valid(version, loose=True) is not None
        and nodesemver.gt(version, installed, loose=True)
    ]
    if not usable:
        return None
    return str(nodesemver.sort(usable, loose=True)[0])


def _crosses_major(current: str, target: str) -> bool:
    """npm treats 0.x as unstable, so a 0.x minor bump is breaking too."""
    before = nodesemver.parse(current, loose=True)
    after = nodesemver.parse(target, loose=True)
    if before is None or after is None:
        return True
    if before.major != after.major:
        return True
    return bool(before.major == 0 and before.minor != after.minor)


def _range_admits(requested: str, version: str) -> bool:
    try:
        return bool(nodesemver.satisfies(version, requested, loose=True))
    except ValueError:
        return False
