#!/usr/bin/env python3
"""Create every TablesDB table, column and index, idempotently (PROJECT.md 7).

    uv run python scripts/bootstrap_db.py          # create or top up
    uv run python scripts/bootstrap_db.py --check  # report, change nothing

Safe to re-run: anything that already exists is left alone. VectorsDB is set up
separately by scripts/bootstrap_vectors.py, because it may need a dedicated
database and is allowed to fail without blocking the rest.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

from appwrite.client import Client
from appwrite.enums.tables_db_index_type import TablesDBIndexType
from appwrite.services.tables_db import TablesDB

from vulnagent.config.settings import load_settings
from vulnagent.db.rows import DATABASE_ID

SEVERITIES = ["low", "medium", "high", "critical", "unknown"]
LONG = 1_000_000
MEDIUM = 4096
SHORT = 255


@dataclass(frozen=True)
class Column:
    key: str
    kind: str
    required: bool = False
    size: int = SHORT
    elements: list[str] = field(default_factory=list)
    array: bool = False


@dataclass(frozen=True)
class Index:
    key: str
    columns: list[str]
    unique: bool = False


@dataclass(frozen=True)
class TableSpec:
    id: str
    name: str
    columns: list[Column]
    indexes: list[Index] = field(default_factory=list)


def text(key: str, *, required: bool = False, size: int = SHORT) -> Column:
    return Column(key, "string", required=required, size=size)


def enum(key: str, elements: list[str], *, required: bool = False) -> Column:
    return Column(key, "enum", required=required, elements=elements)


TABLES = [
    TableSpec(
        "installations",
        "Installations",
        [
            Column("github_installation_id", "integer", required=True),
            text("account_login", required=True),
            enum("account_type", ["User", "Organization"], required=True),
            text("owner_user_id"),
            Column("suspended", "boolean"),
        ],
        [Index("github_installation_id", ["github_installation_id"], unique=True)],
    ),
    TableSpec(
        "repos",
        "Repositories",
        [
            text("installation_id", required=True),
            Column("github_repo_id", "integer", required=True),
            text("full_name", required=True),
            text("default_branch", required=True),
            text("owner_user_id"),
            Column("has_config", "boolean"),
            text("config_json", size=LONG),
            text("config_error", size=MEDIUM),
            Column("ecosystems", "string", size=SHORT, array=True),
            enum("agent_state", ["idle", "scanning", "working", "error"], required=True),
            text("active_run_id"),
            Column("next_scan_at", "datetime"),
            Column("last_scan_at", "datetime"),
            *(
                Column(f"open_{severity}", "integer")
                for severity in ["critical", "high", "medium", "low", "unknown"]
            ),
        ],
        [
            Index("github_repo_id", ["github_repo_id"], unique=True),
            Index("full_name", ["full_name"]),
            Index("owner_user_id", ["owner_user_id"]),
            Index("next_scan_at", ["next_scan_at"]),
        ],
    ),
    TableSpec(
        "scans",
        "Scans",
        [
            text("repo_id", required=True),
            enum("trigger", ["schedule", "push", "new_advisory", "manual"], required=True),
            enum("status", ["running", "succeeded", "failed"], required=True),
            text("commit_sha"),
            Column("packages_scanned", "integer"),
            Column("vulns_found", "integer"),
            text("error", size=MEDIUM),
            Column("started_at", "datetime"),
            Column("finished_at", "datetime"),
        ],
        [Index("repo_id", ["repo_id"])],
    ),
    TableSpec(
        "repo_packages",
        "Repository packages",
        [
            text("repo_id", required=True),
            text("purl", required=True, size=MEDIUM),
            text("ecosystem", required=True),
            text("name", required=True),
            text("version", required=True),
            Column("is_direct", "boolean"),
            Column("is_dev", "boolean"),
            text("scan_id"),
        ],
        [Index("repo_purl", ["repo_id", "purl"], unique=True), Index("name", ["name"])],
    ),
    TableSpec(
        "dependency_edges",
        "Dependency edges",
        [
            text("repo_id", required=True),
            text("parent_purl", required=True, size=MEDIUM),
            text("child_purl", required=True, size=MEDIUM),
            text("requested_range"),
            text("ecosystem"),
            text("scan_id"),
        ],
        [Index("repo_child", ["repo_id", "child_purl"]), Index("repo_id", ["repo_id"])],
    ),
    TableSpec(
        "advisories",
        "Advisories",
        [
            text("osv_id", required=True),
            Column("aliases", "string", size=SHORT, array=True),
            text("summary", size=MEDIUM),
            text("details", size=LONG),
            enum("severity", SEVERITIES, required=True),
            Column("cvss_score", "float"),
            text("affected_json", size=LONG),
            Column("osv_modified", "datetime"),
        ],
        [Index("osv_id", ["osv_id"], unique=True)],
    ),
    TableSpec(
        "vulnerabilities",
        "Vulnerabilities",
        [
            text("repo_id", required=True),
            text("osv_id", required=True),
            text("purl", required=True, size=MEDIUM),
            text("package_name", required=True),
            text("installed_version", required=True),
            text("fixed_version"),
            enum("severity", SEVERITIES, required=True),
            enum(
                "status",
                ["open", "in_progress", "fixed", "ignored", "unfixable", "needs_major"],
                required=True,
            ),
            Column("is_direct", "boolean"),
            Column("first_seen_at", "datetime"),
            Column("last_seen_at", "datetime"),
            Column("resolved_at", "datetime"),
            text("resolved_by_run_id"),
        ],
        [
            Index("repo_osv_purl", ["repo_id", "osv_id", "purl"], unique=True),
            Index("repo_status_severity", ["repo_id", "status", "severity"]),
        ],
    ),
    TableSpec(
        "agent_runs",
        "Agent runs",
        [
            text("repo_id", required=True),
            enum("trigger", ["auto", "manual"], required=True),
            text("state", required=True),
            Column("attempt", "integer"),
            Column("max_attempts", "integer"),
            Column("vuln_ids", "string", size=SHORT, array=True),
            text("plan_json", size=LONG),
            text("branch"),
            text("base_sha"),
            text("head_sha"),
            Column("pr_number", "integer"),
            text("pr_url", size=MEDIUM),
            text("last_error", size=MEDIUM),
            Column("created_at", "datetime"),
            Column("updated_at", "datetime"),
            Column("completed_at", "datetime"),
        ],
        [Index("repo_id", ["repo_id"]), Index("state", ["state"])],
    ),
    TableSpec(
        "agent_events",
        "Agent events",
        [
            text("run_id", required=True),
            text("repo_id", required=True),
            enum(
                "type",
                [
                    "state_change",
                    "info",
                    "pr_opened",
                    "ci_failed",
                    "ci_passed",
                    "memory_hit",
                    "patch_pushed",
                    "gave_up",
                    "merged",
                    "error",
                ],
                required=True,
            ),
            text("message", required=True, size=MEDIUM),
            text("data_json", size=LONG),
            Column("created_at", "datetime"),
        ],
        [Index("run_id", ["run_id"]), Index("repo_id", ["repo_id"])],
    ),
    TableSpec(
        "webhook_deliveries",
        "Webhook deliveries",
        [
            text("delivery_id", required=True),
            text("event", required=True),
            Column("received_at", "datetime"),
        ],
        [Index("delivery_id", ["delivery_id"], unique=True)],
    ),
]


class Bootstrapper:
    def __init__(self, tables: TablesDB, *, check_only: bool) -> None:
        self._tables = tables
        self._check_only = check_only
        self.missing: list[str] = []

    def run(self) -> None:
        self._database()
        for spec in TABLES:
            self._table(spec)

    def _database(self) -> None:
        if self._exists(lambda: self._tables.get(DATABASE_ID)):
            print(f"database {DATABASE_ID}: present")
            return
        self._create(
            f"database {DATABASE_ID}", lambda: self._tables.create(DATABASE_ID, "VulnAgent")
        )

    def _table(self, spec: TableSpec) -> None:
        print(f"\n{spec.id}")
        if not self._exists(lambda: self._tables.get_table(DATABASE_ID, spec.id)):
            self._create(
                f"  table {spec.id}",
                lambda: self._tables.create_table(DATABASE_ID, spec.id, spec.name),
            )

        for column in spec.columns:
            self._column(spec, column)
        for index in spec.indexes:
            self._index(spec, index)

    def _column(self, spec: TableSpec, column: Column) -> None:
        if self._exists(lambda: self._tables.get_column(DATABASE_ID, spec.id, column.key)):
            return
        self._create(
            f"  column {column.key} ({column.kind})", lambda: self._add_column(spec, column)
        )

    def _add_column(self, spec: TableSpec, column: Column) -> Any:
        common = {
            "database_id": DATABASE_ID,
            "table_id": spec.id,
            "key": column.key,
            "required": column.required,
            "array": column.array,
        }
        match column.kind:
            case "string":
                return self._tables.create_string_column(size=column.size, **common)
            case "integer":
                return self._tables.create_integer_column(**common)
            case "float":
                return self._tables.create_float_column(**common)
            case "boolean":
                return self._tables.create_boolean_column(**common)
            case "datetime":
                return self._tables.create_datetime_column(**common)
            case "enum":
                return self._tables.create_enum_column(elements=column.elements, **common)
        raise ValueError(f"unknown column kind {column.kind}")

    def _index(self, spec: TableSpec, index: Index) -> None:
        if self._exists(lambda: self._tables.get_index(DATABASE_ID, spec.id, index.key)):
            return
        self._create(
            f"  index {index.key}",
            lambda: self._tables.create_index(
                database_id=DATABASE_ID,
                table_id=spec.id,
                key=index.key,
                type=TablesDBIndexType.UNIQUE if index.unique else TablesDBIndexType.KEY,
                columns=index.columns,
            ),
        )

    def _exists(self, probe: Any) -> bool:
        try:
            probe()
        except Exception:
            return False
        return True

    def _create(self, label: str, action: Any) -> None:
        if self._check_only:
            print(f"{label}: MISSING")
            self.missing.append(label.strip())
            return
        action()
        print(f"{label}: created")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="report what is missing, change nothing"
    )
    arguments = parser.parse_args()

    settings = load_settings(dotenv=".env")
    client = (
        Client()
        .set_endpoint(settings.appwrite_endpoint)
        .set_project(settings.appwrite_project_id)
        .set_key(settings.appwrite_api_key.get_secret_value())
    )

    bootstrapper = Bootstrapper(TablesDB(client), check_only=arguments.check)
    bootstrapper.run()

    if arguments.check and bootstrapper.missing:
        print(f"\n{len(bootstrapper.missing)} things are missing", file=sys.stderr)
        return 1
    print("\nschema is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
