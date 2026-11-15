"""Embedding backends. ``HashingEmbedder`` is the deterministic offline/mock one."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

from app.core.exceptions import ExternalServiceError

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are at be by can do for from how i in is it me my of on or the to what when where which you your".split()
)


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


class HashingEmbedder:
    """Bag-of-words feature hashing (L2-normalised). Lexical only, but deterministic and offline."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for word in _WORD.findall(text.lower()):
                if word in _STOP:
                    continue
                h = int.from_bytes(hashlib.blake2b(_stem(word).encode(), digest_size=8).digest(), "big")
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


def _normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class PineconeEmbedder:
    """Embeddings from Pinecone's hosted inference (same API key as the index, no torch in the deployment).

    The model is asymmetric, so passages and queries are embedded with different ``input_type``
    values; ``embed`` is for stored passages and ``embed_query`` for the user's question.
    """

    BATCH = 96  # the service's per-request input limit

    def __init__(self, model: str, client: Any, dimension: int | None = None) -> None:
        self._model, self._client, self._dimension = model, client, dimension

    @classmethod
    def from_settings(cls, settings: Any) -> PineconeEmbedder:
        from pinecone import Pinecone  # type: ignore[import-not-found,unused-ignore]

        client = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
        return cls(settings.pinecone_embed_model, client, settings.pinecone_embed_dimension)

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        params: dict[str, Any] = {"input_type": input_type, "truncate": "END"}
        if self._dimension:
            params["dimension"] = self._dimension
        try:
            for i in range(0, len(texts), self.BATCH):
                res = self._client.inference.embed(
                    model=self._model, inputs=texts[i : i + self.BATCH], parameters=params
                )
                out.extend([_normalise([float(x) for x in item["values"]]) for item in res])
        except Exception as exc:  # noqa: BLE001 - provider errors vary; never leak their text
            raise ExternalServiceError("Embedding service is temporarily unavailable.") from exc
        if len(out) != len(texts):
            raise ExternalServiceError("Embedding service is temporarily unavailable.")
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]
