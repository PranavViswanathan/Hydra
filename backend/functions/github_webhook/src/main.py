"""HTTP entry point for GitHub webhooks (§10).

Verify, dedupe, route, return. Anything that takes real time is handed to an
async execution of another function.
"""

from __future__ import annotations

import os
from typing import Any

from vulnagent.core.safety import verify_webhook_signature
from vulnagent.github.webhooks import (
    Delivery,
    read_ci_completed,
    read_installation_change,
    read_pull_request_closed,
    read_push,
    route,
)
from vulnagent.runtime import build_context
from vulnagent.services.installations import apply_installation_change, reload_config
from vulnagent.services.triggers import (
    start_scan,
    wake_agent_for_ci,
    wake_agent_for_closed_pr,
)


def main(context: Any) -> Any:
    body = context.req.body_binary or b""
    signature = context.req.headers.get("x-hub-signature-256")
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()

    if not verify_webhook_signature(body, signature, secret):
        return context.res.json({"error": "bad signature"}, 401)

    delivery = Delivery(
        delivery_id=context.req.headers.get("x-github-delivery", ""),
        event=context.req.headers.get("x-github-event", ""),
        payload=context.req.body_json or {},
    )

    app = build_context()
    try:
        # §9.5: a redelivery is claimed once and then ignored.
        if not app.db.deliveries.claim(delivery.delivery_id, delivery.event):
            return context.res.json({"status": "duplicate"})

        handled = _route(app, delivery, context)
        return context.res.json({"status": handled})
    finally:
        app.close()


def _route(app: Any, delivery: Delivery, context: Any) -> str:
    destination = route(delivery)

    if destination == "installation_changed":
        apply_installation_change(app, read_installation_change(delivery.payload))
    elif destination == "push_to_default_branch":
        push = read_push(delivery.payload)
        reload_config(app, push)
        start_scan(app, push)
    elif destination == "ci_completed":
        wake_agent_for_ci(app, read_ci_completed(delivery))
    elif destination == "pull_request_closed":
        wake_agent_for_closed_pr(app, read_pull_request_closed(delivery.payload))
    else:
        context.log(f"ignoring {delivery.event}")

    return destination
