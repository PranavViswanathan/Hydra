import json

import pytest

from vulnagent.memory.base import FailureRecord, Hit, cosine_similarity
from vulnagent.memory.tables import TablesDBMemory
from vulnagent.memory.vectors import VectorsDBMemory

SIGNATURE = "TypeError: jwt.sign is not a function at src/auth.ts"


class StubEmbeddings:
    dimensions = 4

    def __init__(self, vectors: dict[str, list[float]] | None = None) -> None:
        self.vectors = vectors or {}
        self.embedded: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        return self.vectors.get(text, [1.0, 0.0, 0.0, 0.0])


class StubVectors:
    def __init__(self, documents: list[dict] | None = None) -> None:
        self.documents = documents or []
        self.created: list[dict] = []
        self.queries: list[list[str]] = []

    def create_document(self, database_id, collection_id, document_id, data):
        self.created.append(
            {"database_id": database_id, "collection_id": collection_id, "data": data}
        )
        return {"$id": document_id}

    def create_query(self, database_id, collection_id, queries=None):
        self.queries.append(queries or [])
        return {"documents": self.documents}


class StubTables:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.created: list[dict] = []

    def create_row(self, database_id, table_id, row_id, data):
        self.created.append({"table_id": table_id, "data": data})
        return {"$id": row_id}

    def list_rows(self, database_id, table_id, queries=None):
        return {"rows": self.rows}


def a_record(**overrides) -> FailureRecord:
    return FailureRecord(
        **{
            "ecosystem": "npm",
            "error_signature": SIGNATURE,
            "log_excerpt": "TypeError: jwt.sign is not a function",
            "package_changes": "jsonwebtoken 8.5.1->9.0.2",
            "fix_diff": "- jwt.sign(p)\n+ await jwt.sign(p)",
            "outcome": "success",
            "repo_full_name": "pranav/test-app",
            "run_id": "run_1",
            **overrides,
        }
    )


def a_row(score=None, **overrides) -> dict:
    row = {
        "$id": "doc1",
        "ecosystem": "npm",
        "error_signature": SIGNATURE,
        "log_excerpt": "TypeError",
        "package_changes": "jsonwebtoken 8.5.1->9.0.2",
        "fix_diff": "+ await",
        "outcome": "success",
        "repo_full_name": "pranav/test-app",
        "run_id": "run_1",
        **overrides,
    }
    if score is not None:
        row["$score"] = score
    return row


