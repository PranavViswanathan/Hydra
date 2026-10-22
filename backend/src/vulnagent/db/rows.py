"""Row models for every table in §7.

These are what the rest of the code works with; nothing outside `vulnagent.db`
sees an Appwrite row dictionary.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from vulnagent.core.models import Severity

DATABASE_ID: Final = "vulnagent"
VECTORS_DATABASE_ID: Final = "vulnagent_vectors"

type AgentStateLabel = Literal["idle", "scanning", "working", "error"]
type ScanTrigger = Literal["schedule", "push", "new_advisory", "manual"]
type ScanStatus = Literal["running", "succeeded", "failed"]
type VulnStatus = Literal["open", "in_progress", "fixed", "ignored", "unfixable", "needs_major"]
type RunTrigger = Literal["auto", "manual"]
type EventType = Literal[
    "state_change",
    "info",
    "pr_opened",
    "ci_failed",
    "ci_passed",
    "memory_hit",
    "patch_pushed",
    "gave_up",
    "merged",
    "error",
]


class Row(BaseModel):
    """Appwrite's own `$`-prefixed fields are kept out of the domain models."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default="", alias="$id")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Any:
        return cls.model_validate({key: value for key, value in row.items() if key != "$sequence"})

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"id"})
        return {key: value for key, value in data.items() if value is not None}


class Installation(Row):
    github_installation_id: int
    account_login: str
    account_type: Literal["User", "Organization"] = "User"
    owner_user_id: str | None = None
    suspended: bool = False


class Repo(Row):
    installation_id: str
    github_repo_id: int
    full_name: str
    default_branch: str = "main"
    owner_user_id: str | None = None
    has_config: bool = False
    config_json: str = ""
    config_error: str | None = None
    ecosystems: list[str] = Field(default_factory=list)
    agent_state: AgentStateLabel = "idle"
    active_run_id: str | None = None
    next_scan_at: dt.datetime | None = None
    last_scan_at: dt.datetime | None = None
    open_critical: int = 0
    open_high: int = 0
    open_medium: int = 0
    open_low: int = 0
    open_unknown: int = 0

    def counts(self) -> dict[Severity, int]:
        return {
            "critical": self.open_critical,
            "high": self.open_high,
            "medium": self.open_medium,
            "low": self.open_low,
            "unknown": self.open_unknown,
        }


class Scan(Row):
    repo_id: str
    trigger: ScanTrigger
    status: ScanStatus = "running"
    commit_sha: str = ""
    packages_scanned: int = 0
    vulns_found: int = 0
    error: str | None = None
    started_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    finished_at: dt.datetime | None = None


class RepoPackage(Row):
    repo_id: str
    purl: str
    ecosystem: str
    name: str
    version: str
    is_direct: bool = False
    is_dev: bool = False
    scan_id: str = ""


class DependencyEdge(Row):
    repo_id: str
    parent_purl: str
    child_purl: str
    requested_range: str = ""
    ecosystem: str = "npm"
    scan_id: str = ""


class AdvisoryRow(Row):
    osv_id: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    details: str = ""
    severity: Severity = "unknown"
    cvss_score: float | None = None
    affected_json: str = ""
    osv_modified: dt.datetime | None = None


class Vulnerability(Row):
    repo_id: str
    osv_id: str
    purl: str
    package_name: str
    installed_version: str
    fixed_version: str | None = None
    severity: Severity = "unknown"
    status: VulnStatus = "open"
    is_direct: bool = False
    first_seen_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    last_seen_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    resolved_at: dt.datetime | None = None
    resolved_by_run_id: str | None = None


class AgentRun(Row):
    repo_id: str
    trigger: RunTrigger = "auto"
    state: str = "QUEUED"
    attempt: int = 0
    max_attempts: int = 3
    vuln_ids: list[str] = Field(default_factory=list)
    plan_json: str = ""
    branch: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    last_error: str | None = None
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    updated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    completed_at: dt.datetime | None = None


class AgentEvent(Row):
    run_id: str
    repo_id: str
    type: EventType
    message: str
    data_json: str | None = None
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))


class WebhookDelivery(Row):
    delivery_id: str
    event: str
    received_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
