"""Compare axis verdicts / selection size / organizer cost across process-dossier replay runs.

Usage: python scripts/_compare_process_runs_tmp.py <result-dir> [<result-dir> ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AXES = ("trace_analysis", "intent_understanding", "planning_routing", "tool_execution",
        "context_memory", "knowledge_data", "model_capability")


def load(directory: str, sample: str) -> dict | None:
    path = ROOT / directory / f"{sample}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    results = {r["axis_id"]: r for r in (data.get("axes") or {}).get("results") or []}
    row: dict = {"dir": directory, "seconds": data.get("elapsed_seconds"),
                 "fulfillment": (data.get("judge") or {}).get("overall_fulfillment", {}).get("status")}
    for axis in AXES:
        result = results.get(axis)
        if not result:
            row[axis] = "—"
            continue
        if axis == "trace_analysis":
            usage = result.get("usage") or {}
            audit = ((result.get("output") or {}).get("structure") or {}).get("evidence_audit") or {}
            row[axis] = (f"{result.get('verdict')} refs={usage.get('selected_refs')} "
                         f"reads={usage.get('read_ids')} calls={usage.get('tool_calls')} "
                         f"audit={len(audit.get('reads') or [])}/{len(audit.get('unread') or [])}/"
                         f"{len(audit.get('shape_only') or [])}")
        else:
            checks = (result.get("output") or {}).get("checks") or []
            missing = sum(1 for c in checks if c.get("status") == "insufficient_evidence")
            row[axis] = f"{result.get('verdict')} ({len(checks) - missing}/{len(checks)} 有据)"
    return row


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    dirs = [a for a in args if a.endswith("/")]
    sample = next((a for a in args if not a.endswith("/")), "frozen--snap-cash-value")
    rows = [row for directory in dirs if (row := load(directory.rstrip("/"), sample))]
    width = max((len(r["dir"]) for r in rows), default=10)
    for axis in ("fulfillment", *AXES):
        print(f"{axis:22s} " + " | ".join(f"{str(r.get(axis))[:46]:46s}" for r in rows))
    print(f"{'seconds':22s} " + " | ".join(f"{str(r.get('seconds')):46s}" for r in rows))
    print("目录：" + " | ".join(f"{r['dir']:>{width}s}" for r in rows))


if __name__ == "__main__":
    main()
