from __future__ import annotations

import json
import hashlib
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .active_artifacts import ActiveArtifactContext, DEFAULT_ACTIVE_ARTIFACT_REGISTRY
from .config import ROOT as REPOSITORY_ROOT, get_runtime_config
from .portable_artifact import write_active_artifact
from .schema.context import ContextRecord, ContextRecordSummary

MAX_PER_PROJECT = get_runtime_config().context.max_records_per_project
_ACTIVE_ARTIFACT_CONTEXT: ActiveArtifactContext | None = None


def _artifact_context() -> ActiveArtifactContext:
    return _ACTIVE_ARTIFACT_CONTEXT or DEFAULT_ACTIVE_ARTIFACT_REGISTRY.context(REPOSITORY_ROOT)


def _store_dir() -> Path:
    return DEFAULT_ACTIVE_ARTIFACT_REGISTRY.family("context_record").base_path(_artifact_context())


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _record_path(project_id: str, trace_id: str, caller: str, created_at: str, record_id: str = "") -> Path:
    ts = created_at or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe_caller = caller.replace("/", "_").replace(":", "_")
    suffix = str(record_id or uuid.uuid4()).replace("/", "_").replace(":", "_")[:12]
    return _store_dir() / project_id / trace_id / f"{safe_caller}-{ts}-{suffix}.json"


def _record_paths_for_trace(project_id: str, trace_id: str) -> List[Path]:
    dir_path = _store_dir() / project_id / trace_id
    if not dir_path.exists():
        return []
    return sorted(dir_path.glob("*.json"))


def _record_paths_for_project(project_id: str) -> List[Path]:
    dir_path = _store_dir() / project_id
    if not dir_path.exists():
        return []
    # 并发落档时别的线程可能刚把某个文件裁掉：列出后、取 mtime 前消失的直接跳过
    stamped = []
    for p in dir_path.rglob("*.json"):
        try:
            stamped.append((p.stat().st_mtime, p))
        except FileNotFoundError:
            continue
    return [p for _, p in sorted(stamped, key=lambda x: x[0], reverse=True)]


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
        governance=dict(data.get("governance") or {}),
        retry_count=int(data.get("retry_count") or 0),
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
        "governance": record.governance,
        "retry_count": record.retry_count,
    }


def _record_fingerprint(record: ContextRecord) -> str:
    """内容与结果完全相同的记录视为同一次逻辑调用的重复落档。"""
    payload = json.dumps(
        {"messages": record.messages, "error": record.error, "response": record.response},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    import hashlib
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dedupe_duplicate_records(record: ContextRecord) -> int:
    """删除同一 trace/caller 下内容与结果完全相同的旧记录，返回被删除数量。

    重试会造成同一个 prompt + 同一个结果被重复落档（实测 500 条里 76 组 2–3 条），
    把真正的历史挤出滚动窗口。只声称“完全相同”的重复，首轮失败、次轮成功这类
    结果不同的调用不会被合并；不携带 prompt 的记录不参与合并。"""
    if not record.messages:
        return 0
    removed = 0
    fingerprint = _record_fingerprint(record)
    for path in _record_paths_for_trace(record.project_id, record.trace_id):
        if not path.name.startswith(f"{record.caller.replace('/', '_').replace(':', '_')}-"):
            continue
        try:
            existing = _normalize_record(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if existing.record_id == record.record_id:
            continue
        if _record_fingerprint(existing) != fingerprint:
            continue
        removed += 1 + existing.retry_count
        try:
            path.unlink()
        except Exception:
            pass
    return removed


def save_context(record: ContextRecord) -> str:
    context = _artifact_context()
    _ensure_dir(_store_dir())
    record.retry_count += _dedupe_duplicate_records(record)
    path = _record_path(
        record.project_id,
        record.trace_id,
        record.caller,
        record.created_at,
        record.record_id,
    )
    _ensure_dir(path.parent)
    write_active_artifact(
        "context_record",
        path,
        _record_to_dict(record),
        context=context,
    )
    _prune_project(record.project_id)
    return path.as_posix()


def load_context(project_id: str, trace_id: str, caller: str) -> Optional[ContextRecord]:
    """trace 下该 caller 最近的一条记录。同 caller 可能有多条（重试、ToolLoop 按段落档）。"""
    records = [r for r in load_contexts_by_trace(project_id, trace_id) if r.caller == caller]
    return records[-1] if records else None


def load_contexts_by_trace(project_id: str, trace_id: str) -> List[ContextRecord]:
    records: List[ContextRecord] = []
    for p in _record_paths_for_trace(project_id, trace_id):
        try:
            records.append(_normalize_record(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    records.sort(key=lambda r: r.created_at)
    return records


def _runtime_stage(response: Any) -> str:
    runtime = response.get("runtime") if isinstance(response, dict) else None
    return str(runtime.get("stage") or "") if isinstance(runtime, dict) else ""


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
            retry_count=int(data.get("retry_count") or 0),
            stage=_runtime_stage(data.get("response")),
            governance_blocking=bool(
                ((data.get("governance") or {}).get("gate") or {}).get("blocking")
            ),
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
