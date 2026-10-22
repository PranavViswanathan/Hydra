"""The structured response the repair step expects back from the model (§12)."""

from __future__ import annotations

import json
import re
from typing import Any, Final

from pydantic import BaseModel, Field, ValidationError

from vulnagent.core.errors import VulnAgentError
from vulnagent.core.models import FileMap

_FENCE: Final = re.compile(r"^\s*```[\w-]*\s*\n(?P<body>.*?)\n?\s*```\s*$", re.DOTALL)
_OBJECT: Final = re.compile(r"\{.*\}", re.DOTALL)


class RepairEdit(BaseModel):
    path: str
    search: str
    replace: str


class RepairResponse(BaseModel):
    analysis: str
    edits: list[RepairEdit] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    give_up: bool = False
    give_up_reason: str | None = None

    def apply_to(self, files: FileMap) -> FileMap:
        """Apply every edit, returning only the files that changed."""
        updated: FileMap = {}
        for edit in self.edits:
            current = updated.get(edit.path, files.get(edit.path))
            if current is None:
                raise VulnAgentError(f"edit targets {edit.path}, which was never fetched")
            occurrences = current.count(edit.search)
            if occurrences == 0:
                raise VulnAgentError(f"search text not found in {edit.path}")
            if occurrences > 1:
                raise VulnAgentError(
                    f"search text appears more than once in {edit.path} ({occurrences} times)"
                )
            updated[edit.path] = current.replace(edit.search, edit.replace, 1)
        return updated


def parse_repair_response(text: str) -> RepairResponse:
    """Parse the model's reply, with an error message fit to hand back to it."""
    payload = _extract_json(text)
    try:
        return RepairResponse.model_validate(payload)
    except ValidationError as error:
        raise VulnAgentError(
            f"the response did not match the contract: {_describe(error)}"
        ) from error


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise VulnAgentError("the model returned an empty response")

    fenced = _FENCE.match(stripped)
    if fenced is not None:
        stripped = fenced.group("body").strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = _OBJECT.search(stripped)
        if match is None:
            raise VulnAgentError("the response contained no JSON object") from None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as error:
            raise VulnAgentError(f"the response was not valid JSON: {error}") from error

    if not isinstance(payload, dict):
        raise VulnAgentError("the response JSON was not an object")
    return payload


def _describe(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or '(root)'}: {item['msg']}"
        for item in error.errors()
    )
