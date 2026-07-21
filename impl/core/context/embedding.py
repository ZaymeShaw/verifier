from __future__ import annotations

import hashlib
import math
import re
from typing import Any, List, Mapping, Sequence

from .errors import ContextConfigurationError, ContextValidationError

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


class UnconfiguredEmbeddingProvider:
    """Fail-closed provider used until a real embedding service is configured."""

    @property
    def model_id(self) -> str:
        return "unconfigured"

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        raise ContextConfigurationError(
            "embedding provider is not configured; supply a production provider before registration or search"
        )


class BailianEmbeddingProvider:
    """Production ContextRuntime adapter around the repository's Bailian embedder."""

    def __init__(self, embedder: Any = None) -> None:
        from ..knowledge_base import BailianEmbedder

        self._embedder = embedder or BailianEmbedder()

    @property
    def model_id(self) -> str:
        return str(self._embedder.id)

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        normalized = [str(text) for text in texts]
        batch = getattr(self._embedder, "get_embeddings_and_usage", None)
        if callable(batch):
            raw_vectors, usage = batch(normalized)
        else:
            raw_vectors = []
            usage = None
            for text in normalized:
                vector, usage = self._embedder.get_embedding_and_usage(text)
                raw_vectors.append(vector)
        detail = usage if isinstance(usage, Mapping) else {}
        error = str(detail.get("error") or "")
        if error in {"missing_bailian_api_key", "missing_dashscope_dependency"}:
            raise ContextConfigurationError(f"Bailian ContextUnit embedding is not configured: {dict(detail)}")
        if len(raw_vectors) != len(normalized):
            raise ContextValidationError(
                f"Bailian returned embedding batch size {len(raw_vectors)} for {len(normalized)} texts; "
                f"response detail={dict(detail)}"
            )
        vectors = []
        for vector in raw_vectors:
            try:
                vectors.append(validate_embedding_vector(
                    vector,
                    expected_dimensions=getattr(self._embedder, "dimensions", 0),
                ))
            except ContextValidationError as exc:
                raise ContextValidationError(
                    f"Bailian returned an invalid ContextUnit embedding: {exc}; response detail={dict(detail)}"
                ) from exc
        return vectors


def validate_embedding_vector(vector: Sequence[Any], *, expected_dimensions: int = 0) -> List[float]:
    if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)) or not vector:
        raise ContextValidationError("embedding vector is empty or not a numeric sequence")
    try:
        normalized = [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise ContextValidationError("embedding vector contains a non-numeric value") from exc
    if any(not math.isfinite(value) for value in normalized):
        raise ContextValidationError("embedding vector contains NaN or infinity")
    if expected_dimensions and len(normalized) != int(expected_dimensions):
        raise ContextValidationError(
            f"embedding vector dimension {len(normalized)} does not match expected {int(expected_dimensions)}"
        )
    if not any(value != 0.0 for value in normalized):
        raise ContextValidationError("embedding vector is all zero")
    return normalized


class DeterministicHashEmbeddingProvider:
    """Deterministic bag-of-token embedding for tests and structural validation only."""

    def __init__(self, dimensions: int = 64, model_id: str = "test-hash-v1"):
        if dimensions <= 0:
            raise ContextValidationError("embedding dimensions must be positive")
        self._dimensions = int(dimensions)
        self._model_id = str(model_id)
        self.calls = 0

    @property
    def model_id(self) -> str:
        return self._model_id

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls += 1
        return [self._embed_one(str(text)) for text in texts]

    def _embed_one(self, text: str) -> List[float]:
        vector = [0.0] * self._dimensions
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:8], "big") % self._dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector
