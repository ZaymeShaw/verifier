from __future__ import annotations

import hashlib
import math
import re
from typing import List, Sequence

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
