"""The one Appwrite function: pick the handler for this call and run it (§10).

Appwrite's free plan allows two functions, so every Python trigger shares
this deployment. See `routing.destination` for how a call is told apart.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Final

from vulnagent.entrypoints import (
    agent_step,
    api,
    github_webhook,
    scan,
    scheduler,
    vulnerability_created,
)
from vulnagent.entrypoints.routing import destination

HANDLERS: Final[dict[str, Callable[[Any], Any]]] = {
    "scheduler": scheduler.handle,
    "vulnerability_created": vulnerability_created.handle,
    "scan": scan.handle,
    "agent_step": agent_step.handle,
    "github_webhook": github_webhook.handle,
    "api": api.handle,
}


def main(context: Any) -> Any:
    headers = context.req.headers
    found = destination(
        trigger=headers.get("x-appwrite-trigger", "http"),
        path=context.req.path.rstrip("/") or "/",
        headers=headers,
        body=context.req.body_binary or b"",
        key=os.environ.get("APPWRITE_API_KEY", "").encode(),
    )
    if found == "forbidden":
        return context.res.json({"error": "forbidden"}, 403)
    return HANDLERS[found](context)
