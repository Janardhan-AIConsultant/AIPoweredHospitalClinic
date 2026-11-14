import json
from datetime import date
from types import SimpleNamespace

import pytest

from app.ai.llm import Message, MockLLM
from app.core.config import Settings
from app.rag.chunking import MAX_CHUNK_CHARS, chunk_markdown, load_knowledge
from app.rag.embeddings import HashingEmbedder
from app.rag.retriever import KNOWLEDGE_DIR, ClinicInfoRetriever, build_retriever
from app.rag.store import ChromaVectorStore, InMemoryVectorStore


def make() -> ClinicInfoRetriever:
    r = ClinicInfoRetriever(HashingEmbedder(), InMemoryVectorStore())
    r.ingest()
    return r


# ------------------------------------------------------------------ chunking
def test_chunking_by_section_strips_comments_and_is_stable():
    md = "# T\n<!-- hidden -->\nintro ignored? no\n\n## A\nOne. Two.\n\n## B\nThree."
    chunks = chunk_markdown("f", md)
    assert [c.title for c in chunks] == ["", "A", "B"]
    assert "hidden" not in " ".join(c.text for c in chunks)
    assert chunks[1].text == "A: One. Two."
    assert [c.id for c in chunks] == [c.id for c in chunk_markdown("f", md)]
    assert len({c.id for c in chunks}) == 3


def test_long_sections_are_split():
    body = " ".join(f"Sentence number {i} is here." for i in range(80))
    chunks = chunk_markdown("f", f"## Long\n{body}")
    assert len(chunks) > 1 and all(len(c.text) <= MAX_CHUNK_CHARS + 20 for c in chunks)
    assert chunk_markdown("f", "## Empty\n") == []


def test_real_knowledge_base_loads():
    chunks = load_knowledge(KNOWLEDGE_DIR)
    assert len(chunks) >= 10 and {c.source for c in chunks} >= {"hours-and-location", "booking-and-policies"}


# ----------------------------------------------------------------- retrieval
def test_retrieval_finds_the_right_section():
    r = make()
    cases = {
        "What are your opening hours?": "Opening hours",
        "where is the clinic located, address": "Address",
        "is there parking": "Parking",
        "can I cancel my appointment": "Cancellation",
        "what payment methods do you accept, UPI?": "Fees and payment",
        "do I need an account": "account",
    }
    for question, expected in cases.items():
        top = r.search(question)
        assert top and expected.lower() in top[0]["text"].lower(), question


def test_unrelated_or_empty_queries_return_nothing():
    r = make()
    assert r.search("quantum chromodynamics lagrangian") == []
    assert r.search("   ") == []
    assert ClinicInfoRetriever(HashingEmbedder(), InMemoryVectorStore()).search("hours") == []


def test_reingest_replaces_index():
    r = make()
    n = r.store.count()
    assert r.ingest() == n and r.store.count() == n


def test_hashing_embedder_is_deterministic_and_normalised():
    e = HashingEmbedder()
    a, b = e.embed(["opening hours"])[0], e.embed(["opening hours"])[0]
    assert a == b and abs(sum(v * v for v in a) - 1.0) < 1e-9
    assert sum(e.embed(["the of and"])[0]) == 0  # only stop words -> zero vector, no crash


def test_build_retriever_is_mock_without_chroma_and_cached():
    s = Settings(_env_file=None)
    assert s.chroma_mode == "mock"
    assert build_retriever(s) is build_retriever(s)


# ------------------------------------------------------- chroma (fake client)
class FakeCollection:
    def __init__(self):
        self.rows = {}

    def upsert(self, ids, documents, embeddings, metadatas):
        for i, d, e, m in zip(ids, documents, embeddings, metadatas, strict=True):
            self.rows[i] = (d, e, m)

    def query(self, query_embeddings, n_results):
        items = list(self.rows.items())[:n_results]
        return {
            "ids": [[i for i, _ in items]],
            "documents": [[v[0] for _, v in items]],
            "metadatas": [[v[2] for _, v in items]],
            "distances": [[0.25 for _ in items]],
        }

    def count(self):
        return len(self.rows)


