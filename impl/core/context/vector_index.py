from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .models import ContextUnitRecord
from .registry import SQLiteContextDatabase


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


class SQLiteContextVectorIndex:
    def __init__(self, database: SQLiteContextDatabase):
        self.database = database

    def has_vector(self, unit_id: str, model_id: str, *, transaction: Any = None) -> bool:
        if transaction is not None:
            row = transaction.execute(
                "SELECT 1 FROM context_vectors WHERE unit_id = ? AND model_id = ?", (unit_id, model_id)
            ).fetchone()
            return row is not None
        with self.database.reader() as connection:
            row = connection.execute(
                "SELECT 1 FROM context_vectors WHERE unit_id = ? AND model_id = ?", (unit_id, model_id)
            ).fetchone()
        return row is not None

    def upsert(
        self,
        record: ContextUnitRecord,
        vector: Sequence[float],
        *,
        model_id: str,
        description_hash: str,
        transaction: Any,
    ) -> None:
        transaction.execute(
            """
            INSERT INTO context_vectors (
                unit_id, model_id, vector_json, project_id, scope, unit_type,
                source_type, status, description_hash, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unit_id) DO UPDATE SET
                model_id = excluded.model_id,
                vector_json = excluded.vector_json,
                project_id = excluded.project_id,
                scope = excluded.scope,
                unit_type = excluded.unit_type,
                source_type = excluded.source_type,
                status = excluded.status,
                description_hash = excluded.description_hash,
                updated_at = excluded.updated_at
            """,
            (
                record.id,
                model_id,
                json.dumps([float(value) for value in vector], separators=(",", ":")),
                record.project_id,
                record.scope,
                record.unit_type,
                record.source_type,
                record.status,
                description_hash,
                _utc_now(),
            ),
        )

    def update_filters(self, record: ContextUnitRecord, *, transaction: Any) -> None:
        transaction.execute(
            """
            UPDATE context_vectors
            SET project_id = ?, scope = ?, unit_type = ?, source_type = ?, status = ?, updated_at = ?
            WHERE unit_id = ?
            """,
            (
                record.project_id,
                record.scope,
                record.unit_type,
                record.source_type,
                record.status,
                _utc_now(),
                record.id,
            ),
        )

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
        if not allowed_statuses:
            return []
        for allowed in (allowed_scopes, allowed_unit_types, allowed_source_types):
            if allowed is not None and not allowed:
                return []

        conditions = ["v.model_id = ?", "v.project_id = ?", "r.role = ?"]
        parameters: List[Any] = [model_id, project_id, role]
        self._append_in_filter(conditions, parameters, "v.status", allowed_statuses, include=True)
        self._append_in_filter(conditions, parameters, "v.scope", allowed_scopes, include=True)
        self._append_in_filter(conditions, parameters, "v.scope", forbidden_scopes, include=False)
        self._append_in_filter(conditions, parameters, "v.unit_type", allowed_unit_types, include=True)
        self._append_in_filter(conditions, parameters, "v.unit_type", forbidden_unit_types, include=False)
        self._append_in_filter(conditions, parameters, "v.source_type", allowed_source_types, include=True)
        self._append_in_filter(conditions, parameters, "v.source_type", forbidden_source_types, include=False)

        sql = f"""
            SELECT v.unit_id, v.vector_json, u.name, u.description, u.content, u.content_ref,
                   u.project_id, u.scope, u.roles_json, u.unit_type, u.source_type,
                   u.status, u.tags_json
            FROM context_vectors v
            JOIN context_units u ON u.id = v.unit_id
            JOIN context_unit_roles r ON r.unit_id = v.unit_id
            WHERE {' AND '.join(conditions)}
        """
        with self.database.reader() as connection:
            rows = connection.execute(sql, tuple(parameters)).fetchall()

        hits: List[Dict[str, Any]] = []
        for row in rows:
            record = ContextUnitRecord(
                id=str(row["unit_id"]),
                name=str(row["name"]),
                description=str(row["description"]),
                content=row["content"],
                content_ref=row["content_ref"],
                project_id=str(row["project_id"]),
                scope=str(row["scope"]),
                roles=tuple(json.loads(row["roles_json"])),
                unit_type=str(row["unit_type"]),
                source_type=str(row["source_type"]),
                status=str(row["status"]),
                tags=dict(json.loads(row["tags_json"])),
            )
            if not self._matches_visibility(
                record, operation=operation, trace_id=trace_id, run_id=run_id, case_id=case_id
            ):
                continue
            vector = json.loads(row["vector_json"])
            hits.append(
                {
                    "id": record.id,
                    "name": record.name,
                    "description": record.description,
                    "score": _cosine(query_vector, vector),
                    "record": record,
                }
            )
        hits.sort(key=lambda item: (-float(item["score"]), str(item["id"])))
        return hits[: max(0, int(limit))]

    @staticmethod
    def _matches_visibility(
        record: ContextUnitRecord,
        *,
        operation: str,
        trace_id: str,
        run_id: str,
        case_id: str,
    ) -> bool:
        operation_values = record.tags.get("operation") or record.tags.get("operations") or ""
        operations = {item.strip() for item in str(operation_values).split(",") if item.strip()}
        if operations and operation not in operations:
            return False
        for key, current in (("trace_id", trace_id), ("run_id", run_id), ("case_id", case_id)):
            bound = record.tags.get(key)
            if bound and bound != current:
                return False
        return True

    @staticmethod
    def _append_in_filter(
        conditions: List[str],
        parameters: List[Any],
        column: str,
        values: Optional[Sequence[str]],
        *,
        include: bool,
    ) -> None:
        if values is None:
            return
        normalized = tuple(sorted(set(str(value) for value in values)))
        if not normalized:
            return
        placeholders = ",".join("?" for _ in normalized)
        operator = "IN" if include else "NOT IN"
        conditions.append(f"{column} {operator} ({placeholders})")
        parameters.extend(normalized)
