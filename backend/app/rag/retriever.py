"""Clinic-information retrieval service."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.rag.chunking import load_knowledge
from app.rag.embeddings import Embedder, HashingEmbedder, PineconeEmbedder
from app.rag.store import InMemoryVectorStore, VectorStore

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
MIN_SCORE = 0.15
TOP_K = 3


class ClinicInfoRetriever:
    def __init__(self, embedder: Embedder, store: VectorStore, min_score: float = MIN_SCORE) -> None:
        self.embedder, self.store, self.min_score = embedder, store, min_score

    def ingest(self, directory: Path = KNOWLEDGE_DIR) -> int:
        chunks = load_knowledge(directory)
        self.store.reset()
        if chunks:
            self.store.add(chunks, self.embedder.embed([c.text for c in chunks]))
        return len(chunks)

    def search(self, query: str, k: int = TOP_K) -> list[dict[str, str]]:
        if not query.strip():  # an empty index simply returns no hits; avoid a stats call per question
            return []
        embed_query = getattr(self.embedder, "embed_query", None)  # asymmetric models embed queries differently
        vector = embed_query(query) if embed_query else self.embedder.embed([query])[0]
        hits = self.store.query(vector, k)
        return [{"source": h.chunk.source, "text": h.chunk.text} for h in hits if h.score >= self.min_score]


_mock: ClinicInfoRetriever | None = None


def build_retriever(settings: Settings) -> ClinicInfoRetriever:
    """Mock (in-memory + hashing embedder built from ``knowledge/``) unless Pinecone is configured."""
    global _mock
    if settings.pinecone_mode == "live":
        from app.rag.store import PineconeVectorStore

        # The live collection is populated by ``python -m app.rag.ingest``, never at request time.
        embedder: Embedder = PineconeEmbedder.from_settings(settings)
        return ClinicInfoRetriever(embedder, PineconeVectorStore.from_settings(settings))
    if _mock is None:
        _mock = ClinicInfoRetriever(HashingEmbedder(), InMemoryVectorStore())
        _mock.ingest()
    return _mock
