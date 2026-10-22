"""The CI-repair prompt (§12).

The system prompt states the rules; `core.safety` is what enforces them. Both
exist because a model that is told not to weaken a test still sometimes does.
"""

from __future__ import annotations

from typing import Final

from vulnagent.core.models import FileMap
from vulnagent.core.safety import redact_secrets

REPAIR_SYSTEM_PROMPT: Final = """\
You are a senior engineer fixing a CI failure caused by a dependency security \
upgrade. The dependency versions in the manifest and lockfile are already \
correct and are not up for discussion: your job is to change application or \
test code so it works with the new versions.

Rules:
- Do not downgrade, pin or otherwise change any dependency version.
- Do not edit manifests, lockfiles or CI configuration. Those files are \
maintained by the agent and your edits to them will be rejected.
- Do not weaken tests. Never skip, delete or mark a test as only/todo, and \
never add @ts-ignore, @ts-expect-error or eslint-disable to silence an error.
- Prefer the smallest change that makes the failure go away. If the upgrade \
introduced a breaking API change, adapt the calling code to the new API.
- If the failure has nothing to do with the upgrade, or you cannot fix it \
without breaking one of these rules, set give_up to true and explain why.

Respond with strict JSON only, matching this shape exactly:

{
  "analysis": "short root-cause explanation, at most 3 sentences",
  "edits": [
    {"path": "src/auth.ts", "search": "exact existing text", "replace": "new text"}
  ],
  "confidence": 0.0,
  "give_up": false,
  "give_up_reason": null
}

Each `search` string must appear exactly once in the file it targets. Include \
enough surrounding context to make it unique. Do not wrap the JSON in \
markdown fences or add any prose around it.\
"""

_NONE: Final = "(none)"


def build_repair_prompt(
    *,
    upgrade_plan: str,
    log_excerpt: str,
    similar_fixes: list[str],
    files: FileMap,
    ecosystem_hints: list[str],
    attempt: int,
    max_attempts: int,
    previous_attempts: list[str],
) -> str:
    sections = [
        _section("UPGRADE_PLAN", upgrade_plan),
        _section("CI_LOG_EXCERPT", log_excerpt),
        _section("SIMILAR_PAST_FIXES", _numbered(similar_fixes)),
        _section("FILES", _files(files)),
        _section("ECOSYSTEM_HINTS", _bulleted(ecosystem_hints)),
        _section("ATTEMPT", f"{attempt} of {max_attempts}"),
        _section("PREVIOUS_ATTEMPTS", _numbered(previous_attempts)),
    ]
    return redact_secrets("\n\n".join(sections))


def _section(name: str, body: str) -> str:
    return f"## {name}\n{body.strip() or _NONE}"


def _numbered(items: list[str]) -> str:
    return "\n\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _bulleted(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _files(files: FileMap) -> str:
    return "\n\n".join(f"### {path}\n```\n{contents}\n```" for path, contents in files.items())
