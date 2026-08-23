from __future__ import annotations

import hashlib
import math
from array import array

import httpx

from app.core.config import Settings


class RagEmbeddingError(RuntimeError):
    pass


def embedding_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalize_vector(values: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude <= 0:
        raise RagEmbeddingError("Embedding provider returned a zero vector")
    return [value / magnitude for value in values]


def pack_vector(values: list[float]) -> bytes:
    return array("f", values).tobytes()


def unpack_vector(value: bytes) -> array[float]:
    result = array("f")
    result.frombytes(value)
    return result


def cosine_from_normalized(left: list[float], right_blob: bytes) -> float:
    right = unpack_vector(right_blob)
    if len(left) != len(right):
        return -1.0
    return float(sum(a * b for a, b in zip(left, right, strict=True)))


class RagEmbeddingClient:
    """Small OpenAI-compatible embedding client used by the local RAG index."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def model(self) -> str:
        return self.settings.rag_embedding_model.strip()

    @property
    def base_url(self) -> str:
        return (
            self.settings.rag_embedding_base_url.strip()
            or self.settings.lm_studio_base_url.strip()
            or self.settings.llm_base_url.strip()
        )

    @property
    def api_key(self) -> str:
        return (
            self.settings.rag_embedding_api_key.strip()
            or self.settings.lm_studio_api_key.strip()
            or self.settings.llm_api_key.strip()
        )

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.rag_embedding_enabled
            and self.model
            and self.base_url
        )

    async def embed_documents(self, values: list[str]) -> list[list[float]]:
        return await self._embed(values, prefix="search_document: ")

    async def embed_query(self, value: str) -> list[float]:
        vectors = await self._embed([value], prefix="search_query: ")
        return vectors[0]

    async def _embed(self, values: list[str], *, prefix: str) -> list[list[float]]:
        if not self.configured:
            raise RagEmbeddingError("RAG embedding provider is not configured")
        if not values:
            return []

        max_chars = max(256, self.settings.rag_embedding_input_max_chars)
        use_nomic_prefix = "nomic" in self.model.casefold()
        inputs = [
            f"{prefix if use_nomic_prefix else ''}{value[:max_chars]}"
            for value in values
        ]
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(
                timeout=max(1.0, self.settings.rag_embedding_timeout_seconds),
                verify=self.settings.rag_embedding_ssl_verify,
            ) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/embeddings",
                    headers=headers,
                    json={"model": self.model, "input": inputs},
                )
        except httpx.RequestError as exc:
            raise RagEmbeddingError("Unable to connect to the embedding provider") from exc

        if not response.is_success:
            raise RagEmbeddingError(
                f"Embedding provider returned HTTP {response.status_code}"
            )
        try:
            items = sorted(response.json()["data"], key=lambda item: int(item["index"]))
            vectors = [
                normalize_vector([float(value) for value in item["embedding"]])
                for item in items
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise RagEmbeddingError("Embedding provider returned an invalid response") from exc
        if len(vectors) != len(values):
            raise RagEmbeddingError("Embedding provider returned an unexpected vector count")
        return vectors