class TestCosineSimilarity:
    def test_identical_vectors_match_perfectly(self):
        assert cosine_similarity([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)

    def test_opposite_vectors_do_not_match(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_perpendicular_vectors_score_zero(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_a_zero_vector_scores_zero_rather_than_dividing_by_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_vectors_of_different_lengths_do_not_match(self):
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


class TestWhatGetsEmbedded:
    def test_embeds_the_signature_together_with_the_package_changes(self):
        record = a_record()

        assert record.embedding_text() == f"{SIGNATURE}\njsonwebtoken 8.5.1->9.0.2"

    def test_truncates_an_oversized_log_excerpt(self):
        record = a_record(log_excerpt="x" * 10_000)

        assert len(str(record.as_row([])["log_excerpt"])) <= 4096


class TestWritingToVectorsDb:
    def test_stores_the_record_with_its_embedding(self):
        memory = VectorsDBMemory(
            vectors=(vectors := StubVectors()),
            embeddings=StubEmbeddings(),
            database_id="vulnagent_vectors",
        )

        memory.add(a_record())

        assert vectors.created[0]["data"]["embedding"] == [1.0, 0.0, 0.0, 0.0]
        assert vectors.created[0]["data"]["fix_diff"] == "- jwt.sign(p)\n+ await jwt.sign(p)"

    def test_writes_into_the_ci_failures_collection(self):
        memory = VectorsDBMemory(
            vectors=(vectors := StubVectors()),
            embeddings=StubEmbeddings(),
            database_id="vulnagent_vectors",
        )

        memory.add(a_record())

        assert vectors.created[0]["collection_id"] == "ci_failures"


class TestSearchingVectorsDb:
    def memory(self, documents, threshold=0.80):
        return VectorsDBMemory(
            vectors=StubVectors(documents),
            embeddings=StubEmbeddings(),
            database_id="vulnagent_vectors",
            threshold=threshold,
        )

    def test_returns_a_close_enough_past_fix(self):
        hits = self.memory([a_row(score=0.93)]).search(SIGNATURE, ecosystem="npm")

        assert len(hits) == 1
        assert hits[0].record.fix_diff == "+ await"
        assert hits[0].score == pytest.approx(0.93)

    def test_drops_a_hit_below_the_similarity_threshold(self):
        assert self.memory([a_row(score=0.42)]).search(SIGNATURE, ecosystem="npm") == []

    def test_returns_the_closest_hits_first(self):
        hits = self.memory([a_row(score=0.85), a_row(score=0.97)]).search(
            SIGNATURE, ecosystem="npm"
        )

        assert [hit.score for hit in hits] == pytest.approx([0.97, 0.85])

    def test_returns_at_most_the_requested_number_of_hits(self):
        hits = self.memory([a_row(score=0.9) for _ in range(10)]).search(
            SIGNATURE, ecosystem="npm", k=3
        )

        assert len(hits) == 3

    def test_always_filters_by_ecosystem_and_successful_outcome(self):
        vectors = StubVectors([])
        memory = VectorsDBMemory(
            vectors=vectors, embeddings=StubEmbeddings(), database_id="vulnagent_vectors"
        )

        memory.search(SIGNATURE, ecosystem="npm")

        sent = " ".join(vectors.queries[0])
        assert '"ecosystem"' in sent
        assert '"npm"' in sent
        assert '"success"' in sent

    def test_ranks_by_cosine_distance_on_the_embedding_column(self):
        vectors = StubVectors([])
        memory = VectorsDBMemory(
            vectors=vectors, embeddings=StubEmbeddings(), database_id="vulnagent_vectors"
        )

        memory.search(SIGNATURE, ecosystem="npm")

        assert "vectorCosine" in " ".join(vectors.queries[0])

    def test_falls_back_to_computing_similarity_when_the_row_carries_no_score(self):
        row = a_row(embedding=[1.0, 0.0, 0.0, 0.0])

        hits = self.memory([row]).search(SIGNATURE, ecosystem="npm")

        assert hits[0].score == pytest.approx(1.0)

    def test_reads_a_distance_as_the_inverse_of_a_similarity(self):
        hits = self.memory([a_row(**{"$distance": 0.05})]).search(SIGNATURE, ecosystem="npm")

        assert hits[0].score == pytest.approx(0.95)

    def test_an_empty_signature_never_reaches_the_database(self):
        vectors = StubVectors([a_row(score=0.99)])
        memory = VectorsDBMemory(
            vectors=vectors, embeddings=StubEmbeddings(), database_id="vulnagent_vectors"
        )

        assert memory.search("   ", ecosystem="npm") == []
        assert vectors.queries == []

    def test_a_row_that_does_not_match_the_record_shape_is_skipped(self):
        assert (
            self.memory([{"$id": "x", "nonsense": True}]).search(SIGNATURE, ecosystem="npm") == []
        )


class TestTablesDbFallback:
    def test_stores_the_embedding_as_text_since_there_is_no_vector_column(self):
        memory = TablesDBMemory(
            tables=(tables := StubTables()), embeddings=StubEmbeddings(), database_id="vulnagent"
        )

        memory.add(a_record())

        assert json.loads(tables.created[0]["data"]["embedding"]) == [1.0, 0.0, 0.0, 0.0]

    def test_finds_the_closest_row_by_brute_force(self):
        rows = [
            a_row(embedding=json.dumps([0.0, 1.0, 0.0, 0.0]), fix_diff="far"),
            a_row(embedding=json.dumps([1.0, 0.0, 0.0, 0.0]), fix_diff="near"),
        ]
        memory = TablesDBMemory(
            tables=StubTables(rows), embeddings=StubEmbeddings(), database_id="vulnagent"
        )

        hits = memory.search(SIGNATURE, ecosystem="npm")

        assert [hit.record.fix_diff for hit in hits] == ["near"]

    def test_applies_the_same_similarity_threshold(self):
        rows = [a_row(embedding=json.dumps([0.0, 1.0, 0.0, 0.0]))]
        memory = TablesDBMemory(
            tables=StubTables(rows), embeddings=StubEmbeddings(), database_id="vulnagent"
        )

        assert memory.search(SIGNATURE, ecosystem="npm") == []

    def test_skips_a_row_whose_embedding_cannot_be_read(self):
        memory = TablesDBMemory(
            tables=StubTables([a_row(embedding="not json")]),
            embeddings=StubEmbeddings(),
            database_id="vulnagent",
        )

        assert memory.search(SIGNATURE, ecosystem="npm") == []

    def test_is_interchangeable_with_the_vectors_implementation(self):
        rows = [a_row(embedding=json.dumps([1.0, 0.0, 0.0, 0.0]))]
        memory = TablesDBMemory(
            tables=StubTables(rows), embeddings=StubEmbeddings(), database_id="vulnagent"
        )

        hits = memory.search(SIGNATURE, ecosystem="npm")

        assert isinstance(hits[0], Hit)
        assert hits[0].record.ecosystem == "npm"


class TestPresentingAHitToTheModel:
    def test_describes_the_past_fix_and_how_close_it_is(self):
        section = Hit(record=a_record(), score=0.91).as_prompt_section()

        assert "0.91" in section
        assert "jsonwebtoken 8.5.1->9.0.2" in section
        assert "await jwt.sign(p)" in section
