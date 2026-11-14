"""Offline ingestion: ``python -m app.rag.ingest`` (re)builds the vector index from ``knowledge/``."""

from __future__ import annotations

from app.core.config import get_settings
from app.rag.retriever import build_retriever


def main() -> None:
    settings = get_settings()
    retriever = build_retriever(settings)
    if settings.chroma_mode == "mock":
        print(f"Mock mode (CHROMA_URL not set): {retriever.store.count()} chunks indexed in memory only.")
        return
    print(f"Ingested {retriever.ingest()} chunks into Chroma.")


if __name__ == "__main__":
    main()
