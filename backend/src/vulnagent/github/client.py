"""Everything the agent does to a repository, over the REST API (§4.3).

No `git` binary and no clone: files are read through the Contents API and
written through the Git Data API (blob, tree, commit, ref).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Final

import httpx

from vulnagent.core.errors import VulnAgentError
from vulnagent.core.models import FileMap
from vulnagent.core.safety import is_agent_branch
from vulnagent.github.auth import ACCEPT, API_ROOT, API_VERSION, DEFAULT_TIMEOUT

AGENT_LABEL: Final = "vulnagent"
NEEDS_HUMAN_LABEL: Final = "vulnagent:needs-human"


@dataclass(frozen=True, slots=True)
class Repository:
    owner: str
    name: str

    @classmethod
    def from_full_name(cls, full_name: str) -> Repository:
        owner, _, name = full_name.partition("/")
        if not owner or not name:
            raise VulnAgentError(f"not a repository full name: {full_name!r}")
        return cls(owner=owner, name=name)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    all_completed: bool
    all_passed: bool
    failed_job_ids: list[int]


class GitHubClient:
    def __init__(self, *, token: str, http: httpx.Client, api_root: str = API_ROOT) -> None:
        self._token = token
        self._http = http
        self._api_root = api_root.rstrip("/")

    # --- reading -----------------------------------------------------------

    def list_root_paths(self, repo: Repository, ref: str) -> list[str]:
        """Top-level file names, enough for adapter detection."""
        body = self._get(f"/repos/{repo.full_name}/contents", params={"ref": ref})
        if not isinstance(body, list):
            return []
        return [str(entry["name"]) for entry in body if isinstance(entry, dict) and "name" in entry]

    def get_file(self, repo: Repository, path: str, ref: str) -> str | None:
        body = self._get(f"/repos/{repo.full_name}/contents/{path}", params={"ref": ref})
        if not isinstance(body, dict) or body.get("encoding") != "base64":
            return None
        return base64.b64decode(str(body["content"])).decode("utf-8", errors="replace")

    def get_files(self, repo: Repository, paths: list[str], ref: str) -> FileMap:
        found: FileMap = {}
        for path in paths:
            contents = self.get_file(repo, path, ref)
            if contents is not None:
                found[path] = contents
        return found

    def head_sha(self, repo: Repository, branch: str) -> str:
        body = self._get(f"/repos/{repo.full_name}/git/ref/heads/{branch}")
        return str(body["object"]["sha"])

    def default_branch(self, repo: Repository) -> str:
        return str(self._get(f"/repos/{repo.full_name}")["default_branch"])

    # --- writing -----------------------------------------------------------

    def create_branch(self, repo: Repository, branch: str, from_sha: str) -> None:
        _require_agent_branch(branch)
        self._post(
            f"/repos/{repo.full_name}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": from_sha},
        )

    def commit_files(
        self, repo: Repository, *, branch: str, base_sha: str, files: FileMap, message: str
    ) -> str:
        """Write `files` as one commit on `branch`, returning the new head sha."""
        _require_agent_branch(branch)
        if not files:
            raise VulnAgentError("refusing to create an empty commit")

        base_commit = self._get(f"/repos/{repo.full_name}/git/commits/{base_sha}")
        tree = self._post(
            f"/repos/{repo.full_name}/git/trees",
            {
                "base_tree": str(base_commit["tree"]["sha"]),
                "tree": [
                    {"path": path, "mode": "100644", "type": "blob", "content": contents}
                    for path, contents in files.items()
                ],
            },
        )
        commit = self._post(
            f"/repos/{repo.full_name}/git/commits",
            {"message": message, "tree": str(tree["sha"]), "parents": [base_sha]},
        )
        new_sha = str(commit["sha"])
        self._patch(f"/repos/{repo.full_name}/git/refs/heads/{branch}", {"sha": new_sha})
        return new_sha

    # --- pull requests -----------------------------------------------------

    def open_pull_request(
        self, repo: Repository, *, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        _require_agent_branch(head)
        return self._post(
            f"/repos/{repo.full_name}/pulls",
            {"title": title, "body": body, "head": head, "base": base},
        )

    def update_pull_request_body(self, repo: Repository, number: int, body: str) -> None:
        self._patch(f"/repos/{repo.full_name}/pulls/{number}", {"body": body})

    def add_labels(self, repo: Repository, number: int, labels: list[str]) -> None:
        self._post(f"/repos/{repo.full_name}/issues/{number}/labels", {"labels": labels})

    def comment(self, repo: Repository, number: int, body: str) -> None:
        self._post(f"/repos/{repo.full_name}/issues/{number}/comments", {"body": body})

    def merge_pull_request(self, repo: Repository, number: int) -> None:
        self._put(f"/repos/{repo.full_name}/pulls/{number}/merge", {"merge_method": "squash"})

    # --- checks ------------------------------------------------------------

    def check_outcome(self, repo: Repository, sha: str) -> CheckOutcome:
        body = self._get(f"/repos/{repo.full_name}/commits/{sha}/check-runs")
        runs = body.get("check_runs") if isinstance(body, dict) else None
        if not isinstance(runs, list) or not runs:
            return CheckOutcome(all_completed=True, all_passed=True, failed_job_ids=[])

        completed = [run for run in runs if run.get("status") == "completed"]
        failed = [run for run in completed if run.get("conclusion") not in _PASSING_CONCLUSIONS]
        return CheckOutcome(
            all_completed=len(completed) == len(runs),
            all_passed=not failed,
            failed_job_ids=[int(run["id"]) for run in failed if "id" in run],
        )

    def job_log(self, repo: Repository, job_id: int) -> str:
        response = self._http.get(
            f"{self._api_root}/repos/{repo.full_name}/actions/jobs/{job_id}/logs",
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return ""
        response.raise_for_status()
        return response.text

    # --- plumbing ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": ACCEPT,
            "X-GitHub-Api-Version": API_VERSION,
        }

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        response = self._http.get(
            f"{self._api_root}{path}",
            headers=self._headers(),
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return {}
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", path, payload)

    def _patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send("PATCH", path, payload)

    def _put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send("PUT", path, payload)

    def _send(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._http.request(
            method,
            f"{self._api_root}{path}",
            headers=self._headers(),
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json() if response.content else {}
        return body if isinstance(body, dict) else {}


_PASSING_CONCLUSIONS: Final = frozenset({"success", "neutral", "skipped"})


def _require_agent_branch(branch: str) -> None:
    """Safety rule 1, at the only place that can violate it."""
    if not is_agent_branch(branch):
        raise VulnAgentError(f"refusing to write to {branch!r}: not a branch the agent created")