class FakeClient:
    def __init__(self):
        self.col = FakeCollection()
        self.deleted = 0

    def get_or_create_collection(self, name, metadata=None):
        assert metadata == {"hnsw:space": "cosine"}
        return self.col

    def delete_collection(self, name):
        self.deleted += 1
        self.col = FakeCollection()


def test_chroma_store_adapter_maps_to_and_from_chroma():
    client = FakeClient()
    r = ClinicInfoRetriever(HashingEmbedder(), ChromaVectorStore(client))
    n = r.ingest()
    assert n > 0 and client.deleted == 1 and r.store.count() == n
    hit = r.search("opening hours")
    assert hit and hit[0]["source"] and hit[0]["text"]  # distance 0.25 -> score 0.75 passes the threshold


def test_chroma_from_settings_requires_chromadb_when_missing():
    s = SimpleNamespace(chroma_url="https://x", chroma_auth_token=SimpleNamespace(get_secret_value=lambda: ""))
    try:
        import chromadb  # noqa: F401
    except ImportError:
        import pytest

        with pytest.raises(ImportError):
            ChromaVectorStore.from_settings(s)


# --------------------------------------------------------------- mock LLM hook
async def test_mock_llm_routes_info_questions_and_answers_from_passages():
    llm = MockLLM(today=date(2030, 1, 1))
    first = await llm.complete([Message("user", "What are your opening hours?")], [])
    assert first.tool_calls[0].name == "clinic_info"
    data = {"passages": [{"source": "s", "text": "Opening hours: 9 to 1."}]}
    done = await llm.complete([Message("user", "hours?"), Message("tool", json.dumps(data), name="clinic_info")], [])
    assert "9 to 1" in done.content
    none = await llm.complete(
        [Message("user", "hours?"), Message("tool", json.dumps({"passages": []}), name="clinic_info")], []
    )
    assert "reception" in none.content
    # booking phrasing must still go to the doctor tools, not clinic_info
    book = await llm.complete([Message("user", "Book Dr. Anil tomorrow at 10am")], [])
    assert book.tool_calls[0].name == "find_doctors"


# ------------------------------------------------------- HF Inference embedder
def test_hf_inference_embedder_request_and_pooling():
    import httpx

    from app.rag.embeddings import HFInferenceEmbedder

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = __import__("json").loads(request.content)
        # one sentence vector, one token-level matrix
        return httpx.Response(200, json=[[3.0, 4.0], [[1.0, 0.0], [3.0, 0.0]]])

    emb = HFInferenceEmbedder("org/model", "hf-secret", transport=httpx.MockTransport(handler))
    a, b = emb.embed(["x", "y"])
    assert seen["url"].endswith("/models/org/model/pipeline/feature-extraction")
    assert seen["auth"] == "Bearer hf-secret" and seen["body"]["inputs"] == ["x", "y"]
    assert a == pytest.approx([0.6, 0.8]) and b == pytest.approx([1.0, 0.0])  # normalised / mean-pooled


def test_hf_inference_embedder_hides_errors():
    import httpx

    from app.core.exceptions import ExternalServiceError
    from app.rag.embeddings import HFInferenceEmbedder

    for resp in (
        httpx.Response(401, text="hf-secret rejected"),
        httpx.Response(200, json={"error": "x"}),
        httpx.Response(200, json=[[1.0]]),
    ):
        emb = HFInferenceEmbedder("m", "hf-secret", transport=httpx.MockTransport(lambda r, resp=resp: resp))
        with pytest.raises(ExternalServiceError) as e:
            emb.embed(["a", "b"])
        assert "hf-secret" not in str(e.value)


def test_retriever_prefers_inference_api_when_a_token_is_set(monkeypatch):
    from app.rag import retriever
    from app.rag.embeddings import HFInferenceEmbedder

    class FakeStore:
        @classmethod
        def from_settings(cls, settings):
            return InMemoryVectorStore()

    monkeypatch.setattr("app.rag.store.ChromaVectorStore", FakeStore)
    s = Settings(_env_file=None, chroma_url="https://c", huggingface_api_token="hf-x")
    assert isinstance(retriever.build_retriever(s).embedder, HFInferenceEmbedder)
