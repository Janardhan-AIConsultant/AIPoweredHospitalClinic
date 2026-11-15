import json
from datetime import date

import pytest

from app.ai.llm import Message, MockLLM
from app.core.config import Settings
from app.rag.chunking import MAX_CHUNK_CHARS, chunk_markdown, load_knowledge
from app.rag.embeddings import HashingEmbedder
from app.rag.retriever import KNOWLEDGE_DIR, ClinicInfoRetriever, build_retriever
from app.rag.store import InMemoryVectorStore, PineconeVectorStore


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


def test_build_retriever_is_mock_without_pinecone_and_cached():
    s = Settings(_env_file=None)
    assert s.pinecone_mode == "mock"
    assert build_retriever(s) is build_retriever(s)


# ------------------------------------------------------ pinecone (fake client)
class FakeIndex:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.delete_calls = 0

    def delete(self, delete_all, namespace):
        assert delete_all is True and namespace == "ns"
        self.delete_calls += 1
        self.rows = {}

    def upsert(self, vectors, namespace):
        assert namespace == "ns" and len(vectors) <= 100
        for v in vectors:
            self.rows[v["id"]] = v

    def query(self, vector, top_k, namespace, include_metadata):
        assert include_metadata and namespace == "ns"
        return {
            "matches": [{"id": i, "score": 0.75, "metadata": v["metadata"]} for i, v in list(self.rows.items())[:top_k]]
        }

    def describe_index_stats(self):
        return {"namespaces": {"ns": {"vector_count": len(self.rows)}} if self.rows else {}}


def test_pinecone_store_adapter_maps_to_and_from_pinecone():
    index = FakeIndex()
    r = ClinicInfoRetriever(HashingEmbedder(), PineconeVectorStore(index, "ns"))
    n = r.ingest()
    assert n > 0 and index.delete_calls == 1 and r.store.count() == n
    hit = r.search("opening hours")
    assert hit and hit[0]["source"] and hit[0]["text"]  # score 0.75 passes the threshold


def test_pinecone_upserts_in_batches_of_100():
    from app.rag.chunking import Chunk

    index = FakeIndex()
    store = PineconeVectorStore(index, "ns")
    chunks = [Chunk(f"c{i}", "t", "s.md", "T") for i in range(250)]
    store.add(chunks, [[0.0] * 3 for _ in chunks])
    assert store.count() == 250


def test_pinecone_reset_tolerates_a_missing_namespace_but_not_other_errors():
    import pytest

    class Missing(FakeIndex):
        def delete(self, delete_all, namespace):
            raise RuntimeError("Namespace not found")

    PineconeVectorStore(Missing(), "ns").reset()

    class Broken(FakeIndex):
        def delete(self, delete_all, namespace):
            raise RuntimeError("401 unauthorized")

    with pytest.raises(RuntimeError):
        PineconeVectorStore(Broken(), "ns").reset()


def test_pinecone_from_settings_builds_a_real_client_without_network():
    s = Settings(_env_file=None, pinecone_api_key="pc-secret", pinecone_index_host="https://idx.svc.pinecone.io")
    assert s.pinecone_mode == "live"
    store = PineconeVectorStore.from_settings(s)  # lazy: must not touch the network until first use
    assert store._resolved is None


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


# ------------------------------------------------------- Pinecone embedder
class FakeInference:
    def __init__(self, fail: bool = False, short: bool = False):
        self.calls: list[dict] = []
        self.fail, self.short = fail, short

    def embed(self, model, inputs, parameters):
        if self.fail:
            raise RuntimeError("401 pc-secret rejected")
        self.calls.append({"model": model, "inputs": list(inputs), "parameters": dict(parameters)})
        n = len(inputs) - (1 if self.short else 0)
        return [{"values": [3.0, 4.0]} for _ in range(n)]


class FakeClient:
    def __init__(self, **kw):
        self.inference = FakeInference(**kw)


def test_pinecone_embedder_uses_passage_and_query_types_and_normalises():
    from app.rag.embeddings import PineconeEmbedder

    c = FakeClient()
    emb = PineconeEmbedder("llama-text-embed-v2", c, 1024)
    assert emb.embed(["a", "b"]) == [pytest.approx([0.6, 0.8])] * 2
    assert emb.embed_query("q") == pytest.approx([0.6, 0.8])
    assert c.inference.calls[0]["parameters"] == {"input_type": "passage", "truncate": "END", "dimension": 1024}
    assert c.inference.calls[1]["parameters"]["input_type"] == "query"


def test_pinecone_embedder_batches_in_96s():
    from app.rag.embeddings import PineconeEmbedder

    c = FakeClient()
    PineconeEmbedder("m", c).embed([str(i) for i in range(200)])
    assert [len(x["inputs"]) for x in c.inference.calls] == [96, 96, 8]


def test_pinecone_embedder_hides_errors():
    from app.core.exceptions import ExternalServiceError
    from app.rag.embeddings import PineconeEmbedder

    for client in (FakeClient(fail=True), FakeClient(short=True)):
        with pytest.raises(ExternalServiceError) as e:
            PineconeEmbedder("m", client).embed(["a", "b"])
        assert "pc-secret" not in str(e.value)


def test_retriever_uses_the_pinecone_embedder_and_query_input_type(monkeypatch):
    from app.rag import retriever
    from app.rag.embeddings import PineconeEmbedder

    class FakeStore:
        @classmethod
        def from_settings(cls, settings):
            return InMemoryVectorStore()

    monkeypatch.setattr("app.rag.store.PineconeVectorStore", FakeStore)
    s = Settings(_env_file=None, pinecone_api_key="pc-x")
    r = retriever.build_retriever(s)
    assert isinstance(r.embedder, PineconeEmbedder) and s.pinecone_embed_dimension == 1024
    c = FakeClient()
    r.embedder._client = c
    r.store.add([__import__("app.rag.chunking", fromlist=["Chunk"]).Chunk("1", "t", "s.md", "T")], [[0.6, 0.8]])
    r.search("hours")
    assert c.inference.calls[-1]["parameters"]["input_type"] == "query"
