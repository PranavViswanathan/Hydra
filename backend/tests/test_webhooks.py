import pytest

from vulnagent.github.webhooks import (
    Delivery,
    read_ci_completed,
    read_installation_change,
    read_pull_request_closed,
    read_push,
    route,
)

REPO = {"full_name": "pranav/test-app", "default_branch": "main", "id": 12345}
INSTALLATION = {"id": 99, "account": {"login": "pranav", "type": "User"}}


def delivery(event: str, payload: dict, delivery_id: str = "d1") -> Delivery:
    return Delivery(delivery_id=delivery_id, event=event, payload=payload)


class TestRouting:
    @pytest.mark.parametrize("event", ["installation", "installation_repositories"])
    def test_installation_events_go_to_the_installation_handler(self, event):
        assert route(delivery(event, {"action": "created", **INSTALLATION})) == (
            "installation_changed"
        )

    def test_a_push_to_the_default_branch_is_handled(self):
        payload = {"ref": "refs/heads/main", "repository": REPO, "commits": []}

        assert route(delivery("push", payload)) == "push_to_default_branch"

    def test_a_push_to_any_other_branch_is_ignored(self):
        payload = {"ref": "refs/heads/feature", "repository": REPO, "commits": []}

        assert route(delivery("push", payload)) == "ignored"

    def test_a_push_to_a_tag_is_ignored(self):
        payload = {"ref": "refs/tags/v1.0.0", "repository": REPO, "commits": []}

        assert route(delivery("push", payload)) == "ignored"

    def test_a_finished_workflow_run_is_handled(self):
        payload = {
            "action": "completed",
            "repository": REPO,
            "workflow_run": {"head_sha": "abc", "conclusion": "failure"},
        }

        assert route(delivery("workflow_run", payload)) == "ci_completed"

    def test_a_workflow_run_that_only_started_is_ignored(self):
        payload = {"action": "requested", "repository": REPO, "workflow_run": {"head_sha": "abc"}}

        assert route(delivery("workflow_run", payload)) == "ignored"

    def test_a_finished_check_suite_is_handled(self):
        payload = {
            "action": "completed",
            "repository": REPO,
            "check_suite": {"head_sha": "abc", "conclusion": "success"},
        }

        assert route(delivery("check_suite", payload)) == "ci_completed"

    def test_a_closed_pull_request_is_handled(self):
        payload = {"action": "closed", "repository": REPO, "pull_request": {"number": 7}}

        assert route(delivery("pull_request", payload)) == "pull_request_closed"

    def test_an_opened_pull_request_is_ignored(self):
        payload = {"action": "opened", "repository": REPO, "pull_request": {"number": 7}}

        assert route(delivery("pull_request", payload)) == "ignored"

    def test_an_event_the_agent_does_not_subscribe_to_is_ignored(self):
        assert route(delivery("star", {"action": "created"})) == "ignored"


class TestInstallationChanges:
    def test_reads_the_account_the_app_was_installed_on(self):
        change = read_installation_change({"action": "created", "installation": INSTALLATION})

        assert (change.installation_id, change.account_login) == (99, "pranav")
        assert change.account_type == "User"

    def test_reads_the_repositories_the_installation_covers(self):
        change = read_installation_change(
            {"action": "created", "installation": INSTALLATION, "repositories": [REPO]}
        )

        assert change.repositories[0]["full_name"] == "pranav/test-app"

    def test_reads_repositories_added_to_an_existing_installation(self):
        change = read_installation_change(
            {"action": "added", "installation": INSTALLATION, "repositories_added": [REPO]}
        )

        assert len(change.repositories) == 1

    def test_notices_a_suspended_installation(self):
        change = read_installation_change(
            {"action": "suspend", "installation": {**INSTALLATION, "suspended_at": "2026-01-01"}}
        )

        assert change.suspended is True

    def test_notices_a_deleted_installation(self):
        change = read_installation_change({"action": "deleted", "installation": INSTALLATION})

        assert change.removed is True


class TestPushes:
    def test_collects_every_path_touched_by_the_push(self):
        payload = {
            "ref": "refs/heads/main",
            "after": "sha2",
            "repository": REPO,
            "installation": INSTALLATION,
            "commits": [
                {"added": ["src/new.ts"], "modified": ["package.json"], "removed": []},
                {"added": [], "modified": ["package-lock.json"], "removed": ["src/old.ts"]},
            ],
        }

        push = read_push(payload)

        assert push.changed_paths == [
            "package-lock.json",
            "package.json",
            "src/new.ts",
            "src/old.ts",
        ]

    def test_reads_the_commit_the_branch_now_points_at(self):
        payload = {"ref": "refs/heads/main", "after": "sha2", "repository": REPO, "commits": []}

        assert read_push(payload).after_sha == "sha2"

    def test_lists_a_path_once_even_if_several_commits_touched_it(self):
        payload = {
            "ref": "refs/heads/main",
            "repository": REPO,
            "commits": [{"modified": ["package.json"]}, {"modified": ["package.json"]}],
        }

        assert read_push(payload).changed_paths == ["package.json"]


class TestCiResults:
    def test_reads_a_failing_run(self):
        payload = {
            "action": "completed",
            "repository": REPO,
            "installation": INSTALLATION,
            "workflow_run": {"head_sha": "abc", "conclusion": "failure"},
        }

        result = read_ci_completed(delivery("workflow_run", payload))

        assert (result.head_sha, result.passed) == ("abc", False)

    def test_reads_a_passing_run(self):
        payload = {
            "action": "completed",
            "repository": REPO,
            "workflow_run": {"head_sha": "abc", "conclusion": "success"},
        }

        assert read_ci_completed(delivery("workflow_run", payload)).passed is True

    def test_a_skipped_run_counts_as_passing(self):
        payload = {
            "action": "completed",
            "repository": REPO,
            "check_suite": {"head_sha": "abc", "conclusion": "skipped"},
        }

        assert read_ci_completed(delivery("check_suite", payload)).passed is True

    def test_a_cancelled_run_does_not_count_as_passing(self):
        payload = {
            "action": "completed",
            "repository": REPO,
            "workflow_run": {"head_sha": "abc", "conclusion": "cancelled"},
        }

        assert read_ci_completed(delivery("workflow_run", payload)).passed is False


class TestClosedPullRequests:
    def test_a_merged_pull_request_is_reported_as_merged(self):
        payload = {
            "action": "closed",
            "repository": REPO,
            "installation": INSTALLATION,
            "pull_request": {"number": 7, "merged": True, "head": {"ref": "vulnagent/run-1"}},
        }

        closed = read_pull_request_closed(payload)

        assert (closed.number, closed.merged) == (7, True)
        assert closed.head_branch == "vulnagent/run-1"

    def test_a_pull_request_closed_without_merging_is_not_merged(self):
        payload = {
            "action": "closed",
            "repository": REPO,
            "pull_request": {"number": 7, "merged": False, "head": {"ref": "vulnagent/run-1"}},
        }

        assert read_pull_request_closed(payload).merged is False
