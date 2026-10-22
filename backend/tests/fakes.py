"""An in-memory stand-in for Appwrite TablesDB, good enough for the repositories.

Supports the handful of query shapes the code actually sends: equal (scalar or
list), lessThanEqual, limit, offset and ordering.
"""

from __future__ import annotations

import json
from typing import Any


class FakeTablesDB:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict[str, Any]]] = {}
        self.next_id = 0

    # --- the TablesDbService slice ----------------------------------------

    def create_row(self, database_id, table_id, row_id, data, **_):
        rows = self.tables.setdefault(table_id, {})
        resolved = self._resolve_id(row_id)
        if resolved in rows:
            raise ConflictError(f"row {resolved} already exists in {table_id}")
        stored = {"$id": resolved, **data}
        rows[resolved] = stored
        return dict(stored)

    def update_row(self, database_id, table_id, row_id, data=None, **_):
        rows = self.tables.setdefault(table_id, {})
        if row_id not in rows:
            raise KeyError(row_id)
        rows[row_id].update(data or {})
        return dict(rows[row_id])

    def upsert_row(self, database_id, table_id, row_id, data=None, **_):
        rows = self.tables.setdefault(table_id, {})
        resolved = self._resolve_id(row_id)
        rows[resolved] = {"$id": resolved, **(rows.get(resolved) or {}), **(data or {})}
        return dict(rows[resolved])

    def delete_row(self, database_id, table_id, row_id, **_):
        self.tables.setdefault(table_id, {}).pop(row_id, None)
        return {}

    def get_row(self, database_id, table_id, row_id, **_):
        return dict(self.tables.get(table_id, {}).get(row_id) or {})

    def list_rows(self, database_id, table_id, queries=None, **_):
        rows = list(self.tables.get(table_id, {}).values())
        limit, offset = 25, 0

        for raw in queries or []:
            query = json.loads(raw)
            method = query.get("method")
            attribute = query.get("attribute")
            values = query.get("values", [])
            if method == "equal":
                rows = [row for row in rows if row.get(attribute) in values]
            elif method == "lessThanEqual":
                rows = [
                    row
                    for row in rows
                    if row.get(attribute) is not None and row[attribute] <= values[0]
                ]
            elif method == "orderDesc":
                rows.sort(key=lambda row: str(row.get(attribute, "")), reverse=True)
            elif method == "orderAsc":
                rows.sort(key=lambda row: str(row.get(attribute, "")))
            elif method == "limit":
                limit = int(values[0])
            elif method == "offset":
                offset = int(values[0])

        return {"total": len(rows), "rows": [dict(row) for row in rows[offset : offset + limit]]}

    # --- helpers ----------------------------------------------------------

    def rows_in(self, table_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.tables.get(table_id, {}).values()]

    def _resolve_id(self, row_id: str) -> str:
        if row_id != "unique()":
            return row_id
        self.next_id += 1
        return f"row{self.next_id}"


class ConflictError(Exception):
    """What Appwrite raises when a unique constraint is violated."""
