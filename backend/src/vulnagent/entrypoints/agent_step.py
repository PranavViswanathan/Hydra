"""Async entry point: advance one agent run by one transition (§10)."""

from __future__ import annotations

from typing import Any

from vulnagent.agent.steps import AgentSteps
from vulnagent.runtime import build_context


def handle(context: Any) -> Any:
    payload = context.req.body_json or {}
    run_id = str(payload.get("run_id", ""))
    expected_state = payload.get("expected_state")
    event = payload.get("event")

    app = build_context()
    try:
        run = app.db.runs.get(run_id)
        if run is None:
            return context.res.json({"error": f"no run {run_id}"}, 404)

        # §9.5: a stale execution must not act on a run that has moved on.
        if expected_state is not None and run.state != expected_state:
            context.log(f"run {run_id} is {run.state}, not {expected_state}; stopping")
            return context.res.json({"status": "stale"})

        repo = app.db.repos.get(run.repo_id)
        installation = app.db.installations.get(repo.installation_id) if repo is not None else None
        if repo is None or installation is None:
            return context.res.json({"error": "the repository or installation is gone"}, 409)

        steps = AgentSteps(
            db=app.db,
            github=app.github_for(installation.github_installation_id),
            registry=app.registry,
            regenerator=app.lockfile_regenerator(),
            llm=app.llm(),
            memory=app.memory(),
        )
        outcome = steps.advance(run, event=event)
        context.log(f"run {run_id} -> {outcome.state}")

        if outcome.reschedule:
            app.enqueue("agent_step", {"run_id": run_id, "expected_state": outcome.state})

        return context.res.json({"state": outcome.state, "message": outcome.message})
    finally:
        app.close()
