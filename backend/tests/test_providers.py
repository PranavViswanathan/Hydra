import pytest
from appwrite.models.embedding_list import EmbeddingList

from vulnagent.core.errors import ConfigError
from vulnagent.llm.anthropic_provider import AnthropicProvider
from vulnagent.memory.embeddings import MODEL_DIMENSIONS, AppwriteEmbeddings


class StubBlock:
    def __init__(self, text: str, kind: str = "text") -> None:
        self.text = text
        self.type = kind


class StubResponse:
    def __init__(self, *blocks: StubBlock) -> None:
        self.content = list(blocks)


class StubMessages:
    def __init__(self, response: StubResponse | None = None) -> None:
        self.response = response or StubResponse(StubBlock('{"analysis": "x", "edits": []}'))
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class StubEmbeddingsService:
    def __init__(self, response=None) -> None:
        self.response = response if response is not None else {"embeddings": [{"embedding": []}]}
        self.calls: list[dict] = []

    def create_text_embeddings(self, texts, model=None):
        self.calls.append({"texts": texts, "model": model})
        return self.response


class TestAnthropicProvider:
    def test_returns_the_text_the_model_produced(self):
        provider = AnthropicProvider(messages=StubMessages(), model="claude-opus-5")

        assert provider.complete(system="s", user="u") == '{"analysis": "x", "edits": []}'

    def test_asks_for_the_configured_model(self):
        provider = AnthropicProvider(messages=(messages := StubMessages()), model="claude-opus-5")

        provider.complete(system="s", user="u")

        assert messages.calls[0]["model"] == "claude-opus-5"

    def test_repairs_are_deterministic(self):
        provider = AnthropicProvider(messages=(messages := StubMessages()), model="m")

        provider.complete(system="s", user="u")

        assert messages.calls[0]["temperature"] == 0.0

    def test_sends_the_system_prompt_separately_from_the_user_content(self):
        provider = AnthropicProvider(messages=(messages := StubMessages()), model="m")

        provider.complete(system="rules", user="context")

        assert messages.calls[0]["system"] == "rules"
        assert messages.calls[0]["messages"] == [{"role": "user", "content": "context"}]

    def test_joins_several_text_blocks(self):
        response = StubResponse(StubBlock("part one "), StubBlock("part two"))
        provider = AnthropicProvider(messages=StubMessages(response), model="m")

        assert provider.complete(system="s", user="u") == "part one part two"

    def test_ignores_blocks_that_are_not_text(self):
        response = StubResponse(StubBlock("keep"), StubBlock("drop", kind="thinking"))
        provider = AnthropicProvider(messages=StubMessages(response), model="m")

        assert provider.complete(system="s", user="u") == "keep"

    def test_an_empty_reply_is_an_empty_string_rather_than_a_crash(self):
        provider = AnthropicProvider(messages=StubMessages(StubResponse()), model="m")

        assert provider.complete(system="s", user="u") == ""


def an_embedding_list(*vectors: list[float], error: str = "") -> EmbeddingList:
    return EmbeddingList.model_validate(
        {
            "total": len(vectors),
            "embeddings": [
                {"model": "all-minilm", "dimension": len(v), "embedding": v, "error": error}
                for v in vectors
            ],
        }
    )


class TestAppwriteEmbeddings:
    def vector(self, size: int) -> EmbeddingList:
        return an_embedding_list([0.1] * size)

    def test_knows_the_width_of_the_model_it_was_given(self):
        provider = AppwriteEmbeddings(embeddings=StubEmbeddingsService(), model="all-minilm")

        assert provider.dimensions == MODEL_DIMENSIONS["all-minilm"]

    def test_the_other_model_has_a_different_width(self):
        provider = AppwriteEmbeddings(embeddings=StubEmbeddingsService(), model="nomic-embed-text")

        assert provider.dimensions == 768

    def test_refuses_a_model_appwrite_does_not_offer(self):
        with pytest.raises(ConfigError, match="text-embedding-3-small"):
            AppwriteEmbeddings(embeddings=StubEmbeddingsService(), model="text-embedding-3-small")

    def test_returns_the_vector_for_the_text(self):
        service = StubEmbeddingsService(self.vector(384))
        provider = AppwriteEmbeddings(embeddings=service, model="all-minilm")

        assert len(provider.embed("some error")) == 384

    def test_asks_the_service_for_exactly_the_text_given(self):
        service = StubEmbeddingsService(self.vector(384))
        provider = AppwriteEmbeddings(embeddings=service, model="all-minilm")

        provider.embed("some error")

        assert service.calls[0]["texts"] == ["some error"]

    def test_refuses_a_vector_of_the_wrong_width(self):
        service = StubEmbeddingsService(self.vector(100))
        provider = AppwriteEmbeddings(embeddings=service, model="all-minilm")

        with pytest.raises(ConfigError, match="384"):
            provider.embed("some error")

    def test_refuses_an_empty_response(self):
        provider = AppwriteEmbeddings(
            embeddings=StubEmbeddingsService({"embeddings": []}), model="all-minilm"
        )

        with pytest.raises(ConfigError):
            provider.embed("some error")

    def test_reports_the_reason_appwrite_gives_for_an_empty_vector(self):
        service = StubEmbeddingsService(an_embedding_list([], error="model is still loading"))
        provider = AppwriteEmbeddings(embeddings=service, model="all-minilm")

        with pytest.raises(ConfigError, match="model is still loading"):
            provider.embed("some error")

    def test_accepts_a_bare_list_of_numbers_as_well_as_a_wrapped_one(self):
        service = StubEmbeddingsService({"embeddings": [[0.1] * 384]})
        provider = AppwriteEmbeddings(embeddings=service, model="all-minilm")

        assert len(provider.embed("some error")) == 384
