#!/usr/bin/env python3
"""Create the VectorsDB database and the `ci_failures` collection (PROJECT.md 8).

    uv run python scripts/bootstrap_vectors.py

This is M0 Spike A. If creation fails because VectorsDB needs a dedicated
database on this plan, the script says so and exits 2 rather than pretending:
the options are self-hosting, paying for a dedicated database, or running the
TablesDBMemory fallback, which the agent supports without any code change.
"""

from __future__ import annotations

import sys

from appwrite.client import Client
from appwrite.enums.vectors_db_index_type import VectorsDBIndexType
from appwrite.services.vectors_db import VectorsDB

from vulnagent.config.settings import load_settings
from vulnagent.db.rows import VECTORS_DATABASE_ID
from vulnagent.memory.base import COLLECTION
from vulnagent.memory.embeddings import MODEL_DIMENSIONS

DEDICATED_HINTS = ("dedicated", "plan", "upgrade", "not available")


def main() -> int:
    settings = load_settings(dotenv=".env")
    model = settings.embedding_model or "all-minilm"
    if model not in MODEL_DIMENSIONS:
        print(f"EMBEDDING_MODEL must be one of {sorted(MODEL_DIMENSIONS)}", file=sys.stderr)
        return 1

    dimension = MODEL_DIMENSIONS[model]
    if settings.embedding_dim and settings.embedding_dim != dimension:
        print(
            f"EMBEDDING_DIM is {settings.embedding_dim} but {model} produces {dimension}",
            file=sys.stderr,
        )
        return 1

    client = (
        Client()
        .set_endpoint(settings.appwrite_endpoint)
        .set_project(settings.appwrite_project_id)
        .set_key(settings.appwrite_api_key.get_secret_value())
    )
    vectors = VectorsDB(client)

    try:
        vectors.get(VECTORS_DATABASE_ID)
        print(f"database {VECTORS_DATABASE_ID}: present")
    except Exception as error:
        if not _create_database(vectors, error):
            return 2

    try:
        vectors.get_collection(VECTORS_DATABASE_ID, COLLECTION)
        print(f"collection {COLLECTION}: present")
    except Exception:
        vectors.create_collection(
            database_id=VECTORS_DATABASE_ID,
            collection_id=COLLECTION,
            name="CI failures",
            dimension=dimension,
        )
        print(f"collection {COLLECTION}: created with dimension {dimension}")

    try:
        vectors.create_index(
            database_id=VECTORS_DATABASE_ID,
            collection_id=COLLECTION,
            key="embedding_cosine",
            type=VectorsDBIndexType.HNSW_COSINE,
            attributes=["embedding"],
        )
        print("index embedding_cosine: created")
    except Exception:
        print("index embedding_cosine: present")

    print("\nSpike A passed: VectorsDB is usable. Record the outcome in docs/DECISIONS.md.")
    return 0


def _create_database(vectors: VectorsDB, previous: Exception) -> bool:
    try:
        vectors.create(database_id=VECTORS_DATABASE_ID, name="VulnAgent vectors")
    except Exception as error:
        message = str(error).lower()
        print(f"\ncould not create the vectors database: {error}", file=sys.stderr)
        if any(hint in message for hint in DEDICATED_HINTS):
            print(
                "\nThis looks like the dedicated-database limit from PROJECT.md section 8.\n"
                "Stop and choose one of: self-host Appwrite, pay for a dedicated database,\n"
                "or run with TablesDBMemory (leave the vectors database absent and the\n"
                "runtime falls back to it automatically).",
                file=sys.stderr,
            )
        return False
    print(f"database {VECTORS_DATABASE_ID}: created (previous probe said: {previous})")
    return True


if __name__ == "__main__":
    raise SystemExit(main())
