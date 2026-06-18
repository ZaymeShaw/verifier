from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT / "data" / "case_pools.json"


def _read_store() -> Dict[str, List[Dict[str, Any]]]:
    if not STORE_PATH.exists():
        return {}
    return _sanitize_store(json.loads(STORE_PATH.read_text(encoding="utf-8")))


def _write_store(data: Dict[str, List[Dict[str, Any]]]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sanitize_store(data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    sanitized: Dict[str, List[Dict[str, Any]]] = {}
    for project_id, pools in (data or {}).items():
        sanitized_pools = []
        for pool in pools or []:
            clean_pool = dict(pool)
            clean_pool["cases"] = [_strip_transient(case) for case in clean_pool.get("cases") or [] if isinstance(case, dict)]
            clean_pool["case_count"] = len(clean_pool["cases"])
            sanitized_pools.append(clean_pool)
        sanitized[project_id] = sanitized_pools
    return sanitized


def compact_case_pool_store() -> Dict[str, Any]:
    before_size = STORE_PATH.stat().st_size if STORE_PATH.exists() else 0
    data = _read_store()
    _write_store(data)
    after_size = STORE_PATH.stat().st_size if STORE_PATH.exists() else 0
    return {"before_size": before_size, "after_size": after_size, "project_count": len(data)}


def list_case_pools(project_id: str) -> List[Dict[str, Any]]:
    pools = _read_store().get(project_id, [])
    return [{key: value for key, value in pool.items() if key != "cases"} for pool in pools]


TRANSIENT_CASE_FIELDS = {
    "trace", "judge", "attribute", "frontend_view", "cluster", "check",
    "raw_response", "raw_model_output", "trace_id", "conversation_summary",
    "turn_traces", "error", "retry_attempt", "reasoning_summary",
}


def _strip_transient(case: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in case.items() if key not in TRANSIENT_CASE_FIELDS}


def save_case_pool(project_id: str, name: str, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    data = _read_store()
    pools = data.get(project_id, [])
    durable_cases = [_strip_transient(case) for case in cases]
    pool = {
        "id": f"pool-{int(time.time() * 1000)}",
        "name": name or f"未命名用例池 {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "case_count": len(durable_cases),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cases": durable_cases,
    }
    data[project_id] = [pool] + [item for item in pools if item.get("name") != pool["name"]]
    _write_store(data)
    return pool


def load_case_pool(project_id: str, pool_id: str) -> Dict[str, Any]:
    for pool in _read_store().get(project_id, []):
        if pool.get("id") == pool_id:
            return pool
    raise KeyError(f"case pool not found: {pool_id}")


def delete_case_pool(project_id: str, pool_id: str) -> Dict[str, Any]:
    data = _read_store()
    before = data.get(project_id, [])
    data[project_id] = [pool for pool in before if pool.get("id") != pool_id]
    _write_store(data)
    return {"deleted": len(before) != len(data[project_id]), "id": pool_id}
