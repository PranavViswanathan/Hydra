"""The adapter registry (§6.3).

Adding an ecosystem means adding a module under this package and listing it
here. Nothing in the core changes.
"""

from __future__ import annotations

from typing import Literal

from vulnagent.adapters.npm.adapter import NpmAdapter
from vulnagent.core.adapter import EcosystemAdapter
from vulnagent.core.errors import ConfigError

ADAPTERS: list[EcosystemAdapter] = [NpmAdapter()]


def detect_adapters(
    paths: list[str], configured: Literal["auto"] | list[str]
) -> list[EcosystemAdapter]:
    """The adapters that should run against a repo with these files."""
    if configured == "auto":
        return [adapter for adapter in ADAPTERS if adapter.detect(paths)]

    by_id = {adapter.id: adapter for adapter in ADAPTERS}
    chosen: list[EcosystemAdapter] = []
    for ecosystem in configured:
        adapter = by_id.get(ecosystem)
        if adapter is None:
            raise ConfigError(
                f"unknown ecosystem {ecosystem!r}; supported: {', '.join(sorted(by_id))}"
            )
        if not adapter.detect(paths):
            raise ConfigError(
                f"ecosystem {ecosystem!r} is configured but its files "
                f"({', '.join(adapter.manifest_files)}) are not in the repository root"
            )
        chosen.append(adapter)
    return chosen
