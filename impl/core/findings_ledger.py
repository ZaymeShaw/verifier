"""发现台账（spec/mock/protocol.md 5.4）。

harness 的探索记忆与交付物之一。每个项目一个 JSON 文件；同 signature 去重，
harness_verdict 与 judge_verdict 一致 → live_defect，不一致 → judge_calibration，
protocol-fuzz 会话固定 protocol_fuzz。
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
REALISM = ("high", "medium", "low")
VERDICTS = ("fulfilled", "not_fulfilled")
JUDGE_VERDICTS = ("fulfilled", "not_fulfilled", "not_evaluable", None)
CATEGORIES = ("live_defect", "judge_calibration", "protocol_fuzz")

_LOCK = threading.Lock()


def ledger_path(project_id: str) -> Path:
    return data_root(ROOT.parent) / project_id / "ledger.json"


def _read(project_id: str) -> List[Dict[str, Any]]:
    path = ledger_path(project_id)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _write(project_id: str, records: List[Dict[str, Any]]) -> None:
    path = ledger_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_active_artifact("findings_ledger", path, records, repository_root=ROOT.parent)


def categorize(harness_verdict: str, judge_verdict: Optional[str], *, protocol_fuzz: bool) -> str:
    if protocol_fuzz:
        return "protocol_fuzz"
    if judge_verdict is None:
        # 未经 judge：只有 harness 自评，暂按 live_defect 记，judge_verdict 保持 null 可见。
        return "live_defect"
    return "live_defect" if judge_verdict == harness_verdict else "judge_calibration"


def add(
    project_id: str,
    *,
    signature: str,
    session_id: str,
    trigger_summary: str,
    realism: str,
    harness_verdict: str,
    judge_verdict: Optional[str] = None,
    protocol_fuzz: bool = False,
    run_id: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    """追加一条发现。同 signature 已存在时不计新发现，返回 {new: False, record: 既有记录}。"""
    signature = str(signature or "").strip()
    if not signature:
        raise ValueError("signature is required")
    if realism not in REALISM:
        raise ValueError(f"realism must be one of {REALISM}")
    if harness_verdict not in VERDICTS:
        raise ValueError(f"harness_verdict must be one of {VERDICTS}")
    if judge_verdict not in JUDGE_VERDICTS:
        raise ValueError(f"judge_verdict must be one of {JUDGE_VERDICTS}")
    record = {
        "signature": signature,
        "session_id": str(session_id or ""),
        "trigger_summary": str(trigger_summary or ""),
        "realism": realism,
        "harness_verdict": harness_verdict,
        "judge_verdict": judge_verdict,
        "category": categorize(harness_verdict, judge_verdict, protocol_fuzz=protocol_fuzz),
        "run_id": str(run_id or ""),
        "notes": str(notes or ""),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with _LOCK:
        records = _read(project_id)
        existing = next((item for item in records if item.get("signature") == signature), None)
        if existing is not None:
            existing.setdefault("duplicate_sessions", [])
            if record["session_id"] and record["session_id"] not in existing["duplicate_sessions"]:
                existing["duplicate_sessions"].append(record["session_id"])
            _write(project_id, records)
            return {"new": False, "record": existing}
        records.append(record)
        _write(project_id, records)
    return {"new": True, "record": record}


def query(
    project_id: str,
    *,
    category: Optional[str] = None,
    signature: Optional[str] = None,
    session_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    records = _read(project_id)
    if category:
        records = [item for item in records if item.get("category") == category]
    if signature:
        records = [item for item in records if item.get("signature") == signature]
    if session_id:
        records = [
            item for item in records
            if item.get("session_id") == session_id or session_id in (item.get("duplicate_sessions") or [])
        ]
    if run_id:
        records = [item for item in records if item.get("run_id") == run_id]
    counts: Dict[str, int] = {}
    for item in records:
        counts[str(item.get("category"))] = counts.get(str(item.get("category")), 0) + 1
    return {"project_id": project_id, "total": len(records), "by_category": counts, "records": records}
