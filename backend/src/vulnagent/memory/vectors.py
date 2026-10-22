"""Failure memory backed by Appwrite VectorsDB (§8).

Written against the installed server SDK: `vectors_db.create_document` to
write and `vectors_db.create_query` with `Query.vector_cosine` to read.
Appwrite has no vector-distance filter query, so the similarity threshold is
applied here, on the rows that come back.
"""

from __future__ import annotations

from typing import Any, Final, Protocol

from appwrite.query import Query

from vulnagent.memory.base import (
    COLLECTION,
    DEFAULT_THRESHOLD,
    DEFAULT_TOP_K,
    EmbeddingProvider,
    FailureRecord,
    Hit,
    cosine_similarity,
)

# Appwrite returns the distance under one of these when it ranks by a vector.
_SCORE_KEYS: Final = ("$score", "$similarity", "$distance", "score", "distance")
_DISTANCE_KEYS: Final = frozenset({"$distance", "distance"})


class VectorsDbService(Protocol):
    """The slice of `appwrite.services.vectors_db.VectorsDB` this module uses."""

    def create_document(
        self, database_id: str, collection_id: str, document_id: str, data: dict[str, Any]
    ) -> Any: ...

    def create_query(
        self, database_id: str, collection_id: str, queries: list[str] | None = None
    ) -> Any: ...


class VectorsDBMemory:
    def __init__(
        self,
        *,
        vectors: VectorsDbService,
        embeddings: EmbeddingProvider,
        database_id: str,
        collection_id: str = COLLECTION,
        threshold: float = DEFAULT_THRESHOLD,
        document_id: str = "unique()",
    ) -> None:
        self._vectors = vectors
        self._embeddings = embeddings
        self._database_id = database_id
        self._collection_id = collection_id
        self._threshold = threshold
        self._document_id = document_id

    def add(self, record: FailureRecord) -> None:
        embedding = self._embeddings.embed(record.embedding_text())
        self._vectors.create_document(
            database_id=self._database_id,
            collection_id=self._collection_id,
            document_id=self._document_id,
            data=record.as_row(embedding),
        )

    def search(self, signature: str, *, ecosystem: str, k: int = DEFAULT_TOP_K) -> list[Hit]:
        if not signature.strip():
            return []

        embedding = self._embeddings.embed(signature)
        response = self._vectors.create_query(
            database_id=self._database_id,
            collection_id=self._collection_id,
            queries=[
                Query.equal("ecosystem", ecosystem),
                Query.equal("outcome", "success"),
                Query.vector_cosine("embedding", embedding),
                Query.limit(k),
            ],
        )
        hits = [
            hit
            for row in _rows(response)
            if (hit := _to_hit(row, embedding)) is not None and hit.score >= self._threshold
        ]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:k]


def _rows(response: Any) -> list[dict[str, Any]]:
    documents = response.get("documents") if isinstance(response, dict) else None
    if not isinstance(documents, list):
        return []
    return [row for row in documents if isinstance(row, dict)]


def _to_hit(row: dict[str, Any], query_embedding: list[float]) -> Hit | None:
    try:
        record = FailureRecord.model_validate(
            {key: value for key, value in row.items() if not key.startswith("$")}
        )
    except ValueError:
        return None
    return Hit(record=record, score=_score_of(row, query_embedding))


def _score_of(row: dict[str, Any], query_embedding: list[float]) -> float:
    for key in _SCORE_KEYS:
        value = row.get(key)
        if isinstance(value, int | float):
            # A distance counts down from identical; a similarity counts up.
            return 1.0 - float(value) if key in _DISTANCE_KEYS else float(value)
    stored = row.get("embedding")
    if isinstance(stored, list):
        return cosine_similarity(query_embedding, [float(value) for value in stored])
    return 0.0
