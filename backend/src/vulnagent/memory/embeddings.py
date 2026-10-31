"""Embeddings from Appwrite's own service, so no third-party key is needed.

The installed SDK exposes `embeddings.create_text_embeddings(texts, model)`
with two models: `all-minilm` (384 dimensions) and `nomic-embed-text` (768).
The dimension matters because it fixes the width of the VectorsDB column, so
it is declared here rather than guessed at bootstrap time.
"""

from __future__ import annotations

from typing import Any, Final, Protocol

from vulnagent.core.errors import ConfigError
from vulnagent.db.responses import plain

MODEL_DIMENSIONS: Final[dict[str, int]] = {
    "all-minilm": 384,
    "nomic-embed-text": 768,
}
DEFAULT_MODEL: Final = "all-minilm"


class EmbeddingsService(Protocol):
    """The slice of `appwrite.services.embeddings.Embeddings` this module uses."""

    def create_text_embeddings(self, texts: list[str], model: Any = None) -> Any: ...


class AppwriteEmbeddings:
    def __init__(self, *, embeddings: EmbeddingsService, model: str = DEFAULT_MODEL) -> None:
        if model not in MODEL_DIMENSIONS:
            raise ConfigError(
                f"unknown embedding model {model!r}; "
                f"Appwrite offers {', '.join(sorted(MODEL_DIMENSIONS))}"
            )
        self._embeddings = embeddings
        self._model = model
        self.dimensions = MODEL_DIMENSIONS[model]

    def embed(self, text: str) -> list[float]:
        response = plain(self._embeddings.create_text_embeddings(texts=[text], model=self._model))
        vector = _first_vector(response)
        if not vector:
            reason = _first_error(response)
            raise ConfigError(
                f"the embedding service returned nothing for model {self._model!r}"
                + (f": {reason}" if reason else "")
            )
        if len(vector) != self.dimensions:
            raise ConfigError(
                f"model {self._model!r} returned {len(vector)} dimensions, "
                f"expected {self.dimensions}"
            )
        return vector


def _first_vector(response: Any) -> list[float] | None:
    embeddings = response.get("embeddings") if isinstance(response, dict) else None
    if not isinstance(embeddings, list) or not embeddings:
        return None
    first = embeddings[0]
    values = first.get("embedding") if isinstance(first, dict) else first
    if not isinstance(values, list):
        return None
    try:
        return [float(value) for value in values]
    except (TypeError, ValueError):
        return None


def _first_error(response: Any) -> str:
    embeddings = response.get("embeddings") if isinstance(response, dict) else None
    first = embeddings[0] if isinstance(embeddings, list) and embeddings else None
    error = first.get("error") if isinstance(first, dict) else None
    return error if isinstance(error, str) else ""
