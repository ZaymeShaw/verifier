"""One-off: dump the decision-relevant raw facts of each frozen sample for human oracle writing.

Deterministic reading only (no LLM): per turn, the user request, the gate/route decision,
tool and backend calls with their result status, the final answer and the collection gaps.
Writes report/process-dossier-20260920/sample-facts.json and .md.
"""
from __future__ import annotations

import json
from pathlib import Path

from impl.core.schema import normalize_run_trace
from impl.projects.llm_probe.business_trace import open_reader

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "report/business-trace-agno-20260913/snapshots"
CLEAN = ROOT / "report/process-dossier-20260920/clean-traces"
OUT = ROOT / "report/process-dossier-20260920"


def _short(value, limit=400):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


def _turn_facts(snapshot, request):
    reader = open_reader(snapshot)
    facts = {"request": request, "collection": snapshot.get("status"),
             "errors": snapshot.get("errors") or [], "calls": [], "answer": None, "gaps": []}
    for kind, name in (("runs", "run"), ("steps", None)):
        for entry in reader.entries:
            if entry["kind"] != kind or entry.get("scope") != "current":
                continue
            if kind == "runs":
                facts["answer"] = _short(reader.value(entry, "content"), 1500)
            elif entry.get("name") in {"gate", "direct", "finalize", "agent_input"}:
                facts["calls"].append({"kind": "step", "name": entry.get("name"),
                                       "ref": entry["ref"], "output": _short(reader.value(entry, "output"))})
    for entry in reader.entries:
        if entry["kind"] != "tool_calls" or entry.get("scope") != "current" or entry.get("copy_of"):
            continue
        if entry.get("representation") != "api":
            continue
        if entry.get("name") == "get_skill_instructions":
            continue
        facts["calls"].append({"kind": "tool", "name": entry.get("name"), "ref": entry["ref"],
                               "arguments": _short(reader.value(entry, "arguments")),
                               "result": _short(reader.value(entry, "result"))})
    for entry in reader.entries:
        if entry["kind"] == "model_calls" and entry.get("scope") == "current" and not entry.get("copy_of"):
            facts["calls"].append({"kind": "model_call", "ref": entry["ref"],
                                   "reconstructed_input": (entry.get("reconstructed_input") or {}).get("status"),
                                   "token_check": ((entry.get("reconstructed_input") or {}).get("token_check") or {}).get("result")})
    for name, limitation in reader.limitations.items():
        detail = {"status": limitation.get("status"), "reason": _short(limitation.get("reason"), 200)} \
            if isinstance(limitation, dict) else {"status": _short(limitation, 120)}
        facts["gaps"].append({"id": name, **detail})
    return facts


def sample(name: str, path: Path, frozen: bool) -> dict:
    payload = json.loads(path.read_text())
    if frozen:
        run = payload["records"]["run"]
        turns = [_turn_facts(payload, run.get("run_input") or {"user": run.get("input")})]
    else:
        trace = normalize_run_trace(payload)
        turns = []
        for record in trace.turn_records or []:
            snapshot = (record.get("project_fields") or {}).get("business_trace") or {}
            turns.append(_turn_facts(snapshot, record.get("request")) if snapshot.get("records")
                         else {"request": record.get("request"), "collection": snapshot.get("status"), "errors": snapshot.get("errors") or []})
    return {"name": name, "sample": str(path.relative_to(ROOT)), "turns": turns}


def main() -> None:
    rows = [sample(f"frozen--{p.stem}", p, True) for p in sorted(FROZEN.glob("snap-*.json"))]
    rows += [sample(f"clean--{p.stem}", p, False) for p in sorted(CLEAN.glob("*.json"))]
    (OUT / "sample-facts.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    lines = ["# 冻结样本原始事实（Judge 运行前，供人工写标准答案）", ""]
    for row in rows:
        lines.append(f"## {row['name']}")
        for index, turn in enumerate(row["turns"], start=1):
            lines.append(f"### turn{index}")
            lines.append(f"- 用户请求：{_short(turn.get('request'), 600)}")
            lines.append(f"- 采集：{turn.get('collection')} 错误：{_short(turn.get('errors'), 200)}")
            for call in turn.get("calls") or []:
                detail = call.get("output") or call.get("result") or call.get("arguments") or call.get("reconstructed_input")
                lines.append(f"- {call['kind']} {call.get('name') or ''} [{call.get('ref')}] {_short(detail, 300)}")
            if turn.get("answer"):
                lines.append(f"- 最终答复：{_short(turn['answer'], 800)}")
            for gap in turn.get("gaps") or []:
                lines.append(f"- 限制：{gap.get('id')} {_short({k: v for k, v in gap.items() if k != 'id'}, 200)}")
        lines.append("")
    (OUT / "sample-facts.md").write_text("\n".join(lines))
    print(f"{len(rows)} samples -> sample-facts.json / sample-facts.md")


if __name__ == "__main__":
    main()
