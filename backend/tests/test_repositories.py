import datetime as dt

import pytest

from tests.fakes import FakeTablesDB
from vulnagent.db.repositories import Database
from vulnagent.db.rows import AgentRun, Installation, Repo, Vulnerability

NOW = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def tables():
    return FakeTablesDB()


@pytest.fixture
def db(tables):
    return Database(tables)


def a_repo(**overrides) -> Repo:
    return Repo(
        **{
            "installation_id": "inst1",
            "github_repo_id": 12345,
            "full_name": "pranav/test-app",
            "owner_user_id": "user1",
            **overrides,
        }
    )


def a_vuln(**overrides) -> Vulnerability:
    return Vulnerability(
        **{
            "repo_id": "repo1",
            "osv_id": "GHSA-a",
            "purl": "pkg:npm/lodash@4.17.20",
            "package_name": "lodash",
            "installed_version": "4.17.20",
            "severity": "high",
            **overrides,
        }
    )


class TestRoundTripping:
    def test_a_created_row_comes_back_with_its_id(self, db):
        created = db.repos.create(a_repo())

        assert created.id
        assert db.repos.get(created.id) == created

    def test_appwrite_system_fields_do_not_leak_into_the_model(self, db, tables):
        created = db.repos.create(a_repo())
        tables.tables["repos"][created.id]["$sequence"] = "7"

        fetched = db.repos.get(created.id)

        assert fetched is not None
        assert not hasattr(fetched, "sequence")

    def test_a_missing_row_reads_as_nothing(self, db):
        assert db.repos.get("nope") is None

    def test_datetimes_survive_the_round_trip(self, db):
        created = db.repos.create(a_repo(next_scan_at=NOW))

        fetched = db.repos.get(created.id)

        assert fetched is not None
        assert fetched.next_scan_at == NOW

    def test_a_list_column_survives_the_round_trip(self, db):
        created = db.repos.create(a_repo(ecosystems=["npm"]))

        fetched = db.repos.get(created.id)

        assert fetched is not None
        assert fetched.ecosystems == ["npm"]


class TestFindingRepos:
    def test_finds_a_repo_by_its_github_id(self, db):
        db.repos.create(a_repo(github_repo_id=1))
        db.repos.create(a_repo(github_repo_id=2, full_name="pranav/other"))

        found = db.repos.by_github_id(2)

        assert found is not None
        assert found.full_name == "pranav/other"

    def test_finds_a_repo_by_full_name(self, db):
        db.repos.create(a_repo())

        found = db.repos.by_full_name("pranav/test-app")

        assert found is not None

    def test_lists_only_the_repos_a_user_owns(self, db):
        db.repos.create(a_repo(owner_user_id="user1"))
        db.repos.create(a_repo(github_repo_id=2, full_name="other/repo", owner_user_id="user2"))

        found = db.repos.for_owner("user1")

        assert [repo.full_name for repo in found] == ["pranav/test-app"]

    def test_finds_repos_whose_next_scan_is_due(self, db):
        db.repos.create(a_repo(next_scan_at=NOW - dt.timedelta(hours=1)))
        db.repos.create(
            a_repo(github_repo_id=2, full_name="b/b", next_scan_at=NOW + dt.timedelta(hours=1))
        )

        due = db.repos.due_for_scan(NOW)

        assert [repo.full_name for repo in due] == ["pranav/test-app"]

    def test_a_repo_with_no_schedule_is_never_due(self, db):
        db.repos.create(a_repo(next_scan_at=None))

        assert db.repos.due_for_scan(NOW) == []

    def test_a_repo_already_working_is_not_picked_up_by_the_scheduler(self, db):
        db.repos.create(a_repo(next_scan_at=NOW - dt.timedelta(hours=1), agent_state="working"))

        assert db.repos.due_for_scan(NOW) == []


