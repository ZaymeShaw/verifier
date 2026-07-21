from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema.context import ContextRecord, ContextRecordSummary

ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = ROOT / "data" / "context_store"
MAX_PER_PROJECT = 200


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _record_path(project_id: str, trace_id: str, caller: str, created_at: str, record_id: str = "") -> Path:
    ts = created_at or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe_caller = caller.replace("/", "_").replace(":", "_")
    suffix = str(record_id or uuid.uuid4()).replace("/", "_").replace(":", "_")[:12]
    return STORE_DIR / project_id / trace_id / f"{safe_caller}-{ts}-{suffix}.json"


def _record_paths_for_trace(project_id: str, trace_id: str) -> List[Path]:
    dir_path = STORE_DIR / project_id / trace_id
    if not dir_path.exists():
        return []
    return sorted(dir_path.glob("*.json"))


def _record_paths_for_project(project_id: str) -> List[Path]:
    dir_path = STORE_DIR / project_id
    if not dir_path.exists():
        return []
    return sorted(dir_path.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _normalize_record(data: Dict[str, Any]) -> ContextRecord:
    return ContextRecord(
        record_id=str(data.get("record_id") or ""),
        trace_id=str(data.get("trace_id") or ""),
        project_id=str(data.get("project_id") or ""),
        caller=str(data.get("caller") or ""),
        messages=list(data.get("messages") or []),
        response=data.get("response"),
        created_at=str(data.get("created_at") or ""),
        prompt_size=int(data.get("prompt_size") or 0),
        llm_model=str(data.get("llm_model") or ""),
        elapsed_ms=int(data.get("elapsed_ms") or 0),
        error=data.get("error"),
    )


def _record_to_dict(record: ContextRecord) -> Dict[str, Any]:
    return {
        "record_id": record.record_id,
        "trace_id": record.trace_id,
        "project_id": record.project_id,
        "caller": record.caller,
        "messages": record.messages,
        "response": record.response,
        "created_at": record.created_at,
        "prompt_size": record.prompt_size,
        "llm_model": record.llm_model,
        "elapsed_ms": record.elapsed_ms,
        "error": record.error,
    }


def save_context(record: ContextRecord) -> str:
    _ensure_dir(STORE_DIR)
    path = _record_path(
        record.project_id,
        record.trace_id,
        record.caller,
        record.created_at,
        record.record_id,
    )
    _ensure_dir(path.parent)
    path.write_text(json.dumps(_record_to_dict(record), ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_project(record.project_id)
    return path.as_posix()


def load_context(project_id: str, trace_id: str, caller: str) -> Optional[ContextRecord]:
    paths = _record_paths_for_trace(project_id, trace_id)
    for p in paths:
        if caller in p.name:
            try:
                return _normalize_record(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
    return None


def load_contexts_by_trace(project_id: str, trace_id: str) -> List[ContextRecord]:
    records: List[ContextRecord] = []
    for p in _record_paths_for_trace(project_id, trace_id):
        try:
            records.append(_normalize_record(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    records.sort(key=lambda r: r.created_at)
    return records


def list_recent_contexts(project_id: str, *, caller: str = "", limit: int = 20) -> List[ContextRecordSummary]:
    paths = _record_paths_for_project(project_id)
    result: List[ContextRecordSummary] = []
    for p in paths:
        if len(result) >= limit:
            break
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if caller and data.get("caller") != caller:
            continue
        result.append(ContextRecordSummary(
            record_id=str(data.get("record_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            project_id=str(data.get("project_id") or ""),
            caller=str(data.get("caller") or ""),
            prompt_size=int(data.get("prompt_size") or 0),
            llm_model=str(data.get("llm_model") or ""),
            elapsed_ms=int(data.get("elapsed_ms") or 0),
            created_at=str(data.get("created_at") or ""),
            error=data.get("error"),
        ))
    return result


def _prune_project(project_id: str) -> None:
    tracks = _record_paths_for_project(project_id)
    if len(tracks) <= MAX_PER_PROJECT:
        return
    for p in tracks[MAX_PER_PROJECT:]:
        try:
            p.unlink()
        except Exception:
            pass
