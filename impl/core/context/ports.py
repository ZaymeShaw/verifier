from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Mapping, Optional, Protocol, Sequence

from .models import ContextUnitRecord


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str:
        ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        ...


class ContentResolver(Protocol):
    def resolve(self, content_ref: str, record: ContextUnitRecord) -> str:
        ...


class ContextRegistry(Protocol):
    def transaction(self) -> AbstractContextManager[Any]:
        ...

    def get(self, unit_id: str, *, transaction: Any = None) -> Optional[Mapping[str, Any]]:
        ...

    def get_many(self, unit_ids: Sequence[str], *, transaction: Any = None) -> Mapping[str, Mapping[str, Any]]:
        ...

    def list_entries(self, project_id: str) -> Sequence[Mapping[str, Any]]:
        ...

    def upsert(
        self,
        record: ContextUnitRecord,
        *,
        source_hash: str,
        description_hash: str,
        embedding_model: str,
        transaction: Any,
    ) -> None:
        ...


class ContextVectorIndex(Protocol):
    def has_vector(self, unit_id: str, model_id: str, *, transaction: Any = None) -> bool:
        ...

    def upsert(
        self,
        record: ContextUnitRecord,
        vector: Sequence[float],
        *,
        model_id: str,
        description_hash: str,
        transaction: Any,
    ) -> None:
        ...

    def update_filters(self, record: ContextUnitRecord, *, transaction: Any) -> None:
        ...

    def search(
        self,
        query_vector: Sequence[float],
        *,
        model_id: str,
        project_id: str,
        role: str,
        operation: str,
        trace_id: str,
        run_id: str,
        case_id: str,
        allowed_scopes: Optional[Sequence[str]],
        forbidden_scopes: Sequence[str],
        allowed_unit_types: Optional[Sequence[str]],
        forbidden_unit_types: Sequence[str],
        allowed_source_types: Optional[Sequence[str]],
        forbidden_source_types: Sequence[str],
        allowed_statuses: Sequence[str],
        limit: int,
    ) -> Sequence[Mapping[str, Any]]:
        ...
