"""One state transition's worth of side effects (§9.2, §9.3).

`state_machine.next_state` decides where a run goes; this module does the work
and writes the result. Each call advances a run by exactly one transition and
returns, so a function execution is always short.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Final

from vulnagent.adapters import detect_adapters
from vulnagent.agent.ci_logs import error_signature, extract_excerpt, referenced_repo_files
from vulnagent.agent.state_machine import (
    AgentEvent as MachineEvent,
)
from vulnagent.agent.state_machine import (
    RunSnapshot,
    is_terminal,
    next_state,
)
from vulnagent.config.schema import RepoConfig, parse_repo_config
from vulnagent.core.adapter import EcosystemAdapter, LockfileRegenerator, RegistryClient
from vulnagent.core.errors import VulnAgentError
from vulnagent.core.models import FileMap, UpgradePlan, VulnFinding, meets_threshold
from vulnagent.core.safety import capped_retries, review_edits
from vulnagent.db.repositories import Database
from vulnagent.db.rows import AgentRun, EventType, Repo, Vulnerability
from vulnagent.github.client import AGENT_LABEL, NEEDS_HUMAN_LABEL, GitHubClient, Repository
from vulnagent.github.pr_body import commit_message, pr_title, render_pr_body, update_agent_log
from vulnagent.llm.base import LLMProvider
from vulnagent.llm.prompts.repair import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from vulnagent.llm.schemas import RepairResponse, parse_repair_response
from vulnagent.memory.base import FailureMemory, FailureRecord
from vulnagent.scanning.reconcile import severity_counts

BRANCH_PREFIX: Final = "vulnagent/"
MAX_CONTEXT_LINES: Final = 300


@dataclass(frozen=True, slots=True)
class StepOutcome:
    state: str
    reschedule: bool
    message: str = ""


class AgentSteps:
    def __init__(
        self,
        *,
        db: Database,
        github: GitHubClient,
        registry: RegistryClient,
        regenerator: LockfileRegenerator,
        llm: LLMProvider | None = None,
        memory: FailureMemory | None = None,
        now: dt.datetime | None = None,
    ) -> None:
        self._db = db
        self._github = github
        self._registry = registry
        self._regenerator = regenerator
        self._llm = llm
        self._memory = memory
        self._now = now or dt.datetime.now(dt.UTC)

    # --- entry point -------------------------------------------------------

    def advance(self, run: AgentRun, *, event: MachineEvent | None = None) -> StepOutcome:
        repo = self._db.repos.get(run.repo_id)
        if repo is None:
            raise VulnAgentError(f"run {run.id} points at a repository that no longer exists")

        if event is not None:
            return self._apply(run, repo, event)

        handler = {
            "QUEUED": self._queued,
            "PLANNING": self._planning,
            "PATCHING": self._patching,
            "PR_OPEN": self._pr_open,
            "READY_TO_MERGE": self._ready_to_merge,
            "MERGED": self._merged,
            "REPAIRING": self._repairing,
        }.get(run.state)

        if handler is None:
            return StepOutcome(state=run.state, reschedule=False, message="waiting on GitHub")
        try:
            return handler(run, repo)
        except VulnAgentError as error:
            return self._apply(run, repo, "errored", error=str(error))

    # --- transitions -------------------------------------------------------

    def _queued(self, run: AgentRun, repo: Repo) -> StepOutcome:
        config = _config_of(repo)
        eligible = self._eligible_vulnerabilities(repo, config)
        if not eligible:
            return self._apply(run, repo, "nothing_to_do", message="no vulnerabilities to fix")

        self._db.vulnerabilities.mark([row.id for row in eligible], "in_progress")
        self._db.runs.update(
            run.id,
            {
                "vuln_ids": [row.id for row in eligible],
                "max_attempts": capped_retries(config.agent.max_ci_retries),
            },
        )
        return self._apply(
            run,
            repo,
            "vulnerabilities_selected",
            message=f"selected {len(eligible)} vulnerabilities to fix",
        )

    def _planning(self, run: AgentRun, repo: Repo) -> StepOutcome:
        config = _config_of(repo)
        target = Repository.from_full_name(repo.full_name)
        base_sha = self._github.head_sha(target, repo.default_branch)

        adapter, files = self._manifests(repo, target, config)
        graph = adapter.parse_dependencies(files)
        plan = adapter.plan_upgrades(
            self._findings_for(run),
            graph,
            allow_major_bumps=config.agent.allow_major_bumps,
            registry=self._registry,
        )

        self._record_unresolved(run, plan)
        self._db.runs.update(run.id, {"plan_json": plan.model_dump_json(), "base_sha": base_sha})

        if plan.is_empty():
            return self._apply(
                run, repo, "nothing_to_do", message="nothing could be upgraded safely"
            )
        return self._apply(
            run, repo, "plan_ready", message=f"planned {len(plan.actions)} dependency changes"
        )

    def _patching(self, run: AgentRun, repo: Repo) -> StepOutcome:
        config = _config_of(repo)
        target = Repository.from_full_name(repo.full_name)
        plan = UpgradePlan.model_validate_json(run.plan_json)
        base_sha = run.base_sha or self._github.head_sha(target, repo.default_branch)

        adapter, files = self._manifests(repo, target, config)
        patches = adapter.apply_upgrades(plan, files, self._regenerator)
        if not patches:
            return self._apply(run, repo, "nothing_to_do", message="the plan changed no files")

        branch = f"{BRANCH_PREFIX}{run.id}"
        self._github.create_branch(target, branch, base_sha)
        head_sha = self._github.commit_files(
            target,
            branch=branch,
            base_sha=base_sha,
            files={patch.path: patch.new_contents for patch in patches},
            message=commit_message(len(plan.resolves)),
        )
        self._db.runs.update(run.id, {"branch": branch, "head_sha": head_sha})
        return self._apply(run, repo, "branch_pushed", message=f"pushed {len(patches)} files")

    def _pr_open(self, run: AgentRun, repo: Repo) -> StepOutcome:
        config = _config_of(repo)
        target = Repository.from_full_name(repo.full_name)
        plan = UpgradePlan.model_validate_json(run.plan_json)
        vulnerabilities = self._vulnerabilities_of(run)

        opened = self._github.open_pull_request(
            target,
            head=run.branch or f"{BRANCH_PREFIX}{run.id}",
            base=repo.default_branch,
            title=pr_title(len(plan.resolves)),
            body=render_pr_body(
                plan,
                severities={row.purl: row.severity for row in vulnerabilities},
                advisory_for={row.purl: row.osv_id for row in vulnerabilities},
                max_attempts=capped_retries(config.agent.max_ci_retries),
            ),
        )
        number = int(opened.get("number", 0))
        self._db.runs.update(
            run.id, {"pr_number": number, "pr_url": str(opened.get("html_url", ""))}
        )
        self._github.add_labels(target, number, [AGENT_LABEL])
        self._log(run, repo, "pr_opened", f"opened pull request #{number}")
        return self._apply(run, repo, "pr_opened", message=f"pull request #{number} is open")

    def _ready_to_merge(self, run: AgentRun, repo: Repo) -> StepOutcome:
        config = _config_of(repo)
        target = Repository.from_full_name(repo.full_name)
        if run.pr_number is None:
            return self._apply(run, repo, "errored", error="the run has no pull request")

        if config.agent.auto_merge:
            self._github.merge_pull_request(target, run.pr_number)
            return StepOutcome(state=run.state, reschedule=False, message="merging")
        self._github.comment(target, run.pr_number, "Ready for review ✅")
        return StepOutcome(state=run.state, reschedule=False, message="waiting for a reviewer")

    def _merged(self, run: AgentRun, repo: Repo) -> StepOutcome:
        self._db.vulnerabilities.mark(
            run.vuln_ids, "fixed", resolved_at=self._now, resolved_by_run_id=run.id
        )
        self._remember(run, repo, outcome="success")
        self._db.repos.set_counts(
            repo.id, severity_counts(self._db.vulnerabilities.for_repo(repo.id))
        )
        self._log(run, repo, "merged", "pull request merged; vulnerabilities marked fixed")
        return self._apply(run, repo, "cleanup_done", message="run complete")

    def _repairing(self, run: AgentRun, repo: Repo) -> StepOutcome:
        if self._llm is None:
            return self._apply(run, repo, "gave_up", message="no LLM provider is configured")

        config = _config_of(repo)
        target = Repository.from_full_name(repo.full_name)
        adapter, _ = self._manifests(repo, target, config)

        excerpt = self._failure_excerpt(target, run)
        if not excerpt:
            return self._apply(run, repo, "gave_up", message="CI failed with no readable log")

        signature = error_signature(excerpt)
        hits = self._recall(run, repo, signature, adapter)
        context = self._context_files(target, run, excerpt)

        response = self._ask_for_a_repair(
            run, adapter, excerpt=excerpt, hits=hits, files=context, config=config
        )
        if response is None:
            return self._apply(run, repo, "gave_up", message="the model's response was unusable")
        if response.give_up:
            return self._apply(
                run,
                repo,
                "gave_up",
                message=response.give_up_reason or "the model gave up",
            )

        verdict = review_edits([edit.model_dump() for edit in response.edits], adapter=adapter)
        if not verdict.ok:
            self._log(run, repo, "error", f"rejected an unsafe patch: {verdict.reason}")
            return self._apply(run, repo, "unsafe_patch", message=verdict.reason)

        updated = response.apply_to(context)
        head_sha = self._github.commit_files(
            target,
            branch=run.branch or f"{BRANCH_PREFIX}{run.id}",
            base_sha=run.head_sha or "",
            files=updated,
            message=f"fix(ci): {response.analysis[:60]} [vulnagent]",
        )
        self._db.runs.update(run.id, {"head_sha": head_sha})
        self._log(run, repo, "patch_pushed", response.analysis)
        self._update_pr_log(target, run, response.analysis)
        return self._apply(run, repo, "patch_pushed", message="pushed a repair")

    # --- shared pieces -----------------------------------------------------

    def _apply(
        self, run: AgentRun, repo: Repo, event: MachineEvent, *, message: str = "", error: str = ""
    ) -> StepOutcome:
        transition = next_state(
            RunSnapshot(state=run.state, attempt=run.attempt, max_attempts=run.max_attempts),  # type: ignore[arg-type]
            event,
        )
        changes: dict[str, object] = {}
        if transition.attempt_delta:
            changes["attempt"] = run.attempt + transition.attempt_delta
        if error:
            changes["last_error"] = error[:500]
        if is_terminal(transition.to_state):
            changes["completed_at"] = self._now

        self._db.runs.save_state(run.id, transition.to_state, **changes)
        self._log(
            run,
            repo,
            _event_type_for(transition.to_state),
            message or f"{run.state} -> {transition.to_state}",
        )

        if is_terminal(transition.to_state):
            self._finish(run, repo, transition.to_state)

        from vulnagent.agent.state_machine import runs_immediately

        return StepOutcome(
            state=transition.to_state,
            reschedule=runs_immediately(transition.to_state),
            message=message,
        )

    def _finish(self, run: AgentRun, repo: Repo, state: str) -> None:
        self._db.repos.go_to_sleep(repo.id, errored=state == "ERRORED")
        if state == "GAVE_UP":
            self._give_up(run, repo)
        elif state in {"CANCELLED", "ERRORED", "NOTHING_TO_DO"}:
            self._release_vulnerabilities(run)

    def _give_up(self, run: AgentRun, repo: Repo) -> None:
        self._release_vulnerabilities(run)
        self._remember(run, repo, outcome="failed")
        if run.pr_number is None:
            return
        target = Repository.from_full_name(repo.full_name)
        self._github.comment(
            target,
            run.pr_number,
            "VulnAgent could not get CI green after "
            f"{run.attempt} attempt(s) and has stopped. The branch is left in place "
            "for a human to take over.",
        )
        self._github.add_labels(target, run.pr_number, [NEEDS_HUMAN_LABEL])

    def _release_vulnerabilities(self, run: AgentRun) -> None:
        """Anything the run claimed goes back to open so a later run can retry it."""
        for vuln_id in run.vuln_ids:
            row = self._db.vulnerabilities.get(vuln_id)
            if row is not None and row.status == "in_progress":
                self._db.vulnerabilities.update(vuln_id, {"status": "open"})

    def _eligible_vulnerabilities(self, repo: Repo, config: RepoConfig) -> list[Vulnerability]:
        today = self._now.date()
        return [
            row
            for row in self._db.vulnerabilities.open_for_repo(repo.id)
            if row.fixed_version
            and meets_threshold(row.severity, config.agent.severity_threshold)
            and not config.is_ignored(row.osv_id, on=today)
        ]

    def _vulnerabilities_of(self, run: AgentRun) -> list[Vulnerability]:
        found = [self._db.vulnerabilities.get(vuln_id) for vuln_id in run.vuln_ids]
        return [row for row in found if row is not None]

    def _findings_for(self, run: AgentRun) -> list[VulnFinding]:
        return [
            VulnFinding(
                osv_id=row.osv_id,
                purl=row.purl,
                fixed_versions=[row.fixed_version] if row.fixed_version else [],
                severity=row.severity,
            )
            for row in self._vulnerabilities_of(run)
        ]

    def _manifests(
        self, repo: Repo, target: Repository, config: RepoConfig
    ) -> tuple[EcosystemAdapter, FileMap]:
        adapters = detect_adapters(
            self._github.list_root_paths(target, repo.default_branch), config.ecosystems
        )
        if not adapters:
            raise VulnAgentError("no supported ecosystem found in the repository root")
        adapter = adapters[0]
        return adapter, self._github.get_files(target, adapter.manifest_files, repo.default_branch)

    def _record_unresolved(self, run: AgentRun, plan: UpgradePlan) -> None:
        by_osv = {row.osv_id: row for row in self._vulnerabilities_of(run)}
        for item in plan.unresolved:
            row = by_osv.get(item.osv_id)
            if row is not None:
                self._db.vulnerabilities.update(
                    row.id,
                    {"status": "needs_major" if item.reason == "needs_major" else "unfixable"},
                )

    def _failure_excerpt(self, target: Repository, run: AgentRun) -> str:
        if not run.head_sha:
            return ""
        outcome = self._github.check_outcome(target, run.head_sha)
        logs = [self._github.job_log(target, job_id) for job_id in outcome.failed_job_ids]
        return "\n".join(extract_excerpt(log) for log in logs if log).strip()

    def _recall(
        self, run: AgentRun, repo: Repo, signature: str, adapter: EcosystemAdapter
    ) -> list[str]:
        if self._memory is None or not signature:
            return []
        hits = self._memory.search(signature, ecosystem=adapter.id)
        for hit in hits:
            self._log(
                run,
                repo,
                "memory_hit",
                f"found a past fix for a similar failure (similarity {hit.score:.2f})",
            )
        return [hit.as_prompt_section() for hit in hits]

    def _context_files(self, target: Repository, run: AgentRun, excerpt: str) -> FileMap:
        paths = referenced_repo_files(excerpt)
        if not paths or not run.branch:
            return {}
        fetched = self._github.get_files(target, paths, run.branch)
        return {path: _head(contents) for path, contents in fetched.items()}

    def _ask_for_a_repair(
        self,
        run: AgentRun,
        adapter: EcosystemAdapter,
        *,
        excerpt: str,
        hits: list[str],
        files: FileMap,
        config: RepoConfig,
    ) -> RepairResponse | None:
        if self._llm is None:
            return None
        prompt = build_repair_prompt(
            upgrade_plan=_plan_summary(run),
            log_excerpt=excerpt,
            similar_fixes=hits,
            files=files,
            ecosystem_hints=adapter.ci_hints(),
            attempt=run.attempt + 1,
            max_attempts=capped_retries(config.agent.max_ci_retries),
            previous_attempts=[],
        )
        reply = self._llm.complete(system=REPAIR_SYSTEM_PROMPT, user=prompt)
        try:
            return parse_repair_response(reply)
        except VulnAgentError as first_error:
            retry = self._llm.complete(
                system=REPAIR_SYSTEM_PROMPT,
                user=f"{prompt}\n\n## PREVIOUS_RESPONSE_REJECTED\n{first_error}",
            )
            try:
                return parse_repair_response(retry)
            except VulnAgentError:
                return None

    def _remember(self, run: AgentRun, repo: Repo, *, outcome: str) -> None:
        if self._memory is None or run.attempt == 0:
            return  # nothing was repaired, so there is nothing to learn from
        plan = _plan_of(run)
        self._memory.add(
            FailureRecord(
                ecosystem=plan.ecosystem if plan else "npm",
                error_signature=run.last_error or "",
                package_changes=_plan_summary(run),
                fix_diff="",
                outcome="success" if outcome == "success" else "failed",
                repo_full_name=repo.full_name,
                run_id=run.id,
                created_at=self._now,
            )
        )

    def _update_pr_log(self, target: Repository, run: AgentRun, entry: str) -> None:
        if run.pr_number is None:
            return
        events = self._db.events.for_run(run.id)
        entries = [event.message for event in events if event.type == "patch_pushed"]
        self._github.update_pull_request_body(
            target, run.pr_number, update_agent_log("", [*entries, entry])
        )

    def _log(self, run: AgentRun, repo: Repo, event_type: EventType, message: str) -> None:
        self._db.events.log(run_id=run.id, repo_id=repo.id, event_type=event_type, message=message)


def _config_of(repo: Repo) -> RepoConfig:
    if not repo.config_json:
        return RepoConfig()
    return parse_repo_config(repo.config_json, path=".vulnagent.yml")


def _plan_of(run: AgentRun) -> UpgradePlan | None:
    if not run.plan_json:
        return None
    try:
        return UpgradePlan.model_validate_json(run.plan_json)
    except ValueError:
        return None


def _plan_summary(run: AgentRun) -> str:
    plan = _plan_of(run)
    if plan is None:
        return ""
    return "; ".join(
        f"{getattr(action, 'name', None) or getattr(action, 'parent_name', '')} "
        f"{getattr(action, 'from_version', '?')}->{action.to_version}"
        for action in plan.actions
    )


def _head(contents: str) -> str:
    lines = contents.splitlines()
    return "\n".join(lines[:MAX_CONTEXT_LINES])


_STATE_EVENTS: Final[dict[str, EventType]] = {
    "GAVE_UP": "gave_up",
    "ERRORED": "error",
    "MERGED": "merged",
    "AWAITING_CI": "state_change",
}


def _event_type_for(state: str) -> EventType:
    return _STATE_EVENTS.get(state, "state_change")


def plan_json_of(plan: UpgradePlan) -> str:
    return json.dumps(plan.model_dump(mode="json"))
