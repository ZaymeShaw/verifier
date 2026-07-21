from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence

from .models import ContextUnitRecord


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SQLiteContextDatabase:
    """Shared SQLite boundary for the Registry and Vector Index."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialized = False
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            with self.connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS context_units (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL,
                        content TEXT,
                        content_ref TEXT,
                        project_id TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        roles_json TEXT NOT NULL,
                        unit_type TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        source_hash TEXT NOT NULL,
                        description_hash TEXT NOT NULL,
                        embedding_model TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        CHECK ((content IS NOT NULL AND content_ref IS NULL)
                            OR (content IS NULL AND content_ref IS NOT NULL))
                    );
                    CREATE INDEX IF NOT EXISTS idx_context_units_project_status
                        ON context_units(project_id, status);
                    CREATE INDEX IF NOT EXISTS idx_context_units_scope_type
                        ON context_units(scope, unit_type, source_type);

                    CREATE TABLE IF NOT EXISTS context_unit_roles (
                        unit_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        PRIMARY KEY (unit_id, role),
                        FOREIGN KEY (unit_id) REFERENCES context_units(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_context_unit_roles_role
                        ON context_unit_roles(role, unit_id);

                    CREATE TABLE IF NOT EXISTS context_vectors (
                        unit_id TEXT PRIMARY KEY,
                        model_id TEXT NOT NULL,
                        vector_json TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        unit_type TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        description_hash TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (unit_id) REFERENCES context_units(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_context_vectors_filter
                        ON context_vectors(project_id, status, scope, unit_type, source_type);
                    """
                )
            self._initialized = True

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()


class SQLiteContextRegistry:
    def __init__(self, database: SQLiteContextDatabase):
        self.database = database

    def transaction(self):
        return self.database.transaction()

    @contextmanager
    def _connection(self, transaction: Any = None):
        if transaction is not None:
            yield transaction
        else:
            with self.database.reader() as connection:
                yield connection

    def get(self, unit_id: str, *, transaction: Any = None) -> Optional[Mapping[str, Any]]:
        with self._connection(transaction) as connection:
            row = connection.execute("SELECT * FROM context_units WHERE id = ?", (unit_id,)).fetchone()
        return self._row_to_entry(row) if row is not None else None

    def get_many(self, unit_ids: Sequence[str], *, transaction: Any = None) -> Mapping[str, Mapping[str, Any]]:
        ids = tuple(dict.fromkeys(str(unit_id) for unit_id in unit_ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._connection(transaction) as connection:
            rows = connection.execute(
                f"SELECT * FROM context_units WHERE id IN ({placeholders})", ids
            ).fetchall()
        return {str(row["id"]): self._row_to_entry(row) for row in rows}

    def list_entries(self, project_id: str) -> Sequence[Mapping[str, Any]]:
        with self.database.reader() as connection:
            rows = connection.execute(
                "SELECT * FROM context_units WHERE project_id = ? ORDER BY id",
                (str(project_id),),
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def upsert(
        self,
        record: ContextUnitRecord,
        *,
        source_hash: str,
        description_hash: str,
        embedding_model: str,
        transaction: Any,
    ) -> None:
        existing = transaction.execute(
            "SELECT created_at FROM context_units WHERE id = ?", (record.id,)
        ).fetchone()
        now = _utc_now()
        created_at = str(existing["created_at"]) if existing else now
        transaction.execute(
            """
            INSERT INTO context_units (
                id, name, description, content, content_ref, project_id, scope,
                roles_json, unit_type, source_type, status, tags_json,
                source_hash, description_hash, embedding_model, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                content = excluded.content,
                content_ref = excluded.content_ref,
                project_id = excluded.project_id,
                scope = excluded.scope,
                roles_json = excluded.roles_json,
                unit_type = excluded.unit_type,
                source_type = excluded.source_type,
                status = excluded.status,
                tags_json = excluded.tags_json,
                source_hash = excluded.source_hash,
                description_hash = excluded.description_hash,
                embedding_model = excluded.embedding_model,
                updated_at = excluded.updated_at
            """,
            (
                record.id,
                record.name,
                record.description,
                record.content,
                record.content_ref,
                record.project_id,
                record.scope,
                _stable_json(list(record.roles)),
                record.unit_type,
                record.source_type,
                record.status,
                _stable_json(dict(record.tags)),
                source_hash,
                description_hash,
                embedding_model,
                created_at,
                now,
            ),
        )
        transaction.execute("DELETE FROM context_unit_roles WHERE unit_id = ?", (record.id,))
        transaction.executemany(
            "INSERT INTO context_unit_roles(unit_id, role) VALUES (?, ?)",
            [(record.id, role) for role in record.roles],
        )

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> Dict[str, Any]:
        record = ContextUnitRecord(
            id=str(row["id"]),
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
        return {
            "record": record,
            "source_hash": str(row["source_hash"]),
            "description_hash": str(row["description_hash"]),
            "embedding_model": str(row["embedding_model"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
