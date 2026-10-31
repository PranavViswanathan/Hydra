"""Work the function hands to itself, as a signed async execution (§10).

The function is public so GitHub can reach it, so a task path alone proves
nothing. Each task body is signed with the server API key, which only the
deployment holds.
"""

from __future__ import annotations

import json
import os
from typing import Any, Final, Literal, Protocol

from vulnagent.core.safety import sign_body

type Task = Literal["scan", "agent_step"]

TASK_PATHS: Final[dict[Task, str]] = {"scan": "/tasks/scan", "agent_step": "/tasks/agent-step"}
SIGNATURE_HEADER: Final = "x-hydra-signature"
DEFAULT_FUNCTION_ID: Final = "hydra"


def own_function_id() -> str:
    """Appwrite tells every execution which function it is running in."""
    return os.environ.get("APPWRITE_FUNCTION_ID", DEFAULT_FUNCTION_ID)


class FunctionsService(Protocol):
    def create_execution(self, **kwargs: Any) -> Any: ...


class TaskQueue:
    def __init__(self, *, functions: FunctionsService, function_id: str, key: bytes) -> None:
        self._functions = functions
        self._function_id = function_id
        self._key = key

    def enqueue(self, task: Task, payload: dict[str, Any]) -> None:
        body = json.dumps(payload)
        self._functions.create_execution(
            function_id=self._function_id,
            body=body,
            xasync=True,
            path=TASK_PATHS[task],
            method="POST",
            headers={SIGNATURE_HEADER: sign_body(body.encode(), self._key)},
        )
