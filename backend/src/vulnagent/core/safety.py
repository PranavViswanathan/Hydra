"""The safety rules from §11, enforced in code rather than in a prompt.

The model is asked to behave in the repair prompt (§12); this module is what
actually stops it. Every rule here has a test in `tests/test_safety.py`.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final

from vulnagent.core.adapter import EcosystemAdapter

BRANCH_PREFIX: Final = "vulnagent/"

MAX_CHANGED_LINES: Final = 200
MAX_CHANGED_FILES: Final = 10
MAX_RETRY_CEILING: Final = 5

# Rule 2: files the agent owns. The LLM fixes application code, never the
# inputs the deterministic half of the agent produced.
_PROTECTED_PREFIXES: Final = (".github/",)
_PROTECTED_NAMES: Final = (".vulnagent.yml", ".vulnagent.yaml", ".vulnagent.json")

# Rule 3: markers that disable a check rather than fix it.
_WEAKENING_PATTERNS: Final = (
    re.compile(r"\b(?:it|test|describe|context)\s*\.\s*(?:skip|only|todo|failing)\b"),
    re.compile(r"\b(?:xit|xtest|xdescribe|fit|fdescribe)\s*\("),
    re.compile(r"@ts-(?:ignore|expect-error|nocheck)"),
    re.compile(r"eslint-disable"),
    re.compile(r"\bistanbul\s+ignore\b"),
)

_TEST_DECLARATION: Final = re.compile(r"\b(?:it|test|describe|context)\s*\(")

# Rule 6: credential shapes that must never reach the model.
_SECRET_PATTERNS: Final = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{3,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_?KEY|CREDENTIAL)[A-Z0-9_]*\s*[:=]\s*\S{8,}",
        re.IGNORECASE,
    ),
)

REDACTION: Final = "[redacted]"


@dataclass(frozen=True, slots=True)
class SafetyReport:
    ok: bool
    reason: str = ""

    @classmethod
    def refused(cls, reason: str) -> SafetyReport:
        return cls(ok=False, reason=reason)


def is_agent_branch(branch: str) -> bool:
    """Rule 1: the agent only ever pushes to branches it created."""
    if not branch.startswith(BRANCH_PREFIX):
        return False
    remainder = branch[len(BRANCH_PREFIX) :]
    return bool(remainder) and ".." not in remainder and not remainder.startswith("/")


def review_edits(edits: list[dict[str, Any]], *, adapter: EcosystemAdapter) -> SafetyReport:
    """Rules 2, 3 and 4 over one repair attempt's worth of edits."""
    touched: set[str] = set()
    changed_lines = 0

    for item in edits:
        path = str(item.get("path", ""))
        search = str(item.get("search", ""))
        replace = str(item.get("replace", ""))

        refusal = _check_path(path, adapter) or _check_weakening(search, replace)
        if refusal is not None:
            return refusal

        touched.add(path)
        changed_lines += _line_count(search) + _line_count(replace)

    if len(touched) > MAX_CHANGED_FILES:
        return SafetyReport.refused(
            f"touches {len(touched)} files, more than the limit of {MAX_CHANGED_FILES}"
        )
    if changed_lines > MAX_CHANGED_LINES:
        return SafetyReport.refused(
            f"changes {changed_lines} lines, more than the limit of {MAX_CHANGED_LINES}"
        )
    return SafetyReport(ok=True)


def redact_secrets(text: str) -> str:
    """Rule 6: strip anything credential-shaped before logs reach the model."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTION, text)
    return text


def capped_retries(configured: int) -> int:
    """Rule 7: the repo chooses, within a ceiling it cannot raise."""
    return max(0, min(configured, MAX_RETRY_CEILING))


def verify_webhook_signature(body: bytes, header: str | None, secret: bytes) -> bool:
    """Rule 9: constant-time check of `X-Hub-Signature-256` before anything else."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256=") :], expected)


def _check_path(path: str, adapter: EcosystemAdapter) -> SafetyReport | None:
    if not path:
        return SafetyReport.refused("an edit has no path")
    if _escapes_repository(path):
        return SafetyReport.refused(f"{path} is outside the repository")
    if adapter.is_manifest_path(path):
        return SafetyReport.refused(f"{path} is a manifest the agent itself maintains")
    if path in _PROTECTED_NAMES or path.startswith(_PROTECTED_PREFIXES):
        return SafetyReport.refused(f"{path} is protected from model edits")
    return None


def _check_weakening(search: str, replace: str) -> SafetyReport | None:
    for pattern in _WEAKENING_PATTERNS:
        if pattern.search(replace) and not pattern.search(search):
            return SafetyReport.refused(
                f"the replacement disables a check ({pattern.pattern}) instead of fixing it"
            )
    removed = _count(_TEST_DECLARATION, search) - _count(_TEST_DECLARATION, replace)
    if removed > 0:
        return SafetyReport.refused(f"the edit removes {removed} test declaration(s)")
    return None


def _escapes_repository(path: str) -> bool:
    if path.startswith("/") or path.startswith("~"):
        return True
    parts = PurePosixPath(path).parts
    return ".." in parts


def _count(pattern: re.Pattern[str], text: str) -> int:
    return len(pattern.findall(text))


def _line_count(text: str) -> int:
    return len(text.splitlines()) if text else 0
