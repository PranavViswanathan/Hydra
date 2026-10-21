"""The agent's state machine as a pure function (§9.1).

`next_state` decides; `steps.py` acts. Keeping the decision pure means every
transition, including the attempt accounting that stops the CI repair loop, is
testable without Appwrite or GitHub.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

type AgentState = Literal[
    "QUEUED",
    "PLANNING",
    "PATCHING",
    "PR_OPEN",
    "AWAITING_CI",
    "REPAIRING",
    "READY_TO_MERGE",
    "MERGED",
    "COMPLETED",
    "GAVE_UP",
    "CANCELLED",
    "ERRORED",
    "NOTHING_TO_DO",
]

type AgentEvent = Literal[
    "vulnerabilities_selected",
    "plan_ready",
    "branch_pushed",
    "pr_opened",
    "ci_passed",
    "ci_failed",
    "patch_pushed",
    "pr_merged",
    "cleanup_done",
    "nothing_to_do",
    "gave_up",
    "unsafe_patch",
    "pr_closed",
    "errored",
]

STATES: Final[tuple[AgentState, ...]] = get_args(AgentState.__value__)
EVENTS: Final[tuple[AgentEvent, ...]] = get_args(AgentEvent.__value__)

TERMINAL_STATES: Final[frozenset[str]] = frozenset(
    {"COMPLETED", "GAVE_UP", "CANCELLED", "ERRORED", "NOTHING_TO_DO"}
)

# States the agent can advance by itself; the rest wait for a GitHub webhook.
SELF_DRIVEN_STATES: Final[frozenset[str]] = frozenset(
    {"QUEUED", "PLANNING", "PATCHING", "PR_OPEN", "REPAIRING", "MERGED"}
)

_TRANSITIONS: Final[dict[tuple[str, str], AgentState]] = {
    ("QUEUED", "vulnerabilities_selected"): "PLANNING",
    ("QUEUED", "nothing_to_do"): "NOTHING_TO_DO",
    ("PLANNING", "plan_ready"): "PATCHING",
    ("PLANNING", "nothing_to_do"): "NOTHING_TO_DO",
    ("PATCHING", "branch_pushed"): "PR_OPEN",
    ("PR_OPEN", "pr_opened"): "AWAITING_CI",
    ("AWAITING_CI", "ci_passed"): "READY_TO_MERGE",
    ("REPAIRING", "patch_pushed"): "AWAITING_CI",
    ("REPAIRING", "gave_up"): "GAVE_UP",
    ("REPAIRING", "unsafe_patch"): "GAVE_UP",
    ("READY_TO_MERGE", "pr_merged"): "MERGED",
    ("MERGED", "cleanup_done"): "COMPLETED",
}

# Available from any state that is still in flight.
_INTERRUPTS: Final[dict[str, AgentState]] = {"pr_closed": "CANCELLED", "errored": "ERRORED"}


class InvalidTransitionError(Exception):
    """The event cannot happen in the run's current state."""


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    state: AgentState
    attempt: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class Transition:
    to_state: AgentState
    attempt_delta: int = 0


def next_state(run: RunSnapshot, event: AgentEvent) -> Transition:
    if is_terminal(run.state):
        raise InvalidTransitionError(f"run is already {run.state}; {event!r} changes nothing")

    if event == "ci_failed" and run.state == "AWAITING_CI":
        return Transition(to_state="REPAIRING" if _may_retry(run) else "GAVE_UP")

    if event == "patch_pushed" and run.state == "REPAIRING":
        return Transition(to_state="AWAITING_CI", attempt_delta=1)

    interrupt = _INTERRUPTS.get(event)
    if interrupt is not None:
        return Transition(to_state=interrupt)

    destination = _TRANSITIONS.get((run.state, event))
    if destination is None:
        raise InvalidTransitionError(f"{event!r} is not valid while the run is {run.state}")
    return Transition(to_state=destination)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def runs_immediately(state: str) -> bool:
    """Whether `agent_step` should re-enqueue itself after this state."""
    return state in SELF_DRIVEN_STATES and not is_terminal(state)


def _may_retry(run: RunSnapshot) -> bool:
    return run.attempt < run.max_attempts
