import json

import pytest
from appwrite.models.execution import Execution

from vulnagent.core.errors import VulnAgentError
from vulnagent.runtime import AppwriteLockfileRegenerator


def an_execution(response_body: str) -> Execution:
    return Execution.model_validate(
        {"trigger": "http", "status": "completed", "responseBody": response_body}
    )


class StubFunctions:
    def __init__(self, execution: Execution) -> None:
        self.execution = execution
        self.calls: list[dict] = []

    def create_execution(self, **kwargs):
        self.calls.append(kwargs)
        return self.execution


def a_regenerator(response_body: str) -> tuple[AppwriteLockfileRegenerator, StubFunctions]:
    functions = StubFunctions(an_execution(response_body))
    return AppwriteLockfileRegenerator(functions=functions, function_id="npm_lockfile"), functions


def test_returns_the_lockfile_the_helper_function_produced():
    regenerator, _ = a_regenerator(json.dumps({"package_lock": '{"lockfileVersion": 3}'}))

    files = regenerator.regenerate({"package.json": "{}", "package-lock.json": "{}"})

    assert files == {"package-lock.json": '{"lockfileVersion": 3}'}


def test_sends_both_manifests_to_the_helper_function():
    regenerator, functions = a_regenerator(json.dumps({"package_lock": "{}"}))

    regenerator.regenerate({"package.json": "manifest", "package-lock.json": "lock"})

    assert json.loads(functions.calls[0]["body"]) == {
        "package_json": "manifest",
        "package_lock": "lock",
    }


def test_reports_the_error_the_helper_function_returned():
    regenerator, _ = a_regenerator(json.dumps({"error": "npm install failed"}))

    with pytest.raises(VulnAgentError, match="npm install failed"):
        regenerator.regenerate({"package.json": "{}"})
