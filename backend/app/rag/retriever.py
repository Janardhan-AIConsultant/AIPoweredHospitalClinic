"""Clinic-information retrieval service."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.rag.chunking import load_knowledge
from app.rag.embeddings import Embedder, HashingEmbedder, HFInferenceEmbedder, HuggingFaceEmbedder
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
        if not query.strip() or self.store.count() == 0:
            return []
        hits = self.store.query(self.embedder.embed([query])[0], k)
        return [{"source": h.chunk.source, "text": h.chunk.text} for h in hits if h.score >= self.min_score]


_mock: ClinicInfoRetriever | None = None


def build_retriever(settings: Settings) -> ClinicInfoRetriever:
    """Mock (in-memory + hashing embedder built from ``knowledge/``) unless Chroma is configured."""
    global _mock
    if settings.chroma_mode == "live":
        from app.rag.store import ChromaVectorStore

        # The live collection is populated by ``python -m app.rag.ingest``, never at request time.
        token = settings.huggingface_api_token.get_secret_value()
        embedder: Embedder = (
            HFInferenceEmbedder(settings.huggingface_model, token)  # serverless: no local model
            if token
            else HuggingFaceEmbedder(settings.huggingface_model)  # offline ingestion on a machine with torch
        )
        return ClinicInfoRetriever(embedder, ChromaVectorStore.from_settings(settings))
    if _mock is None:
        _mock = ClinicInfoRetriever(HashingEmbedder(), InMemoryVectorStore())
        _mock.ingest()
    return _mock
