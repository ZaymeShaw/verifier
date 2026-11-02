"""探索批次（spec/mock/protocol.md 5.1）。

用户在探索页给出"探索方向"（direction），harness 以 run_id 领取它作为参考而非任务；
探索结束后 harness 把探索报告（report）写回同一条记录。会话与台账本身分别在
session_store / findings_ledger 中，按 run_id 关联，本模块只保管方向与报告。
"""
from __future__ import annotations

from .instances import data_root

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .portable_artifact import write_active_artifact

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("persona", "scripted", "adaptive-replay", "boundary", "drift")
DIRECTION_KEYS = ("coverage_targets", "focus", "strategy_hints", "budget")
BUDGET_KEYS = ("sessions", "tokens", "wall_clock_ms")
REPORT_KEYS = ("run_id", "sessions", "findings", "coverage", "budget_usage", "notes")

_LOCK = threading.Lock()


def explorations_path(project_id: str) -> Path:
    return data_root(ROOT.parent) / project_id / "explorations.json"


def _read(project_id: str) -> List[Dict[str, Any]]:
    path = explorations_path(project_id)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _write(project_id: str, records: List[Dict[str, Any]]) -> None:
    path = explorations_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_active_artifact("exploration_runs", path, records, repository_root=ROOT.parent)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_direction(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("direction must be an object")
    unknown = set(raw) - set(DIRECTION_KEYS)
    if unknown:
        raise ValueError(f"direction has unknown keys: {sorted(unknown)}")
    targets = raw.get("coverage_targets") or []
    if not isinstance(targets, list) or not all(isinstance(item, str) and item for item in targets):
        raise ValueError("direction.coverage_targets must be a list of scenario names")
    hints = raw.get("strategy_hints") or []
    if not isinstance(hints, list) or any(item not in STRATEGIES for item in hints):
        raise ValueError(f"direction.strategy_hints must be a subset of {list(STRATEGIES)}")
    budget_raw = raw.get("budget") or {}
    if not isinstance(budget_raw, dict) or set(budget_raw) - set(BUDGET_KEYS):
        raise ValueError(f"direction.budget keys must be a subset of {list(BUDGET_KEYS)}")
    budget = {}
    for key in BUDGET_KEYS:
        value = budget_raw.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"direction.budget.{key} must be a positive integer")
        budget[key] = value
    return {
        "coverage_targets": list(targets),
        "focus": str(raw.get("focus") or ""),
        "strategy_hints": list(hints),
        "budget": budget,
    }


def normalize_report(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("report must be an object")
    unknown = set(raw) - set(REPORT_KEYS)
    if unknown:
        raise ValueError(f"report has unknown keys: {sorted(unknown)}")
    sessions = raw.get("sessions")
    if not isinstance(sessions, int) or isinstance(sessions, bool) or sessions < 0:
        raise ValueError("report.sessions must be a non-negative integer")
    coverage = raw.get("coverage") or {}
    if not isinstance(coverage, dict) or not all(isinstance(v, int) for v in coverage.values()):
        raise ValueError("report.coverage must map scenario -> session_count")
    usage = raw.get("budget_usage") or {}
    if not isinstance(usage, dict) or set(usage) - set(BUDGET_KEYS):
        raise ValueError(f"report.budget_usage keys must be a subset of {list(BUDGET_KEYS)}")
    findings = raw.get("findings")
    if findings is not None and not isinstance(findings, dict):
        raise ValueError("report.findings must be the ledger query snapshot (object) or null")
    return {
        "sessions": sessions,
        "findings": findings,
        "coverage": dict(coverage),
        "budget_usage": dict(usage),
        "notes": str(raw.get("notes") or ""),
    }


def save_direction(project_id: str, run_id: str, direction: Any) -> Dict[str, Any]:
    """新建或覆盖一个批次的探索方向；已有报告的批次不可再改方向。"""
    if not run_id or not isinstance(run_id, str):
        raise ValueError("run_id is required")
    normalized = normalize_direction(direction)
    with _LOCK:
        records = _read(project_id)
        for record in records:
            if record.get("run_id") == run_id:
                if record.get("report"):
                    raise ValueError(f"exploration {run_id!r} already has a report; open a new run_id")
                record["direction"] = normalized
                record["updated_at"] = _now()
                _write(project_id, records)
                return record
        record = {
            "run_id": run_id,
            "project_id": project_id,
            "created_at": _now(),
            "updated_at": _now(),
            "direction": normalized,
            "report": None,
            "report_at": None,
        }
        records.append(record)
        _write(project_id, records)
        return record


def save_report(project_id: str, run_id: str, report: Any) -> Dict[str, Any]:
    normalized = normalize_report(report)
    normalized["run_id"] = run_id
    with _LOCK:
        records = _read(project_id)
        for record in records:
            if record.get("run_id") == run_id:
                record["report"] = normalized
                record["report_at"] = _now()
                record["updated_at"] = record["report_at"]
                _write(project_id, records)
                return record
    raise KeyError(f"exploration not found: {run_id}")


def get(project_id: str, run_id: str) -> Dict[str, Any]:
    for record in _read(project_id):
        if record.get("run_id") == run_id:
            return record
    raise KeyError(f"exploration not found: {run_id}")


def list_runs(project_id: str) -> List[Dict[str, Any]]:
    return sorted(_read(project_id), key=lambda item: str(item.get("created_at") or ""), reverse=True)


def delete(project_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        records = _read(project_id)
        kept = [item for item in records if item.get("run_id") != run_id]
        if len(kept) == len(records):
            return None
        _write(project_id, kept)
    return {"run_id": run_id, "deleted": True}
