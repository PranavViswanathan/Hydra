"""Turn a v2/v3 `package-lock.json` into a :class:`DepGraph`.

The lockfile's ``packages`` map is keyed by install path, so the tree structure
is encoded in the keys: ``node_modules/a/node_modules/b`` is the copy of ``b``
installed beside ``a``. Resolving an edge therefore means replaying Node's
lookup: check the requester's own ``node_modules`` first, then each ancestor's,
and finally the hoisted copy at the root.
"""

from __future__ import annotations

import json
from typing import Any, Final

from vulnagent.core.errors import UnsupportedLockfileError
from vulnagent.core.models import ROOT, DepEdge, DepGraph, DepNode, Purl
from vulnagent.core.purl import make_purl

ECOSYSTEM: Final = "npm"
MANIFEST: Final = "package.json"
LOCKFILE: Final = "package-lock.json"
SUPPORTED_LOCKFILE_VERSIONS: Final = (2, 3)

_NODE_MODULES: Final = "node_modules/"
_SEPARATOR: Final = "/node_modules/"

# Which dependency maps contribute edges. The root additionally contributes its
# devDependencies; a package's own devDependencies are not installed.
_DEPENDENCY_KEYS: Final = ("dependencies", "optionalDependencies", "peerDependencies")
_ROOT_DEPENDENCY_KEYS: Final = (*_DEPENDENCY_KEYS, "devDependencies")

_MAX_PATHS: Final = 10
_MAX_DEPTH: Final = 32


def parse_lockfile(files: dict[str, str]) -> DepGraph:
    packages = _read_packages(files)
    installed = _installed_packages(packages)
    root = packages.get("", {})

    nodes = _build_nodes(installed, root=root, packages=packages)
    edges = _build_edges(installed, root=root, packages=packages)
    return DepGraph(ecosystem=ECOSYSTEM, nodes=nodes, edges=edges)


def paths_to_root(graph: DepGraph, purl: Purl) -> list[list[Purl | str]]:
    """Every dependency path from ``ROOT`` down to ``purl``, outermost first."""
    parents: dict[str, list[str]] = {}
    for edge in graph.edges:
        parents.setdefault(edge.child, []).append(edge.parent)

    found: list[list[Purl | str]] = []

    def walk(current: str, tail: list[str], seen: frozenset[str]) -> None:
        if len(found) >= _MAX_PATHS or len(tail) > _MAX_DEPTH:
            return
        for parent in parents.get(current, []):
            if parent == ROOT:
                found.append([ROOT, *tail])
            elif parent not in seen:
                walk(parent, [parent, *tail], seen | {parent})

    walk(purl, [purl], frozenset({purl}))
    return found


def _read_packages(files: dict[str, str]) -> dict[str, dict[str, Any]]:
    if LOCKFILE not in files:
        raise UnsupportedLockfileError(f"{LOCKFILE} is missing; cannot resolve the dependency tree")
    try:
        lock = json.loads(files[LOCKFILE])
    except json.JSONDecodeError as error:
        raise UnsupportedLockfileError(f"{LOCKFILE} is not valid JSON: {error}") from error
    if not isinstance(lock, dict):
        raise UnsupportedLockfileError(f"{LOCKFILE} should contain an object")

    version = lock.get("lockfileVersion")
    if version not in SUPPORTED_LOCKFILE_VERSIONS:
        raise UnsupportedLockfileError(
            f"lockfileVersion {version} is not supported; run `npm install` with npm 7 or newer "
            f"to upgrade to lockfileVersion {SUPPORTED_LOCKFILE_VERSIONS[-1]}"
        )

    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise UnsupportedLockfileError(
            f"{LOCKFILE} has no `packages` map, which lockfileVersion {version} requires"
        )
    return packages


def _installed_packages(packages: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The real installs: no root entry, no workspace members, no symlinks."""
    return {
        path: entry
        for path, entry in packages.items()
        if path.startswith(_NODE_MODULES)
        and isinstance(entry, dict)
        and not entry.get("link", False)
        and isinstance(entry.get("version"), str)
    }


def package_name_at(path: str) -> str:
    """``node_modules/a/node_modules/@scope/b`` -> ``@scope/b``."""
    return path.rsplit(_NODE_MODULES, 1)[-1]


def _purl_at(path: str, entry: dict[str, Any]) -> Purl:
    name = entry.get("name") if isinstance(entry.get("name"), str) else package_name_at(path)
    return make_purl(ECOSYSTEM, str(name), str(entry["version"]))


def _resolve(requester_path: str, name: str, packages: dict[str, dict[str, Any]]) -> str | None:
    """Replay Node's resolution: nearest `node_modules` first, then up to the root."""
    prefix = requester_path
    while True:
        candidate = f"{prefix}{_SEPARATOR}{name}" if prefix else f"{_NODE_MODULES}{name}"
        if candidate in packages:
            return candidate
        if not prefix:
            return None
        separator_at = prefix.rfind(_SEPARATOR)
        prefix = prefix[:separator_at] if separator_at != -1 else ""


def _requirements(entry: dict[str, Any], keys: tuple[str, ...]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key in keys:
        section = entry.get(key)
        if isinstance(section, dict):
            for name, requested in section.items():
                merged.setdefault(str(name), str(requested))
    return merged


def _build_nodes(
    installed: dict[str, dict[str, Any]],
    *,
    root: dict[str, Any],
    packages: dict[str, dict[str, Any]],
) -> dict[Purl, DepNode]:
    direct_paths = {
        resolved
        for name in _requirements(root, _ROOT_DEPENDENCY_KEYS)
        if (resolved := _resolve("", name, packages)) is not None
    }

    nodes: dict[Purl, DepNode] = {}
    for path, entry in installed.items():
        purl = _purl_at(path, entry)
        nodes[purl] = DepNode(
            purl=purl,
            name=package_name_at(path),
            version=str(entry["version"]),
            is_direct=path in direct_paths,
            is_dev=bool(entry.get("dev", False)),
        )
    return nodes


def _build_edges(
    installed: dict[str, dict[str, Any]],
    *,
    root: dict[str, Any],
    packages: dict[str, dict[str, Any]],
) -> list[DepEdge]:
    edges: list[DepEdge] = []
    seen: set[tuple[str, str]] = set()

    def add(parent: str, requester_path: str, requirements: dict[str, str]) -> None:
        for name, requested in requirements.items():
            resolved = _resolve(requester_path, name, packages)
            if resolved is None or resolved not in installed:
                continue  # an optional dependency that was never installed
            child = _purl_at(resolved, installed[resolved])
            if (parent, child) in seen:
                continue
            seen.add((parent, child))
            edges.append(DepEdge(parent=parent, child=child, requested_range=requested))

    add(ROOT, "", _requirements(root, _ROOT_DEPENDENCY_KEYS))
    for path, entry in installed.items():
        add(_purl_at(path, entry), path, _requirements(entry, _DEPENDENCY_KEYS))
    return edges
