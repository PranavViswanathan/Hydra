"""The npm :class:`EcosystemAdapter` (§6.4)."""

from __future__ import annotations

from typing import ClassVar

from vulnagent.adapters.npm import parser
from vulnagent.core.models import DepGraph, FileMap, Purl


class NpmAdapter:
    id = "npm"
    osv_ecosystem = "npm"
    manifest_files: ClassVar[list[str]] = [parser.MANIFEST, parser.LOCKFILE]

    def detect(self, repo_file_paths: list[str]) -> bool:
        present = set(repo_file_paths)
        return all(path in present for path in self.manifest_files)

    def parse_dependencies(self, files: FileMap) -> DepGraph:
        return parser.parse_lockfile(files)

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
