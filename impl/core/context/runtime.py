from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .errors import (
    ContextAuthorizationError,
    ContextBudgetError,
    ContextNotFoundError,
    ContextRegistrationConflictError,
    ContextResolutionError,
    ContextValidationError,
)
from .models import ContextUnit, ContextUnitRecord
from .policy import ContextPolicyResolver, _RunContextPolicy
from .ports import ContentResolver, ContextRegistry, ContextVectorIndex, EmbeddingProvider


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_search_text(record: ContextUnitRecord) -> str:
    return f"{record.name}\n{record.description}"


def _record_payload(record: ContextUnitRecord) -> tuple:
    return (
        record.id,
        record.name,
        record.description,
        record.content,
        record.content_ref,
        record.project_id,
        record.scope,
        record.roles,
        record.unit_type,
        record.source_type,
        record.status,
        tuple(sorted(record.tags.items())),
    )


class ContextRuntime:
    """Governed registration, search and loading for one project."""

    def __init__(
        self,
        *,
        project_id: str,
        registry: ContextRegistry,
        vector_index: ContextVectorIndex,
        embedding_provider: EmbeddingProvider,
        content_resolver: ContentResolver,
        policy_resolver: ContextPolicyResolver,
    ):
        self.project_id = str(project_id or "").strip()
        if not self.project_id:
            raise ContextValidationError("project_id is required")
        self.registry = registry
        self.vector_index = vector_index
        self.embedding_provider = embedding_provider
        self.content_resolver = content_resolver
        self.policy_resolver = policy_resolver
        self._registration_lock = threading.RLock()

    def register_context_unit(self, record: ContextUnitRecord) -> Mapping[str, Any]:
        if record.project_id != self.project_id:
            raise ContextRegistrationConflictError(
                f"record project {record.project_id!r} does not match runtime project {self.project_id!r}"
            )

        source_content = record.content
        if source_content is None:
            source_content = self.content_resolver.resolve(str(record.content_ref), record)
        source_hash = _sha256(source_content)
        description_hash = _sha256(_record_search_text(record))
        model_id = self.embedding_provider.model_id

        with self._registration_lock:
            existing = self.registry.get(record.id)
            if existing is not None and existing["record"].project_id != record.project_id:
                raise ContextRegistrationConflictError(
                    f"stable context id {record.id!r} already belongs to project {existing['record'].project_id!r}"
                )

            needs_embedding = (
                existing is None
                or existing["description_hash"] != description_hash
                or existing["embedding_model"] != model_id
                or not self.vector_index.has_vector(record.id, model_id)
            )
            vector = None
            if needs_embedding:
                embedded = self.embedding_provider.embed([_record_search_text(record)])
                if len(embedded) != 1 or not embedded[0]:
                    raise ContextValidationError("embedding provider returned an invalid vector batch")
                vector = tuple(float(value) for value in embedded[0])

            if existing is None:
                action = "created"
            elif _record_payload(existing["record"]) == _record_payload(record):
                if needs_embedding:
                    action = "reindexed"
                elif existing["source_hash"] == source_hash:
                    return {
                        "id": record.id,
                        "action": "reused",
                        "embedding_rebuilt": False,
                    }
                else:
                    action = "updated"
            else:
                action = "updated"

            with self.registry.transaction() as transaction:
                current = self.registry.get(record.id, transaction=transaction)
                if current is not None and current["record"].project_id != record.project_id:
                    raise ContextRegistrationConflictError(
                        f"stable context id {record.id!r} changed project during registration"
                    )
                self.registry.upsert(
                    record,
                    source_hash=source_hash,
                    description_hash=description_hash,
                    embedding_model=model_id,
                    transaction=transaction,
                )
                if vector is not None:
                    self.vector_index.upsert(
                        record,
                        vector,
                        model_id=model_id,
                        description_hash=description_hash,
                        transaction=transaction,
                    )
                else:
                    self.vector_index.update_filters(record, transaction=transaction)

            return {
                "id": record.id,
                "action": action,
                "embedding_rebuilt": vector is not None,
            }

    def register_context_units(self, records: Iterable[ContextUnitRecord]) -> Mapping[str, Any]:
        counts = {"created": 0, "reused": 0, "updated": 0, "reindexed": 0, "embedding_rebuilt": 0}
        items = []
        for record in records:
            result = dict(self.register_context_unit(record))
            items.append(result)
            counts[result["action"]] += 1
            if result["embedding_rebuilt"]:
                counts["embedding_rebuilt"] += 1
        return {**counts, "items": items}

    def invalidate_context_unit(self, unit_id: str, *, status: str = "inactive") -> Mapping[str, Any]:
        if str(status).strip() == "active":
            raise ContextValidationError("invalidation status cannot be active")
        existing = self.registry.get(str(unit_id))
        if existing is None:
            raise ContextNotFoundError(f"context unit not found: {unit_id}")
        return self.register_context_unit(replace(existing["record"], status=status))

    def start_run(
        self,
        *,
        role: str,
        operation: str,
        trace_id: str = "",
        run_id: str = "",
        case_id: str = "",
        run_restrictions: Optional[Mapping[str, Any]] = None,
    ) -> "ContextRun":
        policy = self.policy_resolver.resolve(
            role=role,
            operation=operation,
            project_id=self.project_id,
            trace_id=trace_id,
            run_id=run_id,
            case_id=case_id,
            run_restrictions=run_restrictions,
        )
        return ContextRun(runtime=self, policy=policy)

    def _search(
        self,
        queries: Sequence[str],
        policy: _RunContextPolicy,
        top_k_per_query: Optional[int] = None,
    ) -> List[Mapping[str, Any]]:
        policy.assert_enabled()
        normalized_queries = tuple(dict.fromkeys(str(query).strip() for query in queries if str(query).strip()))
        if not normalized_queries:
            raise ContextValidationError("queries must contain at least one non-empty query")
        if len(normalized_queries) > policy.query_limit:
            raise ContextBudgetError(
                f"query count {len(normalized_queries)} exceeds policy limit {policy.query_limit}"
            )
        requested_top_k = policy.top_k_per_query if top_k_per_query is None else int(top_k_per_query)
        if requested_top_k <= 0:
            raise ContextValidationError("top_k_per_query must be positive")
        effective_top_k = min(requested_top_k, policy.top_k_per_query, policy.candidate_limit)
        query_vectors = self.embedding_provider.embed(normalized_queries)
        if len(query_vectors) != len(normalized_queries):
            raise ContextValidationError("embedding provider returned a mismatched query batch")

        per_query_hits: List[List[Mapping[str, Any]]] = []
        aggregate: Dict[str, Dict[str, Any]] = {}
        for query_index, (query, vector) in enumerate(zip(normalized_queries, query_vectors)):
            raw_hits = self.vector_index.search(
                vector,
                model_id=self.embedding_provider.model_id,
                project_id=policy.project_id,
                role=policy.role,
                operation=policy.operation,
                trace_id=policy.trace_id,
                run_id=policy.run_id,
                case_id=policy.case_id,
                allowed_scopes=None if policy.allowed_scopes is None else tuple(policy.allowed_scopes),
                forbidden_scopes=tuple(policy.forbidden_scopes),
                allowed_unit_types=None
                if policy.allowed_unit_types is None
                else tuple(policy.allowed_unit_types),
                forbidden_unit_types=tuple(policy.forbidden_unit_types),
                allowed_source_types=None
                if policy.allowed_source_types is None
                else tuple(policy.allowed_source_types),
                forbidden_source_types=tuple(policy.forbidden_source_types),
                allowed_statuses=tuple(policy.allowed_statuses),
                limit=effective_top_k,
            )
            authorized_hits = [hit for hit in raw_hits if policy.permits(hit["record"])]
            per_query_hits.append(authorized_hits)
            for rank, hit in enumerate(authorized_hits, start=1):
                unit_id = str(hit["id"])
                item = aggregate.setdefault(
                    unit_id,
                    {
                        "id": unit_id,
                        "name": str(hit["name"]),
                        "description": str(hit["description"]),
                        "matched_queries": [],
                        "_rrf": 0.0,
                        "_score": float(hit["score"]),
                        "_first_query": query_index,
                    },
                )
                item["_rrf"] += 1.0 / (60.0 + rank)
                item["_score"] = max(float(item["_score"]), float(hit["score"]))
                if query not in item["matched_queries"]:
                    item["matched_queries"].append(query)

        # Round-robin selection prevents one broad query from occupying every candidate slot.
        selected_ids = []
        rank = 0
        while len(selected_ids) < policy.candidate_limit:
            added = False
            for hits in per_query_hits:
                if rank < len(hits):
                    unit_id = str(hits[rank]["id"])
                    if unit_id not in selected_ids:
                        selected_ids.append(unit_id)
                        added = True
                        if len(selected_ids) >= policy.candidate_limit:
                            break
            if not added:
                break
            rank += 1

        selected = [aggregate[unit_id] for unit_id in selected_ids]
        selected.sort(key=lambda item: (-float(item["_rrf"]), -float(item["_score"]), item["id"]))
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
                "matched_queries": list(item["matched_queries"]),
            }
            for item in selected
        ]

    def _load(self, unit_ids: Sequence[str], policy: _RunContextPolicy) -> List[ContextUnit]:
        policy.assert_enabled()
        normalized_ids = tuple(dict.fromkeys(str(unit_id).strip() for unit_id in unit_ids if str(unit_id).strip()))
        if not normalized_ids:
            return []
        if len(normalized_ids) > policy.load_limit:
            raise ContextBudgetError(
                f"load count {len(normalized_ids)} exceeds policy limit {policy.load_limit}"
            )

        entries = self.registry.get_many(normalized_ids)
        missing = [unit_id for unit_id in normalized_ids if unit_id not in entries]
        if missing:
            raise ContextNotFoundError(f"context units not found: {missing}")
        unauthorized = [unit_id for unit_id in normalized_ids if not policy.permits(entries[unit_id]["record"])]
        if unauthorized:
            raise ContextAuthorizationError(f"context units are not allowed by this run policy: {unauthorized}")

        records = [entries[unit_id]["record"] for unit_id in normalized_ids]
        with ThreadPoolExecutor(max_workers=min(4, len(records))) as executor:
            contents = list(executor.map(self._resolve_content, records))
        total_chars = sum(len(content) for content in contents)
        if total_chars > policy.content_char_budget:
            raise ContextBudgetError(
                f"loaded content size {total_chars} exceeds policy budget {policy.content_char_budget}"
            )
        return [
            ContextUnit(
                id=record.id,
                name=record.name,
                description=record.description,
                content=content,
            )
            for record, content in zip(records, contents)
        ]

    def _resolve_content(self, record: ContextUnitRecord) -> str:
        if record.content is not None:
            return record.content
        if record.content_ref is None:
            raise ContextResolutionError(f"context record has no content source: {record.id}")
        return self.content_resolver.resolve(record.content_ref, record)


