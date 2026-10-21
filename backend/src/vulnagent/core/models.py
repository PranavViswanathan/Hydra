"""Ecosystem-agnostic domain models.

Nothing here knows about npm, Maven or any other package manager; adapters
(§6) translate their own file formats into these types.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

type Purl = str  # "pkg:npm/lodash@4.17.20", "pkg:npm/%40scope/name@1.2.3"
type Severity = Literal["low", "medium", "high", "critical", "unknown"]
type Threshold = Literal["low", "medium", "high", "critical"]
type FileMap = dict[str, str]  # repo-relative path -> contents

ROOT: Literal["ROOT"] = "ROOT"

# "unknown" is ranked alongside "low": an advisory with no severity data still
# reaches the lowest threshold, but never a deliberately raised one.
_SEVERITY_RANK: dict[str, int] = {
    "unknown": 1,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, 1)


def meets_threshold(severity: str, threshold: str) -> bool:
    return severity_rank(severity) >= severity_rank(threshold)


class DepNode(BaseModel):
    purl: Purl
    name: str
    version: str
    is_direct: bool
    is_dev: bool


class DepEdge(BaseModel):
    parent: Purl | Literal["ROOT"]
    child: Purl
    requested_range: str


class DepGraph(BaseModel):
    ecosystem: str
    nodes: dict[Purl, DepNode]
    edges: list[DepEdge]


class VulnFinding(BaseModel):
    osv_id: str
    aliases: list[str] = Field(default_factory=list)
    purl: Purl
    fixed_versions: list[str] = Field(default_factory=list)  # ascending
    severity: Severity = "unknown"


class BumpDirect(BaseModel):
    kind: Literal["bump_direct"] = "bump_direct"
    name: str
    from_version: str
    to_version: str
    manifest_path: str


class BumpParent(BaseModel):
    kind: Literal["bump_parent"] = "bump_parent"
    parent_name: str
    from_version: str
    to_version: str
    reason: Purl
    manifest_path: str


class Override(BaseModel):
    kind: Literal["override"] = "override"
    name: str
    to_version: str
    reason: Purl
    manifest_path: str


type UpgradeAction = Annotated[BumpDirect | BumpParent | Override, Field(discriminator="kind")]


class Unresolved(BaseModel):
    osv_id: str
    reason: Literal["no_fix", "needs_major", "conflict"]


class UpgradePlan(BaseModel):
    ecosystem: str
    actions: list[UpgradeAction] = Field(default_factory=list)
    resolves: list[str] = Field(default_factory=list)
    unresolved: list[Unresolved] = Field(default_factory=list)
    major_bumps: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.actions


class FilePatch(BaseModel):
    path: str
    new_contents: str
