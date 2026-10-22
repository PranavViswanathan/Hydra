"""Anthropic implementation of :class:`LLMProvider`."""

from __future__ import annotations

from typing import Any, Final, Protocol, cast

MAX_TOKENS: Final = 4096
TEMPERATURE: Final = 0.0  # §12: the repair step must be reproducible


class MessagesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class AnthropicProvider:
    def __init__(self, *, messages: MessagesClient, model: str) -> None:
        self._messages = messages
        self._model = model

    @classmethod
    def from_api_key(cls, *, api_key: str, model: str) -> AnthropicProvider:
        from anthropic import Anthropic

        # The SDK's overloads are richer than the slice we use.
        return cls(messages=cast(MessagesClient, Anthropic(api_key=api_key).messages), model=model)

    def complete(self, *, system: str, user: str) -> str:
        response = self._messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return _text_of(response)


def _text_of(response: Any) -> str:
    blocks = getattr(response, "content", None)
    if not isinstance(blocks, list):
        return ""
    return "".join(
        str(block.text) for block in blocks if getattr(block, "type", None) == "text"
    ).strip()
