import datetime as dt

import httpx
import pytest
import respx

from tests.fakes import FakeTablesDB
from vulnagent.db.repositories import Database
from vulnagent.db.rows import AgentRun, Installation, Repo
from vulnagent.github.webhooks import (
    CiCompleted,
    InstallationChange,
    PullRequestClosed,
    PushToDefaultBranch,
)
from vulnagent.services.installations import apply_installation_change, reload_config
from vulnagent.services.linking import link_installation
from vulnagent.services.triggers import (
    next_scan_time,
    should_start_agent,
    start_scan,
    touches_a_manifest,
    wake_agent_for_ci,
    wake_agent_for_closed_pr,
)

NOW = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.UTC)
API = "https://api.github.com"


class FakeGitHub:
    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = files or {}

    def get_file(self, repo, path, ref):
        return self.files.get(path)


class FakeApp:
    """Stands in for the runtime Context: a database plus an execution queue."""

    def __init__(self, github: FakeGitHub | None = None) -> None:
        self.tables = FakeTablesDB()
        self.db = Database(self.tables)
        self.queued: list[tuple[str, dict]] = []
        self._github = github or FakeGitHub()
        self.http = httpx.Client()

    def enqueue(self, task, payload):
        self.queued.append((task, payload))

    def github_for(self, installation_id):
        return self._github


@pytest.fixture
def app():
    instance = FakeApp()
    yield instance
    instance.http.close()


def a_repo(app, **overrides) -> Repo:
    return app.db.repos.create(
        Repo(
            **{
                "installation_id": "inst1",
                "github_repo_id": 1,
                "full_name": "pranav/test-app",
                "config_json": "version: 1\n",
                **overrides,
            }
        )
    )


class TestManifestDetection:
    @pytest.mark.parametrize("path", ["package.json", "package-lock.json"])
    def test_recognises_a_dependency_file(self, path):
        assert touches_a_manifest([path]) is True

    def test_ordinary_source_changes_do_not_count(self):
        assert touches_a_manifest(["src/index.ts", "README.md"]) is False

    def test_a_vendored_manifest_does_not_count(self):
        assert touches_a_manifest(["node_modules/lodash/package.json"]) is False

    def test_one_manifest_among_many_files_is_enough(self):
        assert touches_a_manifest(["src/a.ts", "package-lock.json"]) is True


class TestScheduling:
    def test_reads_the_next_run_from_the_cron_expression(self, app):
        repo = a_repo(app, config_json='version: 1\nscan:\n  schedule: "0 6 * * *"\n')

        following = next_scan_time(repo, NOW)

        assert following == dt.datetime(2026, 10, 22, 6, 0, tzinfo=dt.UTC)

    def test_a_repository_with_no_schedule_is_never_due_again(self, app):
        repo = a_repo(app, config_json="version: 1\nscan:\n  schedule: null\n")

        assert next_scan_time(repo, NOW) is None


class TestStartingTheAgentAfterAScan:
    def test_starts_when_a_new_vulnerability_clears_the_threshold(self, app):
        repo = a_repo(app, config_json="version: 1\nagent:\n  severity_threshold: high\n")

        assert should_start_agent(repo, new_vulns=1, worst_severity="critical") is True

    def test_does_not_start_for_something_below_the_threshold(self, app):
        repo = a_repo(app, config_json="version: 1\nagent:\n  severity_threshold: high\n")

        assert should_start_agent(repo, new_vulns=1, worst_severity="low") is False

    def test_does_not_start_when_nothing_is_new(self, app):
        repo = a_repo(app)

        assert should_start_agent(repo, new_vulns=0, worst_severity="critical") is False

    def test_does_not_start_a_second_run_on_the_same_repository(self, app):
        repo = a_repo(app, active_run_id="run1")

        assert should_start_agent(repo, new_vulns=1, worst_severity="critical") is False

    def test_respects_auto_start_being_switched_off(self, app):
        repo = a_repo(app, config_json="version: 1\nagent:\n  auto_start: false\n")

        assert should_start_agent(repo, new_vulns=1, worst_severity="critical") is False

    def test_respects_the_agent_being_disabled_entirely(self, app):
        repo = a_repo(app, config_json="version: 1\nenabled: false\n")

        assert should_start_agent(repo, new_vulns=1, worst_severity="critical") is False


