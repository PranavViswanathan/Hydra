"""The npm :class:`EcosystemAdapter` (§6.4)."""

from __future__ import annotations

from vulnagent.adapters.npm import applier, parser, planner
from vulnagent.core.adapter import LockfileRegenerator, RegistryClient
from vulnagent.core.models import (
    DepGraph,
    FileMap,
    FilePatch,
    Purl,
    UpgradeAction,
    UpgradePlan,
    VulnFinding,
)


class NpmAdapter:
    id = "npm"
    osv_ecosystem = "npm"

    def __init__(self) -> None:
        self.manifest_files = [parser.MANIFEST, parser.LOCKFILE]

    def detect(self, repo_file_paths: list[str]) -> bool:
        present = set(repo_file_paths)
        return all(path in present for path in self.manifest_files)

    def parse_dependencies(self, files: FileMap) -> DepGraph:
        return parser.parse_lockfile(files)

    def plan_upgrades(
        self,
        findings: list[VulnFinding],
        graph: DepGraph,
        *,
        allow_major_bumps: bool,
        registry: RegistryClient,
    ) -> UpgradePlan:
        return planner.plan_upgrades(
            findings, graph, allow_major_bumps=allow_major_bumps, registry=registry
        )

    def apply_upgrades(
        self, plan: UpgradePlan, files: FileMap, regenerator: LockfileRegenerator
    ) -> list[FilePatch]:
        return applier.apply_upgrades(plan, files, regenerator)

    def manifest_range_for(self, action: UpgradeAction, declared: str) -> str:
        """The range to write back into package.json for `action`."""
        return planner.manifest_range_for(declared, action.to_version)

    def paths_to_root(self, graph: DepGraph, purl: Purl) -> list[list[Purl | str]]:
        """Dependency paths from the root down to ``purl``, for the dashboard."""
        return parser.paths_to_root(graph, purl)

    def is_manifest_path(self, path: str) -> bool:
        return path in self.manifest_files

    def ci_hints(self) -> list[str]:
        return [
            "Errors referencing `node_modules` paths usually mean an API change in a bumped "
            "package; check that package's changelog for breaking changes.",
            "`TypeError: x is not a function` after an upgrade often means a default export "
            "became a named export, or a sync function became async.",
            "If the failure is a type error only, the fix usually belongs in the calling code, "
            "not in the dependency.",
        ]
