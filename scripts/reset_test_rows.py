#!/usr/bin/env python3
"""Clear a repository's Appwrite rows so an end-to-end run starts clean.

    uv run python scripts/reset_test_rows.py owner/repo

Pairs with scripts/reset_test_repo.sh, which resets the GitHub side.
"""

from __future__ import annotations

import sys

from appwrite.client import Client
from appwrite.services.tables_db import TablesDB

from vulnagent.config.settings import load_settings
from vulnagent.db.repositories import Database


def main(full_name: str) -> int:
    settings = load_settings(dotenv=".env")
    client = (
        Client()
        .set_endpoint(settings.appwrite_endpoint)
        .set_project(settings.appwrite_project_id)
        .set_key(settings.appwrite_api_key.get_secret_value())
    )
    db = Database(TablesDB(client))

    repo = db.repos.by_full_name(full_name)
    if repo is None:
        print(f"no repository row for {full_name}", file=sys.stderr)
        return 1

    for run in db.runs.for_repo(repo.id):
        for event in db.events.for_run(run.id):
            db.events.delete(event.id)
        db.runs.delete(run.id)
    for vulnerability in db.vulnerabilities.for_repo(repo.id):
        db.vulnerabilities.delete(vulnerability.id)
    for package in db.packages.for_repo(repo.id):
        db.packages.delete(package.id)
    for edge in db.edges.for_repo(repo.id):
        db.edges.delete(edge.id)

    db.repos.update(
        repo.id,
        {
            "agent_state": "idle",
            "active_run_id": None,
            "last_scan_at": None,
            "open_critical": 0,
            "open_high": 0,
            "open_medium": 0,
            "open_low": 0,
            "open_unknown": 0,
        },
    )
    print(f"{full_name}: rows cleared, repository back to idle")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1]))
