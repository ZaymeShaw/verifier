"""Draft Catalog embedding channel.

Reuses existing Bailian / Authority embedding infra and the audited field
Key-Index experiment formula (cosine_l2_at_scoring + entry projection).
This is not a new embedding stack. Similarity cutoffs belong on CollectionSpec,
not in business-word ifs.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from impl.core.schema import InvestigationKeyEntry, InvestigationKeyIndex

EMBEDDING_BATCH_SIZE = 10
# Same template as simulate_field_key_index._embedding_projection.
CATALOG_EMBEDDING_PROJECTION_VERSION = "client-search-field-projection-v1"

_VECTOR_CACHE: dict[tuple[int, str, str], dict[str, list[float]]] = {}


def catalog_embedding_projection(entry: InvestigationKeyEntry) -> str:
    return f"字段标识: {entry.key}\n字段名称: {entry.name}\n检索说明: {entry.search_text}"


def cosine_l2(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def embed_batched(
    provider: Any,
    texts: Sequence[str],
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> list[list[float]]:
    vectors: list[list[float]] = []
    size = max(1, int(batch_size))
    for start in range(0, len(texts), size):
        vectors.extend(provider.embed(texts[start : start + size]))
    return [list(vector) for vector in vectors]


def clear_entry_vector_cache() -> None:
    _VECTOR_CACHE.clear()


def entry_vectors_for_index(
    index: InvestigationKeyIndex,
    provider: Any,
    *,
    projection_version: str = CATALOG_EMBEDDING_PROJECTION_VERSION,
) -> dict[str, list[float]]:
    model_id = str(getattr(provider, "model_id", "") or "unknown")
    cache_key = (id(index), model_id, str(projection_version))
    cached = _VECTOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    texts = [catalog_embedding_projection(entry) for entry in index.entries]
    raw = embed_batched(provider, texts) if texts else []
    if len(raw) != len(index.entries):
        raise ValueError(
            f"embedding batch size {len(raw)} does not match entry count {len(index.entries)}"
        )
    vectors = {
        entry.key: list(vector) for entry, vector in zip(index.entries, raw)
    }
    _VECTOR_CACHE[cache_key] = vectors
    return vectors


def search_embedding_channel(
    index: InvestigationKeyIndex,
    query: str,
    *,
    provider: Any | None,
    min_cosine: float,
    limit: int,
    entry_vectors: Mapping[str, Sequence[float]] | None = None,
    query_vector: Sequence[float] | None = None,
) -> list[tuple[InvestigationKeyEntry, float]]:
    """Return (entry, cosine) pairs at or above CollectionSpec min_cosine."""
    text = str(query or "").strip()
    if not text or (provider is None and query_vector is None):
        return []
    if entry_vectors is None:
        if provider is None:
            return []
        vectors = entry_vectors_for_index(index, provider)
    else:
        vectors = entry_vectors
    vector = query_vector
    if vector is None:
        embedded = list(provider.embed([text]))
        if len(embedded) != 1:
            raise ValueError(
                f"embedding provider returned {len(embedded)} vectors for 1 query"
            )
        vector = embedded[0]
    ranked: list[tuple[InvestigationKeyEntry, float]] = []
    for entry in index.entries:
        stored = vectors.get(entry.key)
        if stored is None:
            continue
        similarity = cosine_l2(vector, stored)
        if similarity >= float(min_cosine):
            ranked.append((entry, float(similarity)))
    ranked.sort(key=lambda item: (-item[1], item[0].key))
    return ranked[: max(1, int(limit))]


def resolve_catalog_embedding_provider(explicit: Any = None) -> Any | None:
    if explicit is not None:
        return explicit
    try:
        from impl.core.config import get_embedding_config
        from impl.core.context.embedding import BailianEmbeddingProvider

        if not get_embedding_config().enabled:
            return None
        return BailianEmbeddingProvider()
    except Exception:
        return None
