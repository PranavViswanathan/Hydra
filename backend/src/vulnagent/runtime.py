"""Composition root: build everything a function execution needs from env vars.

Each Appwrite function's `main.py` stays thin by calling `build_context()` and
then handing the pieces to the core.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

import httpx
from appwrite.client import Client
from appwrite.services.embeddings import Embeddings
from appwrite.services.functions import Functions
from appwrite.services.tables_db import TablesDB
from appwrite.services.vectors_db import VectorsDB

from vulnagent.adapters.npm.registry import NpmRegistryClient
from vulnagent.config.settings import Settings, load_settings
from vulnagent.core.errors import ConfigError, VulnAgentError
from vulnagent.core.models import FileMap
from vulnagent.db.repositories import Database
from vulnagent.db.responses import plain
from vulnagent.db.rows import VECTORS_DATABASE_ID
from vulnagent.github.auth import GitHubAppAuth
from vulnagent.github.client import GitHubClient
from vulnagent.llm.anthropic_provider import AnthropicProvider
from vulnagent.llm.base import LLMProvider
from vulnagent.memory.base import FailureMemory
from vulnagent.memory.embeddings import AppwriteEmbeddings
from vulnagent.memory.tables import TablesDBMemory
from vulnagent.memory.vectors import VectorsDBMemory
from vulnagent.osv.client import OsvClient

LOCKFILE_TIMEOUT: Final = 300


@dataclass
class Context:
    settings: Settings
    http: httpx.Client
    client: Client
    db: Database
    osv: OsvClient
    registry: NpmRegistryClient
    auth: GitHubAppAuth
    functions: Functions

    def github_for(self, installation_id: int) -> GitHubClient:
        return GitHubClient(token=self.auth.token_for(installation_id), http=self.http)

    def llm(self) -> LLMProvider | None:
        try:
            api_key, model = self.settings.require_llm()
        except ConfigError:
            return None
        return AnthropicProvider.from_api_key(api_key=api_key.get_secret_value(), model=model)

    def memory(self) -> FailureMemory | None:
        """VectorsDB when the project has one, the TablesDB fallback otherwise (§8)."""
        model = self.settings.embedding_model
        if not model:
            return None
        embeddings = AppwriteEmbeddings(embeddings=Embeddings(self.client), model=model)
        vectors = VectorsDB(self.client)
        try:
            vectors.get(VECTORS_DATABASE_ID)
        except Exception:
            return TablesDBMemory(
                tables=TablesDB(self.client),
                embeddings=embeddings,
                database_id="vulnagent",
            )
        return VectorsDBMemory(
            vectors=vectors, embeddings=embeddings, database_id=VECTORS_DATABASE_ID
        )

    def lockfile_regenerator(self) -> AppwriteLockfileRegenerator:
        return AppwriteLockfileRegenerator(
            functions=self.functions,
            function_id=self.settings.require_npm_lockfile_function_id(),
        )

    def enqueue(self, function_id: str, payload: dict[str, Any]) -> None:
        """Hand work to another function and return; webhooks must stay fast."""
        self.functions.create_execution(
            function_id=function_id, body=json.dumps(payload), xasync=True
        )

    def close(self) -> None:
        self.http.close()


class AppwriteLockfileRegenerator:
    """Runs the Node helper function that owns `npm install` (§6.4)."""

    def __init__(self, *, functions: Functions, function_id: str) -> None:
        self._functions = functions
        self._function_id = function_id

    def regenerate(self, files: FileMap) -> FileMap:
        execution = self._functions.create_execution(
            function_id=self._function_id,
            body=json.dumps(
                {
                    "package_json": files.get("package.json", ""),
                    "package_lock": files.get("package-lock.json", ""),
                }
            ),
            xasync=False,
            path="/",
            method="POST",
        )
        body = _response_body(execution)
        if "package_lock" not in body:
            raise VulnAgentError(f"lockfile regeneration failed: {body.get('error', body)}")
        return {"package-lock.json": str(body["package_lock"])}


def build_context(*, dotenv: str | None = None) -> Context:
    settings = load_settings(dotenv=dotenv)
    client = (
        Client()
        .set_endpoint(settings.appwrite_endpoint)
        .set_project(settings.appwrite_project_id)
        .set_key(settings.appwrite_api_key.get_secret_value())
    )
    http = httpx.Client()
    return Context(
        settings=settings,
        http=http,
        client=client,
        db=Database(TablesDB(client)),
        osv=OsvClient(base_url=settings.osv_base_url, http=http),
        registry=NpmRegistryClient(http=http),
        auth=GitHubAppAuth(
            app_id=settings.github_app_id,
            private_key=settings.github_app_private_key.get_secret_value(),
            http=http,
        ),
        functions=Functions(client),
    )


def _response_body(response: Any) -> dict[str, Any]:
    execution = plain(response)
    raw = execution.get("responseBody") if isinstance(execution, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": raw[:200]}
    return body if isinstance(body, dict) else {}
