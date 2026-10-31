"""One Appwrite function serves every trigger, so it has to tell them apart.

The free plan allows two functions, so the six Python entry points share one
deployment. Internal tasks reach it over the same public URL as GitHub, which
is why they carry a signature.
"""

import json

import pytest

from vulnagent.entrypoints.main import main
from vulnagent.entrypoints.routing import destination
from vulnagent.entrypoints.tasks import SIGNATURE_HEADER, TaskQueue

KEY = b"server-api-key"


class StubFunctions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_execution(self, **kwargs):
        self.calls.append(kwargs)


def enqueued(task: str, payload: dict, *, key: bytes = KEY) -> dict:
    functions = StubFunctions()
    TaskQueue(functions=functions, function_id="hydra", key=key).enqueue(task, payload)  # type: ignore[arg-type]
    return functions.calls[0]


def route(
    *, trigger: str = "http", path: str = "/", headers: dict | None = None, body: bytes = b""
) -> str:
    return destination(trigger=trigger, path=path, headers=headers or {}, body=body, key=KEY)


class TestTheTaskQueue:
    def test_hands_the_task_to_this_same_function(self):
        assert enqueued("scan", {"repo_id": "r1"})["function_id"] == "hydra"

    def test_runs_the_task_asynchronously(self):
        assert enqueued("scan", {"repo_id": "r1"})["xasync"] is True

    def test_sends_the_payload_as_the_body(self):
        call = enqueued("agent_step", {"run_id": "run1", "expected_state": "QUEUED"})

        assert json.loads(call["body"]) == {"run_id": "run1", "expected_state": "QUEUED"}

    @pytest.mark.parametrize(
        ("task", "path"), [("scan", "/tasks/scan"), ("agent_step", "/tasks/agent-step")]
    )
    def test_addresses_each_task_by_its_own_path(self, task, path):
        assert enqueued(task, {})["path"] == path


class TestRoutingATask:
    @pytest.mark.parametrize("task", ["scan", "agent_step"])
    def test_a_task_the_queue_signed_reaches_its_handler(self, task):
        call = enqueued(task, {"repo_id": "r1"})

        assert route(path=call["path"], headers=call["headers"], body=call["body"].encode()) == task

    def test_a_task_without_a_signature_is_refused(self):
        assert route(path="/tasks/scan", body=b'{"repo_id": "r1"}') == "forbidden"

    def test_a_task_whose_body_was_changed_after_signing_is_refused(self):
        call = enqueued("scan", {"repo_id": "r1"})

        assert route(path="/tasks/scan", headers=call["headers"], body=b'{"repo_id": "r2"}') == (
            "forbidden"
        )

    def test_a_task_signed_with_another_key_is_refused(self):
        call = enqueued("scan", {"repo_id": "r1"}, key=b"someone-else")

        assert route(path=call["path"], headers=call["headers"], body=call["body"].encode()) == (
            "forbidden"
        )

    def test_a_missing_server_key_refuses_tasks_rather_than_accepting_any_signer(self):
        call = enqueued("scan", {"repo_id": "r1"}, key=b"")

        assert (
            destination(
                trigger="http",
                path=call["path"],
                headers=call["headers"],
                body=call["body"].encode(),
                key=b"",
            )
            == "forbidden"
        )

    def test_a_signature_for_one_task_does_not_open_an_unknown_task_path(self):
        call = enqueued("scan", {"repo_id": "r1"})

        assert route(path="/tasks/delete-everything", headers=call["headers"]) == "forbidden"

    def test_the_signature_travels_in_its_own_header(self):
        assert SIGNATURE_HEADER in enqueued("scan", {})["headers"]


class TestRoutingEverythingElse:
    def test_the_cron_trigger_runs_the_scheduler(self):
        assert route(trigger="schedule") == "scheduler"

    def test_a_database_event_is_a_new_vulnerability(self):
        assert route(trigger="event") == "vulnerability_created"

    def test_a_call_from_github_is_a_webhook(self):
        assert route(headers={"x-github-event": "push"}) == "github_webhook"

    def test_anything_else_is_the_dashboard_api(self):
        assert route(path="/repos/r1/scan") == "api"

    def test_a_github_header_cannot_smuggle_a_request_onto_a_task_path(self):
        assert route(path="/tasks/scan", headers={"x-github-event": "push"}) == "forbidden"


class StubRequest:
    def __init__(self, *, path: str, headers: dict, body: bytes) -> None:
        self.path = path
        self.headers = headers
        self.body_binary = body
        self.body_json = json.loads(body or b"{}")


class StubResponse:
    def json(self, payload, status=200):
        return status, payload


class StubContext:
    def __init__(self, request: StubRequest) -> None:
        self.req = request
        self.res = StubResponse()


def test_the_function_refuses_an_unsigned_task_before_touching_anything(monkeypatch):
    monkeypatch.setenv("APPWRITE_API_KEY", KEY.decode())
    context = StubContext(
        StubRequest(path="/tasks/agent-step", headers={}, body=b'{"run_id": "run1"}')
    )

    status, _ = main(context)

    assert status == 403
