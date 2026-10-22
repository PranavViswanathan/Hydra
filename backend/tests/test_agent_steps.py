import datetime as dt

import pytest

from tests.fakes import FakeTablesDB
from vulnagent.agent.steps import AgentSteps
from vulnagent.core.models import UpgradePlan
from vulnagent.db.repositories import Database
from vulnagent.db.rows import AgentRun, Repo, Vulnerability
from vulnagent.memory.base import FailureRecord, Hit

NOW = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.UTC)
LODASH = "pkg:npm/lodash@4.17.20"


class FakeGitHub:
    def __init__(self) -> None:
        self.commits: list[dict] = []
        self.comments: list[str] = []
        self.labels: list[str] = []
        self.merged: list[int] = []
        self.logs = "TypeError: jwt.sign is not a function\n    at signToken (src/auth.ts:12:19)"
        self.failed_job_ids = [1]
        self.files = {"src/auth.ts": "const t = jwt.sign(p)\n"}

    def head_sha(self, repo, branch):
        return "base1"

    def list_root_paths(self, repo, ref):
        return ["package.json", "package-lock.json"]

    def get_files(self, repo, paths, ref):
        return {path: self.files[path] for path in paths if path in self.files}

    def create_branch(self, repo, branch, from_sha):
        return None

    def commit_files(self, repo, *, branch, base_sha, files, message):
        self.commits.append({"branch": branch, "files": files, "message": message})
        return f"sha{len(self.commits)}"

    def open_pull_request(self, repo, *, head, base, title, body):
        return {"number": 7, "html_url": "https://github.com/pranav/test-app/pull/7"}

    def update_pull_request_body(self, repo, number, body):
        return None

    def add_labels(self, repo, number, labels):
        self.labels.extend(labels)

    def comment(self, repo, number, body):
        self.comments.append(body)

    def merge_pull_request(self, repo, number):
        self.merged.append(number)

    def check_outcome(self, repo, sha):
        from vulnagent.github.client import CheckOutcome

        return CheckOutcome(
            all_completed=True,
            all_passed=not self.failed_job_ids,
            failed_job_ids=self.failed_job_ids,
        )

    def job_log(self, repo, job_id):
        return self.logs


class FakeRegistry:
    def list_versions(self, name):
        return []

    def get_dependencies(self, name, version):
        return {}


class FakeRegenerator:
    def regenerate(self, files):
        return {"package-lock.json": '{"lockfileVersion": 3, "regenerated": true}\n'}


class FakeLLM:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, *, system, user):
        self.prompts.append(user)
        return self.replies.pop(0) if self.replies else "{}"


class FakeMemory:
    def __init__(self, hits: list[Hit] | None = None) -> None:
        self.hits = hits or []
        self.added: list[FailureRecord] = []

    def add(self, record):
        self.added.append(record)

    def search(self, signature, *, ecosystem, k=3):
        return self.hits


MANIFEST = '{\n  "name": "test-app",\n  "dependencies": {\n    "lodash": "^4.17.20"\n  }\n}\n'
LOCKFILE = """{
  "name": "test-app",
  "lockfileVersion": 3,
  "packages": {
    "": {"name": "test-app", "dependencies": {"lodash": "^4.17.20"}},
    "node_modules/lodash": {"version": "4.17.20"}
  }
}
"""


@pytest.fixture
def tables():
    return FakeTablesDB()


@pytest.fixture
def db(tables):
    return Database(tables)


@pytest.fixture
def github():
    client = FakeGitHub()
    client.files["package.json"] = MANIFEST
    client.files["package-lock.json"] = LOCKFILE
    return client


@pytest.fixture
def repo(db):
    return db.repos.create(
        Repo(
            installation_id="inst1",
            github_repo_id=1,
            full_name="pranav/test-app",
            default_branch="main",
            config_json="version: 1\nagent:\n  severity_threshold: medium\n",
        )
    )


def steps(db, github, **overrides):
    return AgentSteps(
        **{
            "db": db,
            "github": github,
            "registry": FakeRegistry(),
            "regenerator": FakeRegenerator(),
            "now": NOW,
            **overrides,
        }
    )


