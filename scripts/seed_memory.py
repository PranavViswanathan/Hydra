#!/usr/bin/env python3
"""Seed the failure memory with npm failure-to-fix pairs (PROJECT.md 8).

    uv run python scripts/seed_memory.py

The jsonwebtoken entries deliberately match the breaking change in the test
target repo (8 to 9), so the first end-to-end run gets a memory hit rather
than starting cold.
"""

from __future__ import annotations

import sys

from appwrite.client import Client
from appwrite.services.embeddings import Embeddings
from appwrite.services.tables_db import TablesDB
from appwrite.services.vectors_db import VectorsDB

from vulnagent.agent.ci_logs import error_signature
from vulnagent.config.settings import load_settings
from vulnagent.db.rows import DATABASE_ID, VECTORS_DATABASE_ID
from vulnagent.memory.base import FailureMemory, FailureRecord
from vulnagent.memory.embeddings import AppwriteEmbeddings
from vulnagent.memory.tables import TablesDBMemory
from vulnagent.memory.vectors import VectorsDBMemory

SEEDS: list[tuple[str, str, str]] = [
    (
        "TypeError: jwt.sign is not a function\n    at signToken (src/auth.ts)",
        "jsonwebtoken 8.5.1->9.0.2",
        (
            "jsonwebtoken 9 removed the callable form of the default export.\n"
            "- import jwt from 'jsonwebtoken'\n"
            "+ import * as jwt from 'jsonwebtoken'\n"
            "and call jwt.sign(payload, secret, options) with an explicit algorithm."
        ),
    ),
    (
        "Error: secretOrPrivateKey must have a value\n    at Object.module.exports [as sign]",
        "jsonwebtoken 8.5.1->9.0.2",
        (
            "jsonwebtoken 9 validates the secret eagerly.\n"
            "- jwt.sign(payload, process.env.SECRET)\n"
            "+ jwt.sign(payload, requireEnv('SECRET'))"
        ),
    ),
    (
        "error TS2554: Expected 2 arguments, but got 1.\n    src/auth.ts",
        "jsonwebtoken 8.5.1->9.0.2",
        (
            "The v9 types require the options argument.\n"
            "- jwt.verify(token, secret)\n"
            "+ jwt.verify(token, secret, { algorithms: ['HS256'] })"
        ),
    ),
    (
        (
            "TypeError: Cannot read properties of undefined (reading 'parse')\n"
            "    at parseQuery (src/http.ts)"
        ),
        "qs 6.5.2->6.11.2",
        "qs 6.11 moved to named exports.\n- import qs from 'qs'\n+ import { parse } from 'qs'",
    ),
    (
        "FAIL src/utils.test.ts\nAssertionError: expected undefined to equal 3",
        "lodash 4.17.20->4.17.21",
        (
            "lodash 4.17.21 fixed _.template escaping; the test asserted the buggy output.\n"
            "Update the expectation to the corrected escaping rather than pinning lodash."
        ),
    ),
    (
        "npm ERR! ERESOLVE unable to resolve dependency tree\nnpm ERR! peer react@^17",
        "react 17.0.2->18.2.0",
        (
            "The peer range on a sibling package was too narrow.\n"
            "Bump the dependent package to the version that declares peer react ^18."
        ),
    ),
]


def build_memory() -> FailureMemory:
    settings = load_settings(dotenv=".env")
    client = (
        Client()
        .set_endpoint(settings.appwrite_endpoint)
        .set_project(settings.appwrite_project_id)
        .set_key(settings.appwrite_api_key.get_secret_value())
    )
    embeddings = AppwriteEmbeddings(
        embeddings=Embeddings(client), model=settings.embedding_model or "all-minilm"
    )

    vectors = VectorsDB(client)
    try:
        vectors.get(VECTORS_DATABASE_ID)
    except Exception:
        print("no vectors database; seeding the TablesDB fallback instead")
        return TablesDBMemory(
            tables=TablesDB(client), embeddings=embeddings, database_id=DATABASE_ID
        )
    return VectorsDBMemory(vectors=vectors, embeddings=embeddings, database_id=VECTORS_DATABASE_ID)


def main() -> int:
    memory = build_memory()

    for log, changes, fix in SEEDS:
        memory.add(
            FailureRecord(
                ecosystem="npm",
                error_signature=error_signature(log),
                log_excerpt=log,
                package_changes=changes,
                fix_diff=fix,
                outcome="success",
                repo_full_name="vulnagent/seed",
                run_id="seed",
            )
        )
        print(f"seeded: {changes}")

    print(f"\n{len(SEEDS)} memories written")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(f"seeding failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
