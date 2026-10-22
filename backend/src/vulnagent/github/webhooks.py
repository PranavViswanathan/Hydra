"""Read GitHub webhook deliveries into the handful of facts the agent needs (§10).

Signature verification lives in `core.safety`; this module assumes it already
passed and only reads the payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

type Routing = Literal[
    "installation_changed",
    "push_to_default_branch",
    "ci_completed",
    "pull_request_closed",
    "ignored",
]

_INSTALLATION_EVENTS: Final = frozenset({"installation", "installation_repositories"})
_CI_EVENTS: Final = frozenset({"workflow_run", "check_suite"})


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_id: str
    event: str
    payload: dict[str, Any]

    @property
    def action(self) -> str:
        return str(self.payload.get("action", ""))


@dataclass(frozen=True, slots=True)
class InstallationChange:
    installation_id: int
    account_login: str
    account_type: str
    suspended: bool
    removed: bool
    repositories: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PushToDefaultBranch:
    repo_full_name: str
    installation_id: int
    after_sha: str
    changed_paths: list[str]


@dataclass(frozen=True, slots=True)
class CiCompleted:
    repo_full_name: str
    installation_id: int
    head_sha: str
    conclusion: str

    @property
    def passed(self) -> bool:
        return self.conclusion in {"success", "neutral", "skipped"}


@dataclass(frozen=True, slots=True)
class PullRequestClosed:
    repo_full_name: str
    installation_id: int
    number: int
    merged: bool
    head_branch: str


def route(delivery: Delivery) -> Routing:
    if delivery.event in _INSTALLATION_EVENTS:
        return "installation_changed"
    if delivery.event == "push" and _is_default_branch_push(delivery.payload):
        return "push_to_default_branch"
    if delivery.event in _CI_EVENTS and _is_completed(delivery):
        return "ci_completed"
    if delivery.event == "pull_request" and delivery.action == "closed":
        return "pull_request_closed"
    return "ignored"


def read_installation_change(payload: dict[str, Any]) -> InstallationChange:
    installation = _dict(payload.get("installation"))
    account = _dict(installation.get("account"))
    repositories = payload.get("repositories") or payload.get("repositories_added") or []
    return InstallationChange(
        installation_id=int(installation.get("id", 0)),
        account_login=str(account.get("login", "")),
        account_type=str(account.get("type", "User")),
        suspended=installation.get("suspended_at") is not None,
        removed=str(payload.get("action", "")) in {"deleted", "removed"},
        repositories=[repo for repo in repositories if isinstance(repo, dict)],
    )


def read_push(payload: dict[str, Any]) -> PushToDefaultBranch:
    changed: list[str] = []
    for commit in payload.get("commits", []):
        if not isinstance(commit, dict):
            continue
        for key in ("added", "modified", "removed"):
            changed.extend(str(path) for path in commit.get(key, []))
    return PushToDefaultBranch(
        repo_full_name=_repo_full_name(payload),
        installation_id=_installation_id(payload),
        after_sha=str(payload.get("after", "")),
        changed_paths=sorted(set(changed)),
    )


def read_ci_completed(delivery: Delivery) -> CiCompleted:
    body = _dict(delivery.payload.get("workflow_run") or delivery.payload.get("check_suite"))
    return CiCompleted(
        repo_full_name=_repo_full_name(delivery.payload),
        installation_id=_installation_id(delivery.payload),
        head_sha=str(body.get("head_sha", "")),
        conclusion=str(body.get("conclusion") or ""),
    )


def read_pull_request_closed(payload: dict[str, Any]) -> PullRequestClosed:
    pull_request = _dict(payload.get("pull_request"))
    return PullRequestClosed(
        repo_full_name=_repo_full_name(payload),
        installation_id=_installation_id(payload),
        number=int(pull_request.get("number", 0)),
        merged=bool(pull_request.get("merged", False)),
        head_branch=str(_dict(pull_request.get("head")).get("ref", "")),
    )


def _is_default_branch_push(payload: dict[str, Any]) -> bool:
    repository = _dict(payload.get("repository"))
    default_branch = str(repository.get("default_branch", ""))
    return bool(default_branch) and str(payload.get("ref", "")) == f"refs/heads/{default_branch}"


def _is_completed(delivery: Delivery) -> bool:
    if delivery.event == "workflow_run":
        return delivery.action == "completed"
    return delivery.action in {"completed", "requested"} and bool(
        _dict(delivery.payload.get("check_suite")).get("conclusion")
    )


def _repo_full_name(payload: dict[str, Any]) -> str:
    return str(_dict(payload.get("repository")).get("full_name", ""))


def _installation_id(payload: dict[str, Any]) -> int:
    return int(_dict(payload.get("installation")).get("id", 0))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
