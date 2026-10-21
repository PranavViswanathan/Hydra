"""Write an :class:`UpgradePlan` into `package.json` and regenerate the lockfile (§6.4).

The manifest is a file humans maintain, so the rewrite preserves key order,
indentation and the trailing newline: the PR diff should show the version
lines that changed and nothing else.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from vulnagent.adapters.npm.planner import manifest_range_for
from vulnagent.core.adapter import LockfileRegenerator
from vulnagent.core.models import (
    BumpDirect,
    BumpParent,
    FileMap,
    FilePatch,
    Override,
    UpgradeAction,
    UpgradePlan,
)

MANIFEST: Final = "package.json"
LOCKFILE: Final = "package-lock.json"

_DEPENDENCY_SECTIONS: Final = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)

_INDENT_PATTERN: Final = re.compile(r"^\{\s*?\n([ \t]+)", re.MULTILINE)
_DEFAULT_INDENT: Final = "  "


def apply_upgrades(
    plan: UpgradePlan, files: FileMap, regenerator: LockfileRegenerator
) -> list[FilePatch]:
    original = files.get(MANIFEST)
    if original is None or not plan.actions:
        return []

    manifest: dict[str, Any] = json.loads(original)
    changed = False
    for action in plan.actions:
        changed |= _apply(action, manifest)
    if not changed:
        return []

    rewritten = _dump_like(manifest, original)
    patches = [FilePatch(path=MANIFEST, new_contents=rewritten)]

    updated = dict(files)
    updated[MANIFEST] = rewritten
    regenerated = regenerator.regenerate(updated).get(LOCKFILE)
    if regenerated is not None and regenerated != files.get(LOCKFILE):
        patches.append(FilePatch(path=LOCKFILE, new_contents=regenerated))
    return patches


def _apply(action: UpgradeAction, manifest: dict[str, Any]) -> bool:
    match action:
        case BumpDirect(name=name) | BumpParent(parent_name=name):
            return _rewrite_requirement(manifest, name, action.to_version)
        case Override(name=name):
            return _pin_override(manifest, name, action.to_version)


def _rewrite_requirement(manifest: dict[str, Any], name: str, version: str) -> bool:
    for section_name in _DEPENDENCY_SECTIONS:
        section = manifest.get(section_name)
        if not isinstance(section, dict) or name not in section:
            continue
        declared = str(section[name])
        updated = manifest_range_for(declared, version)
        if updated == declared:
            return False
        section[name] = updated
        return True
    return False  # not a direct dependency of this manifest; the lockfile handles it


def _pin_override(manifest: dict[str, Any], name: str, version: str) -> bool:
    overrides = manifest.get("overrides")
    if not isinstance(overrides, dict):
        overrides = {}
        manifest["overrides"] = overrides
    if overrides.get(name) == version:
        return False
    overrides[name] = version
    return True


def _dump_like(manifest: dict[str, Any], original: str) -> str:
    indent = _detect_indent(original)
    text = json.dumps(manifest, indent=indent, ensure_ascii=False)
    return f"{text}\n" if original.endswith("\n") else text


def _detect_indent(original: str) -> str:
    match = _INDENT_PATTERN.search(original)
    return match.group(1) if match else _DEFAULT_INDENT
