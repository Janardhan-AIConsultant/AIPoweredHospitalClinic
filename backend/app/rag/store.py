"""Vector stores: in-memory (mock) and Pinecone (live; tested against a fake client only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

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


class PineconeVectorStore:
    """Pinecone serverless index (cosine). Vectors carry their text in metadata, so no second store is needed.

    Query time only needs ``PINECONE_API_KEY``; the index is created (if missing) by the offline
    ``python -m app.rag.ingest`` via :meth:`ensure_index`, never by a patient request.
    """

    def __init__(self, index: Any, namespace: str) -> None:
        # ``index`` may be a zero-argument callable so the index is only opened on first use:
        # the ingest CLI must be able to create a missing index *before* anything opens it.
        self._index_or_factory = index
        self._resolved: Any | None = None
        self._ns = namespace

    @property
    def _index(self) -> Any:
        if self._resolved is None:
            f = self._index_or_factory
            self._resolved = f() if callable(f) and not hasattr(f, "query") else f
        return self._resolved

    @classmethod
    def from_settings(cls, settings: Any) -> PineconeVectorStore:
        from pinecone import Pinecone  # type: ignore[import-not-found,unused-ignore]

        pc = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
        host = settings.pinecone_index_host
        name = settings.pinecone_index_name
        return cls(lambda: pc.Index(host=host) if host else pc.Index(name), settings.pinecone_namespace)

    @staticmethod
    def ensure_index(settings: Any, dimension: int) -> None:
        """Create the serverless index when absent and wait until it is ready (ingestion only)."""
        from pinecone import Pinecone, ServerlessSpec  # type: ignore[import-not-found,unused-ignore]

        pc = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
        if not pc.has_index(settings.pinecone_index_name):
            pc.create_index(
                name=settings.pinecone_index_name,
                dimension=dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud=settings.pinecone_cloud, region=settings.pinecone_region),
                timeout=300,  # wait until the index is ready to accept upserts
            )

    def reset(self) -> None:
        try:
            self._index.delete(delete_all=True, namespace=self._ns)
        except Exception as exc:  # noqa: BLE001 - an absent namespace is fine on a first ingest
            if "not found" not in str(exc).lower() and "404" not in str(exc):
                raise

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        records = [
            {"id": c.id, "values": v, "metadata": {"text": c.text, "source": c.source, "title": c.title}}
            for c, v in zip(chunks, vectors, strict=True)
        ]
        for i in range(0, len(records), 100):  # stay well inside Pinecone's per-request limits
            self._index.upsert(vectors=records[i : i + 100], namespace=self._ns)

    def query(self, vector: list[float], k: int) -> list[Hit]:
        res = self._index.query(vector=vector, top_k=k, namespace=self._ns, include_metadata=True)
        hits: list[Hit] = []
        for m in res["matches"]:
            meta = m["metadata"]
            hits.append(Hit(Chunk(m["id"], meta["text"], meta["source"], meta["title"]), float(m["score"])))
        return hits

    def count(self) -> int:
        stats = self._index.describe_index_stats()
        return int((stats.get("namespaces") or {}).get(self._ns, {}).get("vector_count", 0))