def a_vuln(db, repo, **overrides) -> Vulnerability:
    return db.vulnerabilities.create(
        Vulnerability(
            **{
                "repo_id": repo.id,
                "osv_id": "GHSA-a",
                "purl": LODASH,
                "package_name": "lodash",
                "installed_version": "4.17.20",
                "fixed_version": "4.17.21",
                "severity": "high",
                "status": "open",
                "is_direct": True,
                **overrides,
            }
        )
    )


def a_run(db, repo, **overrides) -> AgentRun:
    return db.runs.create(AgentRun(**{"repo_id": repo.id, "state": "QUEUED", **overrides}))


class TestSelectingWhatToFix:
    def test_claims_the_open_vulnerabilities_above_the_threshold(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(db, repo)

        outcome = steps(db, github).advance(run)

        assert outcome.state == "PLANNING"
        updated = db.vulnerabilities.get(vuln.id)
        assert updated is not None
        assert updated.status == "in_progress"

    def test_ignores_a_vulnerability_below_the_threshold(self, db, github, repo):
        a_vuln(db, repo, severity="low")
        run = a_run(db, repo)

        assert steps(db, github).advance(run).state == "NOTHING_TO_DO"

    def test_ignores_a_vulnerability_with_no_fix_available(self, db, github, repo):
        a_vuln(db, repo, fixed_version=None)
        run = a_run(db, repo)

        assert steps(db, github).advance(run).state == "NOTHING_TO_DO"

    def test_ignores_an_advisory_the_config_lists_as_ignored(self, db, github, repo):
        db.repos.update(
            repo.id,
            {
                "config_json": (
                    "version: 1\nagent:\n  severity_threshold: medium\n  ignore:\n"
                    "    - id: GHSA-a\n      reason: accepted\n"
                )
            },
        )
        a_vuln(db, repo)
        reloaded = db.repos.get(repo.id)
        assert reloaded is not None
        run = a_run(db, repo)

        assert steps(db, github).advance(run).state == "NOTHING_TO_DO"

    def test_a_run_with_nothing_to_do_puts_the_repository_back_to_sleep(self, db, github, repo):
        db.repos.start_run(repo.id, "run1")
        run = a_run(db, repo)

        steps(db, github).advance(run)

        updated = db.repos.get(repo.id)
        assert updated is not None
        assert (updated.agent_state, updated.active_run_id) == ("idle", None)

    def test_caps_the_retry_budget_at_the_hard_ceiling(self, db, github, repo):
        db.repos.update(
            repo.id, {"config_json": "version: 1\nagent:\n  severity_threshold: medium\n"}
        )
        a_vuln(db, repo)
        run = a_run(db, repo)

        steps(db, github).advance(run)

        updated = db.runs.get(run.id)
        assert updated is not None
        assert updated.max_attempts == 3


class TestPlanning:
    def test_produces_a_plan_and_moves_to_patching(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(db, repo, state="PLANNING", vuln_ids=[vuln.id])

        outcome = steps(db, github).advance(run)

        assert outcome.state == "PATCHING"
        updated = db.runs.get(run.id)
        assert updated is not None
        assert "bump_direct" in updated.plan_json

    def test_records_the_commit_the_plan_was_built_against(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(db, repo, state="PLANNING", vuln_ids=[vuln.id])

        steps(db, github).advance(run)

        updated = db.runs.get(run.id)
        assert updated is not None
        assert updated.base_sha == "base1"

    def test_a_plan_with_nothing_in_it_ends_the_run(self, db, github, repo):
        vuln = a_vuln(db, repo, fixed_version="4.17.19")  # older than installed
        run = a_run(db, repo, state="PLANNING", vuln_ids=[vuln.id])

        assert steps(db, github).advance(run).state == "NOTHING_TO_DO"

    def test_marks_a_vulnerability_that_needs_a_major_bump(self, db, github, repo):
        vuln = a_vuln(db, repo, fixed_version="5.0.0")
        run = a_run(db, repo, state="PLANNING", vuln_ids=[vuln.id])

        steps(db, github).advance(run)

        updated = db.vulnerabilities.get(vuln.id)
        assert updated is not None
        assert updated.status == "needs_major"


class TestPatching:
    def plan_for(self, vuln_id: str) -> str:
        return UpgradePlan.model_validate(
            {
                "ecosystem": "npm",
                "actions": [
                    {
                        "kind": "bump_direct",
                        "name": "lodash",
                        "from_version": "4.17.20",
                        "to_version": "4.17.21",
                        "manifest_path": "package.json",
                    }
                ],
                "resolves": ["GHSA-a"],
            }
        ).model_dump_json()

    def test_commits_the_patched_files_to_the_agents_own_branch(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(
            db,
            repo,
            state="PATCHING",
            vuln_ids=[vuln.id],
            plan_json=self.plan_for(vuln.id),
            base_sha="base1",
        )

        outcome = steps(db, github).advance(run)

        assert outcome.state == "PR_OPEN"
        assert github.commits[0]["branch"] == f"vulnagent/{run.id}"

    def test_the_commit_contains_both_the_manifest_and_the_lockfile(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(
            db, repo, state="PATCHING", vuln_ids=[vuln.id], plan_json=self.plan_for(vuln.id)
        )

        steps(db, github).advance(run)

        assert set(github.commits[0]["files"]) == {"package.json", "package-lock.json"}

    def test_the_commit_message_is_tagged_for_the_agent(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(
            db, repo, state="PATCHING", vuln_ids=[vuln.id], plan_json=self.plan_for(vuln.id)
        )

        steps(db, github).advance(run)

        assert github.commits[0]["message"].endswith("[vulnagent]")


class TestOpeningThePullRequest:
    def test_opens_and_labels_the_pull_request(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(
            db,
            repo,
            state="PR_OPEN",
            vuln_ids=[vuln.id],
            branch="vulnagent/run1",
            plan_json=UpgradePlan(ecosystem="npm", resolves=["GHSA-a"]).model_dump_json(),
        )

        outcome = steps(db, github).advance(run)

        assert outcome.state == "AWAITING_CI"
        assert "vulnagent" in github.labels

    def test_records_the_pull_request_so_webhooks_can_find_the_run(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(
            db,
            repo,
            state="PR_OPEN",
            vuln_ids=[vuln.id],
            branch="vulnagent/run1",
            plan_json=UpgradePlan(ecosystem="npm").model_dump_json(),
        )

        steps(db, github).advance(run)

        updated = db.runs.get(run.id)
        assert updated is not None
        assert updated.pr_number == 7

    def test_waiting_for_ci_does_not_reschedule_the_agent(self, db, github, repo):
        vuln = a_vuln(db, repo)
        run = a_run(
            db,
            repo,
            state="PR_OPEN",
            vuln_ids=[vuln.id],
            branch="vulnagent/run1",
            plan_json=UpgradePlan(ecosystem="npm").model_dump_json(),
        )

        assert steps(db, github).advance(run).reschedule is False


class TestTheRepairLoop:
    def repairing_run(self, db, repo, **overrides) -> AgentRun:
        vuln = a_vuln(db, repo)
        return a_run(
            db,
            repo,
            **{
                "state": "REPAIRING",
                "vuln_ids": [vuln.id],
                "branch": "vulnagent/run1",
                "head_sha": "sha1",
                "pr_number": 7,
                "plan_json": UpgradePlan(ecosystem="npm").model_dump_json(),
                **overrides,
            },
        )

    GOOD_REPAIR = (
        '{"analysis": "jsonwebtoken 9 returns a promise.", '
        '"edits": [{"path": "src/auth.ts", "search": "jwt.sign(p)", '
        '"replace": "await jwt.sign(p)"}], "confidence": 0.9, "give_up": false}'
    )

    def test_applies_a_safe_repair_and_waits_for_ci_again(self, db, github, repo):
        run = self.repairing_run(db, repo)

        outcome = steps(db, github, llm=FakeLLM(self.GOOD_REPAIR)).advance(run)

        assert outcome.state == "AWAITING_CI"
        assert "await jwt.sign(p)" in github.commits[0]["files"]["src/auth.ts"]

    def test_the_repair_counts_as_an_attempt(self, db, github, repo):
        run = self.repairing_run(db, repo)

        steps(db, github, llm=FakeLLM(self.GOOD_REPAIR)).advance(run)

        updated = db.runs.get(run.id)
        assert updated is not None
        assert updated.attempt == 1

    def test_a_past_fix_is_offered_to_the_model_and_logged(self, db, github, repo):
        run = self.repairing_run(db, repo)
        memory = FakeMemory(
            [
                Hit(
                    record=FailureRecord(
                        ecosystem="npm",
                        error_signature="TypeError jwt.sign",
                        package_changes="jsonwebtoken 8.5.1->9.0.2",
                        fix_diff="+ await jwt.sign(p)",
                    ),
                    score=0.93,
                )
            ]
        )
        llm = FakeLLM(self.GOOD_REPAIR)

        steps(db, github, llm=llm, memory=memory).advance(run)

        assert "await jwt.sign(p)" in llm.prompts[0]
        assert any(event.type == "memory_hit" for event in db.events.for_run(run.id))

    def test_refuses_a_patch_that_would_disable_a_test(self, db, github, repo):
        run = self.repairing_run(db, repo)
        unsafe = (
            '{"analysis": "skip it", "edits": [{"path": "src/auth.ts", '
            '"search": "const t = jwt.sign(p)", "replace": "it.skip(\'x\', () => {})"}]}'
        )

        outcome = steps(db, github, llm=FakeLLM(unsafe)).advance(run)

        assert outcome.state == "GAVE_UP"
        assert github.commits == []

    def test_refuses_a_patch_that_edits_the_manifest(self, db, github, repo):
        run = self.repairing_run(db, repo)
        unsafe = (
            '{"analysis": "downgrade", "edits": [{"path": "package.json", '
            '"search": "4.17.21", "replace": "4.17.20"}]}'
        )

        assert steps(db, github, llm=FakeLLM(unsafe)).advance(run).state == "GAVE_UP"

    def test_a_model_that_gives_up_ends_the_run(self, db, github, repo):
        run = self.repairing_run(db, repo)
        giving_up = (
            '{"analysis": "unrelated", "edits": [], "give_up": true, '
            '"give_up_reason": "the test was already failing"}'
        )

        outcome = steps(db, github, llm=FakeLLM(giving_up)).advance(run)

        assert outcome.state == "GAVE_UP"

    def test_asks_again_when_the_first_response_is_unparseable(self, db, github, repo):
        run = self.repairing_run(db, repo)
        llm = FakeLLM("sorry, I cannot help", self.GOOD_REPAIR)

        outcome = steps(db, github, llm=llm).advance(run)

        assert outcome.state == "AWAITING_CI"
        assert len(llm.prompts) == 2

    def test_gives_up_when_the_model_cannot_produce_valid_json_twice(self, db, github, repo):
        run = self.repairing_run(db, repo)

        outcome = steps(db, github, llm=FakeLLM("nope", "still nope")).advance(run)

        assert outcome.state == "GAVE_UP"

    def test_gives_up_when_there_is_no_llm_configured(self, db, github, repo):
        run = self.repairing_run(db, repo)

        assert steps(db, github).advance(run).state == "GAVE_UP"

    def test_giving_up_asks_for_a_human_and_releases_the_vulnerabilities(self, db, github, repo):
        run = self.repairing_run(db, repo)

        steps(db, github, llm=FakeLLM('{"analysis": "x", "edits": [], "give_up": true}')).advance(
            run
        )

        assert "vulnagent:needs-human" in github.labels
        assert github.comments
        [vuln] = db.vulnerabilities.for_repo(repo.id)
        assert vuln.status == "open"


class TestMerging:
    def test_marks_the_vulnerabilities_fixed(self, db, github, repo):
        vuln = a_vuln(db, repo, status="in_progress")
        run = a_run(db, repo, state="MERGED", vuln_ids=[vuln.id])

        outcome = steps(db, github).advance(run)

        assert outcome.state == "COMPLETED"
        updated = db.vulnerabilities.get(vuln.id)
        assert updated is not None
        assert updated.status == "fixed"
        assert updated.resolved_by_run_id == run.id

    def test_the_counts_drop_once_the_vulnerabilities_are_fixed(self, db, github, repo):
        vuln = a_vuln(db, repo, status="in_progress")
        db.repos.set_counts(
            repo.id, {"critical": 0, "high": 1, "medium": 0, "low": 0, "unknown": 0}
        )
        run = a_run(db, repo, state="MERGED", vuln_ids=[vuln.id])

        steps(db, github).advance(run)

        updated = db.repos.get(repo.id)
        assert updated is not None
        assert updated.open_high == 0

    def test_the_repository_goes_back_to_sleep(self, db, github, repo):
        vuln = a_vuln(db, repo, status="in_progress")
        db.repos.start_run(repo.id, "run1")
        run = a_run(db, repo, state="MERGED", vuln_ids=[vuln.id])

        steps(db, github).advance(run)

        updated = db.repos.get(repo.id)
        assert updated is not None
        assert (updated.agent_state, updated.active_run_id) == ("idle", None)

    def test_a_repaired_run_writes_what_worked_into_memory(self, db, github, repo):
        vuln = a_vuln(db, repo, status="in_progress")
        memory = FakeMemory()
        run = a_run(db, repo, state="MERGED", vuln_ids=[vuln.id], attempt=1)

        steps(db, github, memory=memory).advance(run)

        assert [record.outcome for record in memory.added] == ["success"]

    def test_a_run_that_never_needed_a_repair_writes_no_memory(self, db, github, repo):
        vuln = a_vuln(db, repo, status="in_progress")
        memory = FakeMemory()
        run = a_run(db, repo, state="MERGED", vuln_ids=[vuln.id], attempt=0)

        steps(db, github, memory=memory).advance(run)

        assert memory.added == []


class TestInterruptions:
    def test_a_closed_pull_request_cancels_the_run(self, db, github, repo):
        vuln = a_vuln(db, repo, status="in_progress")
        run = a_run(db, repo, state="AWAITING_CI", vuln_ids=[vuln.id])

        outcome = steps(db, github).advance(run, event="pr_closed")

        assert outcome.state == "CANCELLED"

    def test_cancelling_puts_the_vulnerabilities_back(self, db, github, repo):
        vuln = a_vuln(db, repo, status="in_progress")
        run = a_run(db, repo, state="AWAITING_CI", vuln_ids=[vuln.id])

        steps(db, github).advance(run, event="pr_closed")

        updated = db.vulnerabilities.get(vuln.id)
        assert updated is not None
        assert updated.status == "open"

    def test_a_ci_failure_past_the_budget_gives_up(self, db, github, repo):
        run = a_run(db, repo, state="AWAITING_CI", attempt=3, max_attempts=3)

        assert steps(db, github).advance(run, event="ci_failed").state == "GAVE_UP"

    def test_a_ci_failure_within_the_budget_goes_to_repair(self, db, github, repo):
        run = a_run(db, repo, state="AWAITING_CI", attempt=0, max_attempts=3)

        assert steps(db, github).advance(run, event="ci_failed").state == "REPAIRING"

    def test_every_transition_is_recorded_on_the_timeline(self, db, github, repo):
        run = a_run(db, repo, state="AWAITING_CI")

        steps(db, github).advance(run, event="ci_passed")

        assert [event.type for event in db.events.for_run(run.id)] == ["state_change"]


class TestAutoMerge:
    def test_merges_when_the_repository_asked_for_it(self, db, github, repo):
        db.repos.update(repo.id, {"config_json": "version: 1\nagent:\n  auto_merge: true\n"})
        reloaded = db.repos.get(repo.id)
        assert reloaded is not None
        run = a_run(db, repo, state="READY_TO_MERGE", pr_number=7)

        steps(db, github).advance(run)

        assert github.merged == [7]

    def test_otherwise_asks_for_a_review(self, db, github, repo):
        run = a_run(db, repo, state="READY_TO_MERGE", pr_number=7)

        steps(db, github).advance(run)

        assert github.merged == []
        assert "Ready for review" in github.comments[0]
