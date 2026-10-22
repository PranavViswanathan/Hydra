"""Cron entry point: find repositories due for a scan (§10)."""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

from vulnagent.runtime import build_context
from vulnagent.services.triggers import next_scan_time, scan_function_id


def main(context: Any) -> Any:
    app = build_context()
    try:
        now = dt.datetime.now(dt.UTC)
        due = app.db.repos.due_for_scan(now)

        for repo in due:
            app.enqueue(scan_function_id(), {"repo_id": repo.id, "trigger": "schedule"})
            app.db.repos.update(repo.id, {"next_scan_at": next_scan_time(repo, now)})
            context.log(f"queued a scan for {repo.full_name}")

        return context.res.json({"queued": len(due)})
    finally:
        app.close()
