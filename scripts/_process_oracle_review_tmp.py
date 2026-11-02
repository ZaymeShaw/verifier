"""One-off: build the human review sheet comparing frozen-trace facts, Judge verdicts and flagged anomalies.

Facts come from sample-facts.json (deterministic read), verdicts from results/*.json, and only
machine-checkable anomalies are flagged (axis failed/blocked, judge not_evaluable, dropped refs,
excluded material, axes disagreeing). Semantic judgments stay with the human.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "report/process-dossier-20260920"
AXES = ("intent_understanding", "planning_routing", "tool_execution", "context_memory",
        "knowledge_data", "model_capability")


def facts_digest(turns: list[dict]) -> list[str]:
    lines = []
    for index, turn in enumerate(turns, start=1):
        request = turn.get("request")
        if isinstance(request, dict):
            body = request.get("body") or {}
            messages = body.get("messages") or []
            question = messages[-1].get("content") if messages else ""
        else:
            question = str(request)
        lines.append(f"- 轮{index} 用户：{str(question)[:200]}")
        for call in turn.get("calls") or []:
            status = call.get("output") or call.get("result") or call.get("arguments") or call.get("reconstructed_input")
            label = call.get("name") or call["kind"]
            text = status if isinstance(status, str) else json.dumps(status, ensure_ascii=False)
            lines.append(f"  - {call['kind']}:{label} → {text[:180]}")
    return lines


def main() -> None:
    facts = {row["name"]: row for row in json.loads((BASE / "sample-facts.json").read_text())}
    results = {}
    for path in sorted((BASE / "results").glob("*.json")):
        results[path.stem] = json.loads(path.read_text())
    lines = ["# E 复评对照表（给人工写标准答案用）", "",
             "事实列由程序从冻结 trace 提取；结论列是本次 Judge 产出；「人工标准答案」留空待填。",
             "只看机器可核的异常：轴 failed/blocked、主轴 not_evaluable、引用被剔除、材料被排除、六轴互相不一致。", ""]
    summary = ["| 样本 | 主轴 | " + " | ".join(AXES) + " | 异常 |", "| --- | --- |" + " --- |" * (len(AXES) + 1)]
    for name, row in results.items():
        report = row.get("axes") or {}
        axes = {r["type_id"]: r for r in report.get("results", [])}
        judge_status = (row.get("judge") or {}).get("overall_fulfillment", {}).get("status")
        flags = []
        for axis_id in AXES:
            result = axes.get(axis_id) or {}
            if result.get("status") in {"failed", "blocked"}:
                flags.append(f"{axis_id}:{result.get('status')}")
            verdict = result.get("verdict")
            view_dropped = ((result.get("output") or {}).get("view") or {}).get("dropped_refs")
            if view_dropped:
                flags.append(f"{axis_id}:剔除引用 {len(view_dropped)}")
            excluded = ((result.get("output") or {}).get("view") or {}).get("excluded") or []
            if excluded:
                flags.append(f"{axis_id}:排除材料 {len(excluded)}")
        verdicts = {axis_id: (axes.get(axis_id) or {}).get("verdict") or (axes.get(axis_id) or {}).get("status") for axis_id in AXES}
        if judge_status == "not_evaluable":
            flags.append("主轴 not_evaluable")
        summary.append("| " + name + " | " + str(judge_status) + " | " + " | ".join(str(verdicts[a]) for a in AXES)
                       + " | " + ("；".join(flags) or "-") + " |")
    lines += summary + [""]
    for name, row in results.items():
        lines.append(f"## {name}")
        lines.append("### 冻结 trace 事实")
        lines += facts_digest((facts.get(name) or {}).get("turns") or [])
        report = row.get("axes") or {}
        axes = {r["type_id"]: r for r in report.get("results", [])}
        lines.append("### 本次 Judge 结论")
        analysis = axes.get("trace_analysis") or {}
        structure = ((analysis.get("output") or {}).get("structure") or {})
        lines.append(f"- 案卷：{analysis.get('verdict')} · 片段 {((analysis.get('output') or {}).get('chunks'))}")
        for action in structure.get("route") or []:
            lines.append(f"  - 路线 {action.get('action')}：{str(action.get('purpose'))[:120]} [{', '.join(action.get('evidence_refs') or [])[:120]}]")
        for axis_id in AXES:
            result = axes.get(axis_id) or {}
            output = result.get("output") or {}
            lines.append(f"- **{axis_id}**：{result.get('verdict') or result.get('status')} — {str((output.get('assessment') or {}).get('reason') or result.get('error'))[:300]}")
            for check in output.get("checks") or []:
                lines.append(f"  - [{check['status']}] {check['check_id']} {str(check.get('finding'))[:200]}")
                if check.get("evidence_refs"):
                    lines.append(f"    ↳ {', '.join(check['evidence_refs'])[:200]}")
                if check.get("missing_evidence"):
                    lines.append(f"    缺证：{str(check['missing_evidence'])[:200]}")
        judge = row.get("judge") or {}
        lines.append(f"- **主轴**：{(judge.get('overall_fulfillment') or {}).get('status')} — {str(judge.get('reasoning_summary'))[:600]}")
        lines.append("### 人工标准答案（待填）")
        lines.append("- 六轴应报：")
        lines.append("- 不应误报：")
        lines.append("")
    (BASE / "oracle-review.md").write_text("\n".join(lines))
    print(f"{len(results)} results -> oracle-review.md")


if __name__ == "__main__":
    main()