class TestPushTriggers:
    def push(self, paths, full_name="pranav/test-app") -> PushToDefaultBranch:
        return PushToDefaultBranch(
            repo_full_name=full_name,
            installation_id=99,
            after_sha="sha2",
            changed_paths=paths,
        )

    def test_a_manifest_change_queues_a_scan(self, app):
        a_repo(app)

        assert start_scan(app, self.push(["package.json"])) is True
        assert app.queued[0][1]["trigger"] == "push"

    def test_the_scan_is_queued_as_a_scan_task(self, app):
        a_repo(app)

        start_scan(app, self.push(["package.json"]))

        assert app.queued[0][0] == "scan"

    def test_a_source_only_push_queues_nothing(self, app):
        a_repo(app)

        assert start_scan(app, self.push(["src/index.ts"])) is False
        assert app.queued == []

    def test_a_repository_that_switched_off_push_scans_is_left_alone(self, app):
        a_repo(app, config_json="version: 1\nscan:\n  on_push: false\n")

        assert start_scan(app, self.push(["package.json"])) is False

    def test_a_push_to_an_unknown_repository_is_ignored(self, app):
        assert start_scan(app, self.push(["package.json"], "someone/else")) is False


class TestCiTriggers:
    def ci(self, sha="sha1", conclusion="failure") -> CiCompleted:
        return CiCompleted(
            repo_full_name="pranav/test-app",
            installation_id=99,
            head_sha=sha,
            conclusion=conclusion,
        )

    def test_a_failure_on_the_commit_the_run_pushed_wakes_the_agent(self, app):
        repo = a_repo(app)
        run = app.db.runs.create(AgentRun(repo_id=repo.id, state="AWAITING_CI", head_sha="sha1"))
        app.db.repos.start_run(repo.id, run.id)

        assert wake_agent_for_ci(app, self.ci()) is True
        assert app.queued[0][1]["event"] == "ci_failed"

    def test_waking_the_agent_queues_an_agent_step_task(self, app):
        repo = a_repo(app)
        run = app.db.runs.create(AgentRun(repo_id=repo.id, state="AWAITING_CI", head_sha="sha1"))
        app.db.repos.start_run(repo.id, run.id)

        wake_agent_for_ci(app, self.ci())

        assert app.queued[0][0] == "agent_step"

    def test_a_pass_wakes_the_agent_with_the_other_event(self, app):
        repo = a_repo(app)
        run = app.db.runs.create(AgentRun(repo_id=repo.id, state="AWAITING_CI", head_sha="sha1"))
        app.db.repos.start_run(repo.id, run.id)

        wake_agent_for_ci(app, self.ci(conclusion="success"))

        assert app.queued[0][1]["event"] == "ci_passed"

    def test_ci_for_a_different_commit_is_ignored(self, app):
        repo = a_repo(app)
        run = app.db.runs.create(AgentRun(repo_id=repo.id, state="AWAITING_CI", head_sha="sha1"))
        app.db.repos.start_run(repo.id, run.id)

        assert wake_agent_for_ci(app, self.ci(sha="someone-elses-sha")) is False

    def test_ci_for_a_repository_with_no_active_run_is_ignored(self, app):
        a_repo(app)

        assert wake_agent_for_ci(app, self.ci()) is False

    def test_ci_arriving_while_the_run_is_elsewhere_is_ignored(self, app):
        repo = a_repo(app)
        run = app.db.runs.create(AgentRun(repo_id=repo.id, state="REPAIRING", head_sha="sha1"))
        app.db.repos.start_run(repo.id, run.id)

        assert wake_agent_for_ci(app, self.ci()) is False


class TestPullRequestClosed:
    def test_a_merge_wakes_the_run_behind_the_pull_request(self, app):
        repo = a_repo(app)
        app.db.runs.create(AgentRun(repo_id=repo.id, state="READY_TO_MERGE", pr_number=7))

        closed = PullRequestClosed(
            repo_full_name="pranav/test-app",
            installation_id=99,
            number=7,
            merged=True,
            head_branch="vulnagent/run1",
        )

        assert wake_agent_for_closed_pr(app, closed) is True
        assert app.queued[0][1]["event"] == "pr_merged"

    def test_closing_without_merging_cancels_instead(self, app):
        repo = a_repo(app)
        app.db.runs.create(AgentRun(repo_id=repo.id, state="AWAITING_CI", pr_number=7))

        closed = PullRequestClosed(
            repo_full_name="pranav/test-app",
            installation_id=99,
            number=7,
            merged=False,
            head_branch="vulnagent/run1",
        )

        wake_agent_for_closed_pr(app, closed)

        assert app.queued[0][1]["event"] == "pr_closed"

    def test_a_pull_request_the_agent_did_not_open_is_ignored(self, app):
        a_repo(app)

        closed = PullRequestClosed(
            repo_full_name="pranav/test-app",
            installation_id=99,
            number=99,
            merged=True,
            head_branch="someone-else",
        )

        assert wake_agent_for_closed_pr(app, closed) is False


