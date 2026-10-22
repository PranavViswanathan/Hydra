"""The failure memory interface (§8).

The agent must not care whether memories live in VectorsDB or in a TablesDB
fallback, so everything above this module talks to `FailureMemory`.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

type Outcome = Literal["success", "failed"]

COLLECTION: Final = "ci_failures"
DEFAULT_TOP_K: Final = 3
DEFAULT_THRESHOLD: Final = 0.80
MAX_LOG_EXCERPT_BYTES: Final = 4096


class FailureRecord(BaseModel):
    ecosystem: str
    error_signature: str
    log_excerpt: str = ""
    package_changes: str = ""
    fix_diff: str = ""
    outcome: Outcome = "success"
    repo_full_name: str = ""
    run_id: str = ""
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def embedding_text(self) -> str:
        """What gets embedded: the normalised error plus what changed around it."""
        return f"{self.error_signature}\n{self.package_changes}"

    def as_row(self, embedding: list[float]) -> dict[str, object]:
        return {
            "embedding": embedding,
            "ecosystem": self.ecosystem,
            "error_signature": self.error_signature,
            "log_excerpt": self.log_excerpt.encode()[:MAX_LOG_EXCERPT_BYTES].decode(
                errors="ignore"
            ),
            "package_changes": self.package_changes,
            "fix_diff": self.fix_diff,
            "outcome": self.outcome,
            "repo_full_name": self.repo_full_name,
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
        }


class Hit(BaseModel):
    record: FailureRecord
    score: float

    def as_prompt_section(self) -> str:
        return (
            f"Similarity {self.score:.2f}. "
            f"Packages changed: {self.record.package_changes or 'unknown'}.\n"
            f"Error was:\n{self.record.error_signature}\n"
            f"Fix that worked:\n{self.record.fix_diff}"
        )


@runtime_checkable
class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class FailureMemory(Protocol):
    def add(self, record: FailureRecord) -> None: ...

    def search(self, signature: str, *, ecosystem: str, k: int = DEFAULT_TOP_K) -> list[Hit]: ...


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    magnitude = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / magnitude if magnitude else 0.0
