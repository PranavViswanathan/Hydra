"""The contract every ecosystem adapter implements.

The core calls only these methods, so adding an ecosystem means adding a module
under ``vulnagent/adapters/`` and registering it. No core changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vulnagent.core.models import DepGraph, FileMap, FilePatch, UpgradePlan, VulnFinding


@runtime_checkable
class RegistryClient(Protocol):
    """Read-only view of a package registry (npm, Maven Central, PyPI...)."""

    def list_versions(self, name: str) -> list[str]: ...

    def get_dependencies(self, name: str, version: str) -> dict[str, str]: ...


@runtime_checkable
class LockfileRegenerator(Protocol):
    """Regenerates a lockfile from a manifest, out of process (§6.4)."""

    def regenerate(self, files: FileMap) -> FileMap: ...


@runtime_checkable
class EcosystemAdapter(Protocol):
    id: str  # "npm"
    osv_ecosystem: str  # "npm" | "Maven" | "PyPI"
    manifest_files: list[str]  # ["package.json", "package-lock.json"]

    def detect(self, repo_file_paths: list[str]) -> bool: ...

    def parse_dependencies(self, files: FileMap) -> DepGraph: ...

    def plan_upgrades(
        self,
        findings: list[VulnFinding],
        graph: DepGraph,
        *,
        allow_major_bumps: bool,
        registry: RegistryClient,
    ) -> UpgradePlan: ...

    def apply_upgrades(
        self, plan: UpgradePlan, files: FileMap, regenerator: LockfileRegenerator
    ) -> list[FilePatch]:
        """Rewrite the manifest and, through `regenerator`, its lockfile."""
        ...

    def is_manifest_path(self, path: str) -> bool: ...

    def ci_hints(self) -> list[str]: ...
