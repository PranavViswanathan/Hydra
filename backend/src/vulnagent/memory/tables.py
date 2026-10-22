"""Failure memory with no VectorsDB: embeddings in a TablesDB column (§8 fallback).

Brute-force cosine over the rows for one ecosystem. Fine at the scale this
runs at (hundreds of rows), and it keeps the agent working if VectorsDB turns
out to need a dedicated database.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from vulnagent.memory.base import (
    COLLECTION,
    DEFAULT_THRESHOLD,
    DEFAULT_TOP_K,
    EmbeddingProvider,
    FailureRecord,
    Hit,
    cosine_similarity,
)

MAX_ROWS_SCANNED = 1000


class TablesDbService(Protocol):
    """The slice of `appwrite.services.tables_db.TablesDB` this module uses."""

    def create_row(
        self, database_id: str, table_id: str, row_id: str, data: dict[str, Any]
    ) -> Any: ...

    def list_rows(
        self, database_id: str, table_id: str, queries: list[str] | None = None
    ) -> Any: ...


class TablesDBMemory:
    def __init__(
        self,
        *,
        tables: TablesDbService,
        embeddings: EmbeddingProvider,
        database_id: str,
        table_id: str = COLLECTION,
        threshold: float = DEFAULT_THRESHOLD,
        row_id: str = "unique()",
    ) -> None:
        self._tables = tables
        self._embeddings = embeddings
        self._database_id = database_id
        self._table_id = table_id
        self._threshold = threshold
        self._row_id = row_id

    def add(self, record: FailureRecord) -> None:
        row = record.as_row(self._embeddings.embed(record.embedding_text()))
        row["embedding"] = json.dumps(row["embedding"])  # stored as text, not a vector column
        self._tables.create_row(
            database_id=self._database_id,
            table_id=self._table_id,
            row_id=self._row_id,
            data=row,
        )

    def search(self, signature: str, *, ecosystem: str, k: int = DEFAULT_TOP_K) -> list[Hit]:
        if not signature.strip():
            return []

        from appwrite.query import Query

        embedding = self._embeddings.embed(signature)
        response = self._tables.list_rows(
            database_id=self._database_id,
            table_id=self._table_id,
            queries=[
                Query.equal("ecosystem", ecosystem),
                Query.equal("outcome", "success"),
                Query.limit(MAX_ROWS_SCANNED),
            ],
        )

        hits: list[Hit] = []
        for row in _rows(response):
            stored = _embedding_of(row)
            if stored is None:
                continue
            score = cosine_similarity(embedding, stored)
            if score < self._threshold:
                continue
            try:
                record = FailureRecord.model_validate(
                    {
                        key: value
                        for key, value in row.items()
                        if not key.startswith("$") and key != "embedding"
                    }
                )
            except ValueError:
                continue
            hits.append(Hit(record=record, score=score))

        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:k]


def _rows(response: Any) -> list[dict[str, Any]]:
    rows = response.get("rows") or response.get("documents") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _embedding_of(row: dict[str, Any]) -> list[float] | None:
    raw = row.get("embedding")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, list):
        return None
    try:
        return [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