class TestInstallations:
    def change(self, **overrides) -> InstallationChange:
        return InstallationChange(
            **{
                "installation_id": 99,
                "account_login": "pranav",
                "account_type": "User",
                "suspended": False,
                "removed": False,
                "repositories": [
                    {"id": 1, "full_name": "pranav/test-app", "default_branch": "main"}
                ],
                **overrides,
            }
        )

    def test_records_the_installation_and_its_repositories(self):
        app = FakeApp(FakeGitHub({".vulnagent.yml": "version: 1\n"}))

        saved = apply_installation_change(app, self.change())

        assert [repo.full_name for repo in saved] == ["pranav/test-app"]
        assert app.db.installations.by_github_id(99) is not None

    def test_reads_the_repository_config_while_linking(self):
        app = FakeApp(FakeGitHub({".vulnagent.yml": "version: 1\nagent:\n  auto_merge: true\n"}))

        [repo] = apply_installation_change(app, self.change())

        assert repo.has_config is True
        assert "auto_merge" in repo.config_json

    def test_an_unconfigured_repository_is_recorded_as_such(self):
        app = FakeApp(FakeGitHub({}))

        [repo] = apply_installation_change(app, self.change())

        assert repo.has_config is False
        assert repo.config_error is None

    def test_an_invalid_config_is_stored_as_an_error_for_the_dashboard(self):
        app = FakeApp(FakeGitHub({".vulnagent.yml": "version: 1\nenabeld: false\n"}))

        [repo] = apply_installation_change(app, self.change())

        assert repo.config_error is not None
        assert "enabeld" in repo.config_error

    def test_installing_twice_does_not_duplicate_the_repository(self):
        app = FakeApp(FakeGitHub({".vulnagent.yml": "version: 1\n"}))

        apply_installation_change(app, self.change())
        apply_installation_change(app, self.change())

        assert len(app.db.repos.find([])) == 1

    def test_uninstalling_removes_the_installation_and_its_repositories(self):
        app = FakeApp(FakeGitHub({".vulnagent.yml": "version: 1\n"}))
        apply_installation_change(app, self.change())

        apply_installation_change(app, self.change(removed=True))

        assert app.db.installations.by_github_id(99) is None
        assert app.db.repos.find([]) == []

    def test_a_suspended_installation_is_flagged(self):
        app = FakeApp(FakeGitHub({}))

        apply_installation_change(app, self.change(suspended=True))

        installation = app.db.installations.by_github_id(99)
        assert installation is not None
        assert installation.suspended is True


class TestConfigReload:
    def test_rereads_the_config_when_the_push_touched_it(self):
        app = FakeApp(FakeGitHub({".vulnagent.yml": "version: 1\nagent:\n  auto_merge: true\n"}))
        a_repo(app)

        push = PushToDefaultBranch(
            repo_full_name="pranav/test-app",
            installation_id=99,
            after_sha="sha2",
            changed_paths=[".vulnagent.yml"],
        )

        assert reload_config(app, push) is True
        repo = app.db.repos.by_full_name("pranav/test-app")
        assert repo is not None
        assert "auto_merge" in repo.config_json

    def test_leaves_the_config_alone_when_the_push_did_not_touch_it(self):
        app = FakeApp(FakeGitHub({}))
        a_repo(app)

        push = PushToDefaultBranch(
            repo_full_name="pranav/test-app",
            installation_id=99,
            after_sha="sha2",
            changed_paths=["src/index.ts"],
        )

        assert reload_config(app, push) is False


class TestLinkingAnInstallationToAUser:
    @respx.mock
    def test_links_when_the_user_can_see_the_installation(self, app):
        respx.get(f"{API}/user/installations").mock(
            return_value=httpx.Response(200, json={"installations": [{"id": 99}]})
        )
        app.db.installations.create(Installation(github_installation_id=99, account_login="pranav"))
        a_repo(app, installation_id=app.db.installations.by_github_id(99).id)

        linked = link_installation(app, user_id="user1", installation_id=99, user_token="gho_x")

        assert linked is True
        repo = app.db.repos.by_full_name("pranav/test-app")
        assert repo is not None
        assert repo.owner_user_id == "user1"

    @respx.mock
    def test_refuses_an_installation_the_user_cannot_see(self, app):
        respx.get(f"{API}/user/installations").mock(
            return_value=httpx.Response(200, json={"installations": [{"id": 1}]})
        )
        app.db.installations.create(Installation(github_installation_id=99, account_login="pranav"))

        assert link_installation(app, user_id="user1", installation_id=99, user_token="x") is False

    @respx.mock
    def test_refuses_when_github_rejects_the_token(self, app):
        respx.get(f"{API}/user/installations").mock(return_value=httpx.Response(401))

        assert link_installation(app, user_id="user1", installation_id=99, user_token="x") is False

    def test_refuses_without_a_token(self, app):
        assert link_installation(app, user_id="user1", installation_id=99, user_token="") is False