class TestAgentLifecycle:
    def test_starting_a_run_marks_the_repo_as_working(self, db):
        repo = db.repos.create(a_repo())

        db.repos.start_run(repo.id, "run1")

        updated = db.repos.get(repo.id)
        assert updated is not None
        assert (updated.active_run_id, updated.agent_state) == ("run1", "working")

    def test_going_to_sleep_releases_the_repo(self, db):
        repo = db.repos.create(a_repo(active_run_id="run1", agent_state="working"))

        db.repos.go_to_sleep(repo.id)

        updated = db.repos.get(repo.id)
        assert updated is not None
        assert updated.active_run_id is None
        assert updated.agent_state == "idle"

    def test_an_errored_run_leaves_the_repo_in_the_error_state(self, db):
        repo = db.repos.create(a_repo(agent_state="working"))

        db.repos.go_to_sleep(repo.id, errored=True)

        updated = db.repos.get(repo.id)
        assert updated is not None
        assert updated.agent_state == "error"

    def test_saving_a_state_also_moves_the_updated_timestamp(self, db):
        run = db.runs.create(AgentRun(repo_id="repo1"))

        db.runs.save_state(run.id, "PLANNING")

        updated = db.runs.get(run.id)
        assert updated is not None
        assert updated.state == "PLANNING"
        assert updated.updated_at >= run.updated_at

    def test_finds_the_run_behind_a_pull_request(self, db):
        db.runs.create(AgentRun(repo_id="repo1", pr_number=7))
        db.runs.create(AgentRun(repo_id="repo1", pr_number=8))

        found = db.runs.by_pr_number("repo1", 8)

        assert found is not None
        assert found.pr_number == 8

    def test_counts_are_written_back_per_severity(self, db):
        repo = db.repos.create(a_repo())

        db.repos.set_counts(
            repo.id, {"critical": 1, "high": 2, "medium": 0, "low": 0, "unknown": 0}
        )

        updated = db.repos.get(repo.id)
        assert updated is not None
        assert updated.counts() == {"critical": 1, "high": 2, "medium": 0, "low": 0, "unknown": 0}


class TestVulnerabilities:
    def test_lists_only_the_vulnerabilities_still_open(self, db):
        db.vulnerabilities.create(a_vuln(osv_id="GHSA-open", status="open"))
        db.vulnerabilities.create(a_vuln(osv_id="GHSA-working", status="in_progress"))
        db.vulnerabilities.create(a_vuln(osv_id="GHSA-done", status="fixed"))

        found = db.vulnerabilities.open_for_repo("repo1")

        assert {vuln.osv_id for vuln in found} == {"GHSA-open", "GHSA-working"}

    def test_marking_several_vulnerabilities_at_once(self, db):
        first = db.vulnerabilities.create(a_vuln(osv_id="GHSA-a"))
        second = db.vulnerabilities.create(a_vuln(osv_id="GHSA-b"))

        db.vulnerabilities.mark([first.id, second.id], "fixed", resolved_by_run_id="run1")

        fixed = db.vulnerabilities.find([])
        assert {vuln.status for vuln in fixed} == {"fixed"}
        assert {vuln.resolved_by_run_id for vuln in fixed} == {"run1"}


class TestWebhookDeduplication:
    def test_the_first_delivery_is_claimed(self, db):
        assert db.deliveries.claim("delivery-1", "push") is True

    def test_a_redelivery_is_refused(self, db):
        db.deliveries.claim("delivery-1", "push")

        assert db.deliveries.claim("delivery-1", "push") is False

    def test_different_deliveries_are_both_claimed(self, db):
        assert db.deliveries.claim("delivery-1", "push") is True
        assert db.deliveries.claim("delivery-2", "push") is True

    def test_a_github_delivery_uuid_becomes_a_usable_row_id(self, db, tables):
        db.deliveries.claim("72d3162e-cc78-11e3-81ab-4c9367dc0958", "push")

        [row_id] = list(tables.tables["webhook_deliveries"])
        assert len(row_id) <= 36
        assert all(character.isalnum() or character == "-" for character in row_id)


class TestPaging:
    def test_reads_past_the_first_page(self, db):
        for index in range(250):
            db.vulnerabilities.create(a_vuln(osv_id=f"GHSA-{index}"))

        assert len(db.vulnerabilities.for_repo("repo1")) == 250


class TestInstallations:
    def test_finds_an_installation_by_its_github_id(self, db):
        db.installations.create(Installation(github_installation_id=99, account_login="pranav"))

        found = db.installations.by_github_id(99)

        assert found is not None
        assert found.account_login == "pranav"
