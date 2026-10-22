"""Turn a GitHub Actions job log into something a model and a vector search can use (§9.3).

Three jobs: pull out the lines that describe the failure, normalise them into a
signature stable across runs (so the same breakage matches a past fix), and
list the repository files worth sending as context.
"""

from __future__ import annotations

import re
from typing import Final

from vulnagent.core.safety import redact_secrets

MAX_EXCERPT_BYTES: Final = 4096
MAX_SIGNATURE_CHARS: Final = 1000
MAX_CONTEXT_FILES: Final = 5

_TIMESTAMP: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
_WORKFLOW_COMMAND: Final = re.compile(r"^##\[(?:group|endgroup|debug|command)]")

_INTERESTING: Final = (
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\bFAIL(?:ED)?\b"),
    re.compile(r"\b\w*(?:Error|Exception)\b"),
    re.compile(r"^npm ERR!"),
    re.compile(r"^\s+at\s"),
    re.compile(r"\bTS\d{4}\b"),
    re.compile(r"\bAssertionError\b"),
    re.compile(r"^\s*(?:Expected|Received|expected|actual)[:\s]"),
)

# Noise that changes between runs and would break signature matching.
_NORMALISERS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "<hash>"),
    (re.compile(r"/tmp/[\w.-]+"), "/tmp/<temp>"),
    (re.compile(r"(?:/[\w.-]+)*?/(?:work|home|runner|Users)/(?:[\w.-]+/)*?(?=src/|tests?/)"), ""),
    (re.compile(r"^(?:/[\w.-]+)+/(?=[\w.-]+\.\w+)"), ""),
    (re.compile(r":\d+:\d+"), ""),
    (re.compile(r"\(\d+,\d+\)"), ""),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|m)\b"), "<duration>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][\d:.]+\b"), "<time>"),
    (re.compile(r"\s+"), " "),
)

# A path only counts if it ends in a source extension, so `jwt.sign` in an
# error message is not mistaken for a file.
_PATH_TOKEN: Final = re.compile(r"[\w./@-]+\.(?:[cm]?[jt]sx?|json|vue|svelte)\b")
# Where the checkout starts inside an absolute runner path.
_REPO_ROOT: Final = re.compile(r"/(?:src|lib|app|tests?)/")


def extract_excerpt(log: str) -> str:
    """The error-shaped lines of a job log, redacted and capped at 4 KB."""
    lines = [_strip_prefix(line) for line in log.splitlines()]
    lines = [line for line in lines if line.strip() and not _WORKFLOW_COMMAND.match(line)]

    interesting = [line for line in lines if _is_interesting(line)]
    chosen = interesting or lines[-40:]
    return redact_secrets(_tail_within_budget(chosen))


def error_signature(excerpt: str) -> str:
    """A normalised fingerprint of a failure, stable across runs of the same break."""
    if not excerpt.strip():
        return ""
    signature = "\n".join(_strip_prefix(line).strip() for line in excerpt.splitlines())
    for pattern, replacement in _NORMALISERS:
        signature = pattern.sub(replacement, signature)
    return signature.strip()[:MAX_SIGNATURE_CHARS]


def referenced_repo_files(excerpt: str) -> list[str]:
    """Repository files named in the failure, worth sending to the model as context."""
    found: list[str] = []
    for line in excerpt.splitlines():
        for path in _paths_in(line):
            if "node_modules/" in path or path in found:
                continue
            found.append(path)
            if len(found) >= MAX_CONTEXT_FILES:
                return found
    return found


def _paths_in(line: str) -> list[str]:
    found: list[str] = []
    for match in _PATH_TOKEN.finditer(line):
        path = _repo_relative(match.group(0))
        if path is not None:
            found.append(path)
    return found


def _repo_relative(token: str) -> str | None:
    """Cut a runner's absolute path back to its repository-relative part."""
    if token.startswith("/"):
        roots = list(_REPO_ROOT.finditer(token))
        if not roots:
            return None
        token = token[roots[-1].start() + 1 :]
    token = token.removeprefix("./")
    if token.startswith("/") or "/" not in token:
        return None
    return token


def _strip_prefix(line: str) -> str:
    return _TIMESTAMP.sub("", line)


def _is_interesting(line: str) -> bool:
    return any(pattern.search(line) for pattern in _INTERESTING)


def _tail_within_budget(lines: list[str]) -> str:
    """Keep the most recent lines that fit: the last failure explains the run."""
    kept: list[str] = []
    budget = MAX_EXCERPT_BYTES
    for line in reversed(lines):
        cost = len(line.encode()) + 1
        if cost > budget:
            break
        kept.append(line)
        budget -= cost
    return "\n".join(reversed(kept))
