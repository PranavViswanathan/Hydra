"""Provider protocols, so the agent never imports a vendor SDK directly."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    def complete(self, *, system: str, user: str) -> str:
        """Return the model's reply as text. Deterministic: temperature 0."""
        ...