class ContextRun:
    """Run-scoped facade that shares one immutable policy across Search and Load."""

    def __init__(self, *, runtime: ContextRuntime, policy: _RunContextPolicy):
        self._runtime = runtime
        self._policy = policy
        self._debug: Dict[str, Any] = {
            "policy": policy.debug_dict(),
            "mandatory_ids": list(policy.mandatory_ids),
            "search_queries": [],
            "candidate_ids": [],
            "loaded_ids": [],
            "content_chars": {},
            "content_hashes": {},
        }

    def search_context_units(
        self, queries: Sequence[str], top_k_per_query: Optional[int] = None
    ) -> List[Mapping[str, Any]]:
        items = self._runtime._search(queries, self._policy, top_k_per_query=top_k_per_query)
        self._debug["search_queries"].extend(str(query) for query in queries)
        for item in items:
            if item["id"] not in self._debug["candidate_ids"]:
                self._debug["candidate_ids"].append(item["id"])
        return items

    def load_context_units(self, unit_ids: Sequence[str]) -> List[ContextUnit]:
        units = self._runtime._load(unit_ids, self._policy)
        for unit in units:
            if unit.id not in self._debug["loaded_ids"]:
                self._debug["loaded_ids"].append(unit.id)
            self._debug["content_chars"][unit.id] = len(unit.content)
            self._debug["content_hashes"][unit.id] = _sha256(unit.content)
        return units

    def load_mandatory_context_units(self) -> List[ContextUnit]:
        return self.load_context_units(self._policy.mandatory_ids)

    def debug_snapshot(self) -> Mapping[str, Any]:
        return {
            "context_debug": {
                "policy": dict(self._debug["policy"]),
                "mandatory_ids": list(self._debug["mandatory_ids"]),
                "search_queries": list(self._debug["search_queries"]),
                "candidate_ids": list(self._debug["candidate_ids"]),
                "loaded_ids": list(self._debug["loaded_ids"]),
                "content_chars": dict(self._debug["content_chars"]),
                "content_hashes": dict(self._debug["content_hashes"]),
            }
        }
