"""Typed repositories over TablesDB (§7).

No raw SDK call lives outside this module and `vulnagent.memory`. Each
repository converts rows to the models in `rows.py` and back.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final, Protocol

from appwrite.query import Query

from vulnagent.core.models import Severity
from vulnagent.db.rows import (
    DATABASE_ID,
    AdvisoryRow,
    AgentEvent,
    AgentRun,
    DependencyEdge,
    EventType,
    Installation,
    Repo,
    RepoPackage,
    Row,
    Scan,
    Vulnerability,
    WebhookDelivery,
)

UNIQUE_ID: Final = "unique()"
PAGE_SIZE: Final = 100
MAX_ROWS: Final = 5000


class TablesDbService(Protocol):
    """The slice of `appwrite.services.tables_db.TablesDB` the repositories use."""

    def create_row(
        self, database_id: str, table_id: str, row_id: str, data: dict[str, Any]
    ) -> Any: ...

    def update_row(
        self, database_id: str, table_id: str, row_id: str, data: dict[str, Any] | None = None
    ) -> Any: ...

    def upsert_row(
        self, database_id: str, table_id: str, row_id: str, data: dict[str, Any] | None = None
    ) -> Any: ...

    def delete_row(self, database_id: str, table_id: str, row_id: str) -> Any: ...

    def get_row(self, database_id: str, table_id: str, row_id: str) -> Any: ...

    def list_rows(
        self, database_id: str, table_id: str, queries: list[str] | None = None
    ) -> Any: ...


class Table[TRow: Row]:
    """Shared create/read/update/delete for one table."""

    def __init__(
        self,
        tables: TablesDbService,
        *,
        table_id: str,
        model: type[TRow],
        database_id: str = DATABASE_ID,
    ) -> None:
        self._tables = tables
        self._table_id = table_id
        self._model = model
        self._database_id = database_id

    def create(self, row: TRow, *, row_id: str = UNIQUE_ID) -> TRow:
        created = self._tables.create_row(
            database_id=self._database_id,
            table_id=self._table_id,
            row_id=row_id,
            data=row.to_row(),
        )
        return self._parse(created) or row

    def update(self, row_id: str, changes: dict[str, Any]) -> None:
        self._tables.update_row(
            database_id=self._database_id,
            table_id=self._table_id,
            row_id=row_id,
            data=_serialise(changes),
        )

    def get(self, row_id: str) -> TRow | None:
        return self._parse(self._tables.get_row(self._database_id, self._table_id, row_id))

    def delete(self, row_id: str) -> None:
        self._tables.delete_row(self._database_id, self._table_id, row_id)

    def find(self, queries: list[str], *, limit: int = PAGE_SIZE) -> list[TRow]:
        """Page through everything matching, up to a hard ceiling."""
        found: list[TRow] = []
        offset = 0
        while len(found) < MAX_ROWS:
            page = self._tables.list_rows(
                database_id=self._database_id,
                table_id=self._table_id,
                queries=[*queries, Query.limit(limit), Query.offset(offset)],
            )
            rows = _rows_of(page)
            found.extend(parsed for row in rows if (parsed := self._parse(row)) is not None)
            if len(rows) < limit:
                break
            offset += limit
        return found

    def first(self, queries: list[str]) -> TRow | None:
        found = self.find(queries, limit=1)
        return found[0] if found else None

    def _parse(self, row: Any) -> TRow | None:
        if not isinstance(row, dict) or not row:
            return None
        try:
            parsed: TRow = self._model.from_row(row)
        except ValueError:
            return None
        return parsed


class Installations(Table[Installation]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="installations", model=Installation)

    def by_github_id(self, github_installation_id: int) -> Installation | None:
        return self.first([Query.equal("github_installation_id", github_installation_id)])


class Repos(Table[Repo]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="repos", model=Repo)

    def by_github_id(self, github_repo_id: int) -> Repo | None:
        return self.first([Query.equal("github_repo_id", github_repo_id)])

    def by_full_name(self, full_name: str) -> Repo | None:
        return self.first([Query.equal("full_name", full_name)])

    def for_owner(self, owner_user_id: str) -> list[Repo]:
        return self.find([Query.equal("owner_user_id", owner_user_id)])

    def due_for_scan(self, now: dt.datetime) -> list[Repo]:
        return self.find(
            [
                Query.less_than_equal("next_scan_at", now.isoformat()),
                Query.equal("agent_state", "idle"),
            ]
        )

    def set_counts(self, repo_id: str, counts: dict[Severity, int]) -> None:
        self.update(repo_id, {f"open_{severity}": count for severity, count in counts.items()})

    def start_run(self, repo_id: str, run_id: str) -> None:
        self.update(repo_id, {"active_run_id": run_id, "agent_state": "working"})

    def go_to_sleep(self, repo_id: str, *, errored: bool = False) -> None:
        """Terminal states release the repo: no active run, state back to idle."""
        self.update(repo_id, {"active_run_id": None, "agent_state": "error" if errored else "idle"})


class Scans(Table[Scan]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="scans", model=Scan)


class RepoPackages(Table[RepoPackage]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="repo_packages", model=RepoPackage)

    def for_repo(self, repo_id: str) -> list[RepoPackage]:
        return self.find([Query.equal("repo_id", repo_id)])


class DependencyEdges(Table[DependencyEdge]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="dependency_edges", model=DependencyEdge)

    def for_repo(self, repo_id: str) -> list[DependencyEdge]:
        return self.find([Query.equal("repo_id", repo_id)])


class Advisories(Table[AdvisoryRow]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="advisories", model=AdvisoryRow)

    def by_osv_id(self, osv_id: str) -> AdvisoryRow | None:
        return self.first([Query.equal("osv_id", osv_id)])

    def known_ids(self, osv_ids: list[str]) -> dict[str, AdvisoryRow]:
        if not osv_ids:
            return {}
        found = self.find([Query.equal("osv_id", osv_ids)])
        return {row.osv_id: row for row in found}


class Vulnerabilities(Table[Vulnerability]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="vulnerabilities", model=Vulnerability)

    def for_repo(self, repo_id: str) -> list[Vulnerability]:
        return self.find([Query.equal("repo_id", repo_id)])

    def open_for_repo(self, repo_id: str) -> list[Vulnerability]:
        return self.find(
            [Query.equal("repo_id", repo_id), Query.equal("status", ["open", "in_progress"])]
        )

    def mark(self, vuln_ids: list[str], status: str, **extra: Any) -> None:
        for vuln_id in vuln_ids:
            self.update(vuln_id, {"status": status, **extra})


class AgentRuns(Table[AgentRun]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="agent_runs", model=AgentRun)

    def for_repo(self, repo_id: str) -> list[AgentRun]:
        return self.find([Query.equal("repo_id", repo_id), Query.order_desc("created_at")])

    def by_pr_number(self, repo_id: str, pr_number: int) -> AgentRun | None:
        return self.first([Query.equal("repo_id", repo_id), Query.equal("pr_number", pr_number)])

    def save_state(self, run_id: str, state: str, **extra: Any) -> None:
        self.update(
            run_id,
            {"state": state, "updated_at": dt.datetime.now(dt.UTC), **extra},
        )


class AgentEvents(Table[AgentEvent]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="agent_events", model=AgentEvent)

    def for_run(self, run_id: str) -> list[AgentEvent]:
        return self.find([Query.equal("run_id", run_id), Query.order_asc("created_at")])

    def log(
        self,
        *,
        run_id: str,
        repo_id: str,
        event_type: EventType,
        message: str,
        data_json: str | None = None,
    ) -> AgentEvent:
        return self.create(
            AgentEvent(
                run_id=run_id,
                repo_id=repo_id,
                type=event_type,
                message=message,
                data_json=data_json,
            )
        )


class WebhookDeliveries(Table[WebhookDelivery]):
    def __init__(self, tables: TablesDbService) -> None:
        super().__init__(tables, table_id="webhook_deliveries", model=WebhookDelivery)

    def claim(self, delivery_id: str, event: str) -> bool:
        """True the first time a delivery is seen; False for a redelivery (§9.5)."""
        try:
            self.create(
                WebhookDelivery(delivery_id=delivery_id, event=event), row_id=_safe_id(delivery_id)
            )
        except Exception:
            return False
        return True


class Database:
    """One handle to every repository, built once per function execution."""

    def __init__(self, tables: TablesDbService) -> None:
        self.installations = Installations(tables)
        self.repos = Repos(tables)
        self.scans = Scans(tables)
        self.packages = RepoPackages(tables)
        self.edges = DependencyEdges(tables)
        self.advisories = Advisories(tables)
        self.vulnerabilities = Vulnerabilities(tables)
        self.runs = AgentRuns(tables)
        self.events = AgentEvents(tables)
        self.deliveries = WebhookDeliveries(tables)


def _rows_of(page: Any) -> list[dict[str, Any]]:
    if not isinstance(page, dict):
        return []
    rows = page.get("rows")
    if rows is None:
        rows = page.get("documents")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _serialise(changes: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, dt.datetime) else value
        for key, value in changes.items()
    }


def _safe_id(value: str) -> str:
    """Appwrite ids allow a-z, A-Z, 0-9, underscore and hyphen, 36 characters."""
    cleaned = "".join(character if character.isalnum() else "-" for character in value)
    return cleaned[:36].strip("-") or UNIQUE_ID
