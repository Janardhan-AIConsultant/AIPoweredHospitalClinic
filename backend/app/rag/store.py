"""Vector stores: in-memory (mock) and ChromaDB (live, optional dependency, unverified)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from app.rag.chunking import Chunk


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float  # cosine similarity, higher is better


class VectorStore(Protocol):
    def reset(self) -> None: ...
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def query(self, vector: list[float], k: int) -> list[Hit]: ...
    def count(self) -> int: ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: list[tuple[Chunk, list[float]]] = []

    def reset(self) -> None:
        self._items = []

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        self._items.extend(zip(chunks, vectors, strict=True))

    def query(self, vector: list[float], k: int) -> list[Hit]:
        scored = [Hit(c, sum(a * b for a, b in zip(vector, v, strict=True))) for c, v in self._items]
        return sorted(scored, key=lambda h: h.score, reverse=True)[:k]

    def count(self) -> int:
        return len(self._items)


class ChromaVectorStore:
    """Chroma collection with cosine space. Requires ``chromadb`` and a reachable server."""

    NAME = "clinic_knowledge"

    def __init__(self, client: Any) -> None:
        self._client = client
        self._col = client.get_or_create_collection(self.NAME, metadata={"hnsw:space": "cosine"})

    @classmethod
    def from_settings(cls, settings: Any) -> ChromaVectorStore:
        import chromadb  # type: ignore[import-not-found,unused-ignore]

        url = urlparse(settings.chroma_url)
        token = settings.chroma_auth_token.get_secret_value()
        client = chromadb.HttpClient(
            host=url.hostname,
            port=url.port or (443 if url.scheme == "https" else 80),
            ssl=url.scheme == "https",
            headers={"Authorization": f"Bearer {token}"} if token else None,
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
        )
        return cls(client)

    def reset(self) -> None:
        self._client.delete_collection(self.NAME)
        self._col = self._client.get_or_create_collection(self.NAME, metadata={"hnsw:space": "cosine"})

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        self._col.upsert(
            ids=[c.id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=vectors,
            metadatas=[{"source": c.source, "title": c.title} for c in chunks],
        )

    def query(self, vector: list[float], k: int) -> list[Hit]:
        res = self._col.query(query_embeddings=[vector], n_results=k)
        return [
            Hit(Chunk(i, doc, meta["source"], meta["title"]), 1.0 - float(dist))
            for i, doc, meta, dist in zip(
                res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True
            )
        ]

    def count(self) -> int:
        return int(self._col.count())
