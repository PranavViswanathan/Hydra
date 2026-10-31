"""Which handler a call to the one Appwrite function belongs to (§10)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from vulnagent.core.safety import verify_webhook_signature
from vulnagent.entrypoints.tasks import SIGNATURE_HEADER, TASK_PATHS, Task

type Destination = (
    Task | Literal["scheduler", "vulnerability_created", "github_webhook", "api", "forbidden"]
)

TASK_PREFIX = "/tasks/"


def destination(
    *, trigger: str, path: str, headers: Mapping[str, str], body: bytes, key: bytes
) -> Destination:
    if trigger == "schedule":
        return "scheduler"
    if trigger == "event":
        return "vulnerability_created"
    if path.startswith(TASK_PREFIX):
        return _task(path, headers, body, key)
    if "x-github-event" in headers:
        return "github_webhook"
    return "api"


def _task(path: str, headers: Mapping[str, str], body: bytes, key: bytes) -> Destination:
    task = next((task for task, task_path in TASK_PATHS.items() if task_path == path), None)
    if task is None or not verify_webhook_signature(body, headers.get(SIGNATURE_HEADER), key):
        return "forbidden"
    return task
