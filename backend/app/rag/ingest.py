"""Offline ingestion: ``python -m app.rag.ingest`` (re)builds the vector index from ``knowledge/``."""

from __future__ import annotations

from app.core.config import get_settings
from app.rag.retriever import build_retriever


def main() -> None:
    settings = get_settings()
    retriever = build_retriever(settings)
    if settings.pinecone_mode == "mock":
        print(f"Mock mode (PINECONE_API_KEY not set): {retriever.store.count()} chunks indexed in memory only.")
        return
    from app.rag.store import PineconeVectorStore

    PineconeVectorStore.ensure_index(settings, dimension=settings.pinecone_embed_dimension)
    print(f"Ingested {retriever.ingest()} chunks into Pinecone index '{settings.pinecone_index_name}'.")


if __name__ == "__main__":
    main()
