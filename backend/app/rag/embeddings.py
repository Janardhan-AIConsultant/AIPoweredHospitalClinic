"""Embedding backends. ``HashingEmbedder`` is the deterministic offline/mock one."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

import httpx

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


class HFInferenceEmbedder:
    """Query/ingest-time embeddings through the Hugging Face Inference API (no torch in the deployment).

    Written to the documented feature-extraction endpoint; NOT verified against the real API
    (no token yet). Token-level outputs are mean-pooled; vectors are L2-normalised.
    """

    URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"

    def __init__(
        self, model: str, token: str, timeout: float = 15.0, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._url = self.URL.format(model=model)
        self._token, self._timeout, self._transport = token, timeout, transport

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(
                    self._url,
                    json={"inputs": texts, "options": {"wait_for_model": True}},
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError("unexpected embedding response")
            return [_normalise(self._pool(item)) for item in data]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ExternalServiceError("Embedding service is temporarily unavailable.") from exc

    @staticmethod
    def _pool(item: Any) -> list[float]:
        if item and isinstance(item[0], list):  # [tokens][dims] -> mean over tokens
            return [sum(col) / len(item) for col in zip(*item, strict=True)]
        return [float(x) for x in item]


class HuggingFaceEmbedder:
    """Local sentence-transformers model. Optional dependency; NOT verified in this build."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found,unused-ignore]

        self._model: Any = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.encode(texts, normalize_embeddings=True)]
