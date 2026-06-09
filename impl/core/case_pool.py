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
    return json.loads(STORE_PATH.read_text(encoding="utf-8"))


def _write_store(data: Dict[str, List[Dict[str, Any]]]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_case_pools(project_id: str) -> List[Dict[str, Any]]:
    pools = _read_store().get(project_id, [])
    return [{key: value for key, value in pool.items() if key != "cases"} for pool in pools]


def save_case_pool(project_id: str, name: str, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    data = _read_store()
    pools = data.get(project_id, [])
    pool = {
        "id": f"pool-{int(time.time() * 1000)}",
        "name": name or f"未命名用例池 {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "case_count": len(cases),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cases": cases,
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
