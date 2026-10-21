import pytest

from vulnagent.agent.state_machine import (
    AgentEvent,
    AgentState,
    InvalidTransitionError,
    is_terminal,
    next_state,
    runs_immediately,
)


def run(state: AgentState, attempt: int = 0, max_attempts: int = 3):
    from vulnagent.agent.state_machine import RunSnapshot

    return RunSnapshot(state=state, attempt=attempt, max_attempts=max_attempts)


class TestHappyPath:
    @pytest.mark.parametrize(
        ("state", "event", "expected"),
        [
            ("QUEUED", "vulnerabilities_selected", "PLANNING"),
            ("PLANNING", "plan_ready", "PATCHING"),
            ("PATCHING", "branch_pushed", "PR_OPEN"),
            ("PR_OPEN", "pr_opened", "AWAITING_CI"),
            ("AWAITING_CI", "ci_passed", "READY_TO_MERGE"),
            ("READY_TO_MERGE", "pr_merged", "MERGED"),
            ("MERGED", "cleanup_done", "COMPLETED"),
        ],
    )
    def test_walks_from_queued_through_to_completed(self, state, event, expected):
        assert next_state(run(state), event).to_state == expected

    def test_a_plan_with_nothing_to_do_ends_the_run_early(self):
        assert next_state(run("PLANNING"), "nothing_to_do").to_state == "NOTHING_TO_DO"

    def test_a_queued_run_with_no_eligible_vulnerabilities_ends_early(self):
        assert next_state(run("QUEUED"), "nothing_to_do").to_state == "NOTHING_TO_DO"


class TestCiRepairLoop:
    def test_a_first_failure_sends_the_run_to_repair(self):
        transition = next_state(run("AWAITING_CI", attempt=0, max_attempts=3), "ci_failed")

        assert transition.to_state == "REPAIRING"

    def test_a_repair_goes_back_to_waiting_for_ci(self):
        assert next_state(run("REPAIRING"), "patch_pushed").to_state == "AWAITING_CI"

    def test_each_repair_counts_as_an_attempt(self):
        transition = next_state(run("REPAIRING"), "patch_pushed")

        assert transition.attempt_delta == 1

    def test_waiting_for_ci_does_not_count_as_an_attempt(self):
        assert next_state(run("AWAITING_CI"), "ci_failed").attempt_delta == 0

    def test_the_last_allowed_attempt_still_repairs(self):
        transition = next_state(run("AWAITING_CI", attempt=2, max_attempts=3), "ci_failed")

        assert transition.to_state == "REPAIRING"

    def test_a_failure_past_the_attempt_limit_gives_up(self):
        transition = next_state(run("AWAITING_CI", attempt=3, max_attempts=3), "ci_failed")

        assert transition.to_state == "GAVE_UP"

    def test_a_repo_that_allows_no_retries_gives_up_on_the_first_failure(self):
        transition = next_state(run("AWAITING_CI", attempt=0, max_attempts=0), "ci_failed")

        assert transition.to_state == "GAVE_UP"

    def test_the_model_can_give_up_before_the_limit(self):
        assert next_state(run("REPAIRING"), "gave_up").to_state == "GAVE_UP"

    def test_a_repair_that_cannot_be_applied_safely_gives_up(self):
        assert next_state(run("REPAIRING"), "unsafe_patch").to_state == "GAVE_UP"


class TestInterruptions:
    @pytest.mark.parametrize(
        "state", ["QUEUED", "PLANNING", "PATCHING", "PR_OPEN", "AWAITING_CI", "REPAIRING"]
    )
    def test_closing_the_pull_request_cancels_the_run_from_anywhere(self, state):
        assert next_state(run(state), "pr_closed").to_state == "CANCELLED"

    @pytest.mark.parametrize("state", ["QUEUED", "PLANNING", "PATCHING", "AWAITING_CI"])
    def test_an_unexpected_error_moves_the_run_to_errored(self, state):
        assert next_state(run(state), "errored").to_state == "ERRORED"

    def test_a_merge_still_wins_over_a_close_once_the_pr_is_ready(self):
        assert next_state(run("READY_TO_MERGE"), "pr_merged").to_state == "MERGED"


class TestTerminalStates:
    @pytest.mark.parametrize(
        "state", ["COMPLETED", "GAVE_UP", "CANCELLED", "ERRORED", "NOTHING_TO_DO"]
    )
    def test_a_finished_run_is_terminal(self, state):
        assert is_terminal(state) is True

    @pytest.mark.parametrize("state", ["QUEUED", "PLANNING", "AWAITING_CI", "REPAIRING"])
    def test_a_run_still_in_flight_is_not_terminal(self, state):
        assert is_terminal(state) is False

    @pytest.mark.parametrize("event", ["ci_failed", "pr_closed", "errored"])
    def test_nothing_moves_a_terminal_run(self, event):
        with pytest.raises(InvalidTransitionError):
            next_state(run("COMPLETED"), event)


class TestRejectedTransitions:
    def test_refuses_an_event_that_makes_no_sense_in_the_current_state(self):
        with pytest.raises(InvalidTransitionError, match="ci_passed"):
            next_state(run("PLANNING"), "ci_passed")

    def test_the_error_names_the_state_it_was_in(self):
        with pytest.raises(InvalidTransitionError, match="PLANNING"):
            next_state(run("PLANNING"), "ci_passed")

    def test_refuses_an_event_the_machine_does_not_know(self):
        with pytest.raises(InvalidTransitionError):
            next_state(run("QUEUED"), "teleport")  # type: ignore[arg-type]


class TestScheduling:
    @pytest.mark.parametrize("state", ["QUEUED", "PLANNING", "PATCHING", "PR_OPEN", "MERGED"])
    def test_states_the_agent_can_advance_on_its_own_run_immediately(self, state):
        assert runs_immediately(state) is True

    @pytest.mark.parametrize("state", ["AWAITING_CI", "READY_TO_MERGE"])
    def test_states_that_wait_for_github_do_not_reschedule_themselves(self, state):
        assert runs_immediately(state) is False

    @pytest.mark.parametrize("state", ["COMPLETED", "GAVE_UP", "CANCELLED"])
    def test_a_terminal_state_never_reschedules(self, state):
        assert runs_immediately(state) is False


class TestEventCoverage:
    def test_every_event_the_machine_accepts_is_reachable_from_some_state(self):
        from vulnagent.agent.state_machine import EVENTS, STATES

        reachable = {event for state in STATES for event in EVENTS if _accepts(state, event)}

        assert reachable == set(EVENTS)


def _accepts(state: AgentState, event: AgentEvent) -> bool:
    try:
        next_state(run(state), event)
    except InvalidTransitionError:
        return False
    return True
