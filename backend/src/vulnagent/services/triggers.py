"""What wakes the agent, and when (§10).

Kept out of the function entry points so the decisions are testable: whether a
push touched a manifest, when the next scheduled scan is due, and whether a
scan's findings justify starting a run.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final, Protocol

from croniter import croniter

from vulnagent.adapters import ADAPTERS
from vulnagent.config.schema import RepoConfig, parse_repo_config
from vulnagent.core.models import meets_threshold
from vulnagent.db.repositories import Database
from vulnagent.db.rows import AgentRun, Repo, RunTrigger
from vulnagent.entrypoints.tasks import Task
from vulnagent.github.webhooks import CiCompleted, PullRequestClosed, PushToDefaultBranch

DEBOUNCE: Final = dt.timedelta(minutes=5)


class HasDb(Protocol):
    db: Database

    def enqueue(self, task: Task, payload: dict[str, Any]) -> None: ...


def config_of(repo: Repo) -> RepoConfig:
    if not repo.config_json:
        return RepoConfig()
    return parse_repo_config(repo.config_json, path=".vulnagent.yml")


def touches_a_manifest(paths: list[str]) -> bool:
    """Only a manifest or lockfile change can alter the dependency tree."""
    return any(adapter.is_manifest_path(path) for path in paths for adapter in ADAPTERS)


def next_scan_time(repo: Repo, now: dt.datetime) -> dt.datetime | None:
    schedule = config_of(repo).scan.schedule
    if not schedule:
        return None
    following: dt.datetime = croniter(schedule, now).get_next(dt.datetime)
    return following


def should_start_agent(repo: Repo, *, new_vulns: int, worst_severity: str) -> bool:
    config = config_of(repo)
    return bool(
        config.enabled
        and config.agent.auto_start
        and new_vulns
        and not repo.active_run_id
        and meets_threshold(worst_severity, config.agent.severity_threshold)
    )


def start_agent_run(app: HasDb, repo: Repo, *, trigger: RunTrigger) -> AgentRun:
    """Create a run, claim the repository, and kick off the first step."""
    config = config_of(repo)
    run = app.db.runs.create(
        AgentRun(repo_id=repo.id, trigger=trigger, max_attempts=config.agent.max_ci_retries)
    )
    app.db.repos.start_run(repo.id, run.id)
    app.db.events.log(
        run_id=run.id,
        repo_id=repo.id,
        event_type="state_change",
        message=f"run queued ({trigger})",
    )
    app.enqueue("agent_step", {"run_id": run.id, "expected_state": "QUEUED"})
    return run


def maybe_start_agent(app: HasDb, repo: Repo, result: Any) -> AgentRun | None:
    fresh = app.db.repos.get(repo.id) or repo
    if not should_start_agent(
        fresh, new_vulns=result.new_vulns, worst_severity=result.worst_new_severity
    ):
        return None
    return start_agent_run(app, fresh, trigger="auto")


def start_scan(app: HasDb, push: PushToDefaultBranch) -> bool:
    repo = app.db.repos.by_full_name(push.repo_full_name)
    if repo is None or not touches_a_manifest(push.changed_paths):
        return False
    if not config_of(repo).scan.on_push:
        return False
    app.enqueue("scan", {"repo_id": repo.id, "trigger": "push"})
    return True


def wake_agent_for_ci(app: HasDb, result: CiCompleted) -> bool:
    repo = app.db.repos.by_full_name(result.repo_full_name)
    if repo is None or not repo.active_run_id:
        return False

    run = app.db.runs.get(repo.active_run_id)
    # §9.5: ignore CI for any commit other than the one the run pushed.
    if run is None or run.head_sha != result.head_sha or run.state != "AWAITING_CI":
        return False

    app.enqueue(
        "agent_step",
        {
            "run_id": run.id,
            "expected_state": "AWAITING_CI",
            "event": "ci_passed" if result.passed else "ci_failed",
        },
    )
    return True


def wake_agent_for_closed_pr(app: HasDb, closed: PullRequestClosed) -> bool:
    repo = app.db.repos.by_full_name(closed.repo_full_name)
    if repo is None:
        return False

    run = app.db.runs.by_pr_number(repo.id, closed.number)
    if run is None:
        return False

    app.enqueue(
        "agent_step",
        {
            "run_id": run.id,
            "expected_state": run.state,
            "event": "pr_merged" if closed.merged else "pr_closed",
        },
    )
    return True
