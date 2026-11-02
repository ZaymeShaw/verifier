"""B3 同批对比：基线（逐段读全文）vs 现在（清单 + 侦探），逐样本逐轴比结论、缺证与证据视图尺寸。

用法：python scripts/_b3_comparison_tmp.py [新结果目录] [基线目录]
默认新结果 report/process-dossier-20260920/verify-b3-full，基线 report/process-dossier-20260920/results。
离线：视图尺寸由保存的案卷 + 选段 + 整理员回执重建，不打 LLM。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from impl.projects.llm_probe.business_trace import dossier as dossier_module  # noqa: E402
from impl.projects.llm_probe.business_trace.dossier import (  # noqa: E402
    VIEW_BUDGET_CHARS, build_axis_view)

NEW = ROOT / "report/process-dossier-20260920/verify-b3-full"
BASE = ROOT / "report/process-dossier-20260920/results"
AXES = ("trace_analysis", "intent_understanding", "planning_routing", "tool_execution",
        "context_memory", "knowledge_data", "model_capability")
OUT = ROOT / "report/process-dossier-20260920/evidence-index"


def _load(directory: Path) -> dict[str, dict]:
    rows = {}
    for path in sorted(directory.glob("*.json")):
        try:
            rows[path.stem] = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
    return rows


def _axes(data: dict) -> dict[str, dict]:
    return {r["axis_id"]: r for r in ((data.get("axes") or {}).get("results") or [])}


def _checks(result: dict) -> list[dict]:
    return (result.get("output") or {}).get("checks") or []


def _view_chars(data: dict, axis: str, *, uncapped: bool = False) -> int:
    """本轴视图字符数：按生产口径（单条记录超限只给读过的片段），或按「不限单条」口径。"""
    organizer = _axes(data).get("trace_analysis") or {}
    output = organizer.get("output") or {}
    dossier = output.get("dossier")
    if not isinstance(dossier, dict) or axis == "trace_analysis":
        return 0
    slot = (output.get("selections") or {}).get(axis) or {}
    saved = dossier_module.EVIDENCE_NODE_CHARS
    if uncapped:
        dossier_module.EVIDENCE_NODE_CHARS = 10 ** 9
    try:
        view = build_axis_view(dossier, slot, budget_chars=VIEW_BUDGET_CHARS, axis_id=axis,
                               structure=output.get("structure"))
    finally:
        dossier_module.EVIDENCE_NODE_CHARS = saved
    return len(json.dumps(view, ensure_ascii=False, default=str))


def main() -> None:
    new_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else NEW
    base_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else BASE
    new, base = _load(new_dir), _load(base_dir)
    shared = [name for name in new if name in base]
    rows = []
    for name in shared:
        row: dict = {"name": name}
        na, ba = _axes(new[name]), _axes(base[name])
        row["fulfillment"] = ((new[name].get("judge") or {}).get("overall_fulfillment") or {}).get("status")
        row["fulfillment_base"] = ((base[name].get("judge") or {}).get("overall_fulfillment") or {}).get("status")
        for axis in AXES:
            n, b = na.get(axis), ba.get(axis)
            row[f"{axis}"] = (n or {}).get("verdict")
            row[f"{axis}__base"] = (b or {}).get("verdict")
            nchecks, bchecks = _checks(n or {}), _checks(b or {})
            row[f"{axis}__evidence"] = sum(1 for c in nchecks if c.get("status") != "insufficient_evidence")
            row[f"{axis}__checks"] = len(nchecks)
            row[f"{axis}__missing"] = sum(1 for c in nchecks if c.get("status") == "insufficient_evidence")
            row[f"{axis}__missing_base"] = sum(1 for c in bchecks if c.get("status") == "insufficient_evidence")
            row[f"{axis}__view_chars"] = _view_chars(new[name], axis)
            row[f"{axis}__view_chars_uncapped"] = _view_chars(new[name], axis, uncapped=True)
            row[f"{axis}__view_chars_base"] = _view_chars(base[name], axis)
        organizer = (na.get("trace_analysis") or {})
        usage = organizer.get("usage") or {}
        row["organizer"] = {key: usage.get(key) for key in
                            ("selected_refs", "read_ids", "tool_calls", "catalog_chars", "llm_attempts",
                             "llm_failed_attempts", "llm_endpoint")}
        audit = ((organizer.get("output") or {}).get("structure") or {}).get("evidence_audit") or {}
        row["audit"] = {key: len(audit.get(key) or []) for key in
                        ("reads", "unread", "shape_only", "unknown", "axes_without_evidence")}
        row["audit"]["axes_missing_needs"] = audit.get("axes_missing_needs") or {}
        rows.append(row)

    lines: list[str] = []
    lines.append(f"# B3 同批对比（{len(rows)} 个共同样本）\n")
    fulfilled = sum(1 for row in rows if row["fulfillment"] == row["fulfillment_base"])
    lines.append(f"主轴 fulfillment 与基线一致：{fulfilled}/{len(rows)}\n")
    lines.append("| 轴 | 结论与基线一致 | 检查项 现在/基线 | 缺证项 现在→基线 | 缺证率 现在→基线 | 视图字符 现在/不限单条/基线 |")
    lines.append("|---|---|---|---|---|---|")
    for axis in AXES:
        same = sum(1 for row in rows if row.get(axis) == row.get(f"{axis}__base"))
        missing_new = sum(row.get(f"{axis}__missing") or 0 for row in rows)
        missing_base = sum(row.get(f"{axis}__missing_base") or 0 for row in rows)
        checks_new = sum(row.get(f"{axis}__checks") or 0 for row in rows)
        checks_base = sum((row.get(f"{axis}__checks") or 0) - (row.get(f"{axis}__missing") or 0)
                          + (row.get(f"{axis}__missing_base") or 0) for row in rows)
        views_new = [row[f"{axis}__view_chars"] for row in rows if row.get(f"{axis}__view_chars")]
        views_uncapped = [row[f"{axis}__view_chars_uncapped"] for row in rows
                          if row.get(f"{axis}__view_chars_uncapped")]
        views_base = [row[f"{axis}__view_chars_base"] for row in rows if row.get(f"{axis}__view_chars_base")]
        fmt = lambda xs: f"{int(sum(xs) / len(xs))}（中位 {int(median(xs))}，最大 {max(xs)}）" if xs else "—"
        rate_new = f"{100 * missing_new / checks_new:.0f}%" if checks_new else "—"
        rate_base = f"{100 * missing_base / checks_base:.0f}%" if checks_base else "—"
        lines.append(f"| {axis} | {same}/{len(rows)} | {checks_new}/{checks_base} | {missing_new}→{missing_base} "
                     f"| {rate_new}→{rate_base} | {fmt(views_new)} / {fmt(views_uncapped)} / {fmt(views_base)} |")
    organizer_rows = [row["organizer"] for row in rows]
    lines.append("\n## 整理阶段\n")
    for key in ("selected_refs", "read_ids", "tool_calls", "catalog_chars", "llm_attempts", "llm_failed_attempts"):
        values = [r.get(key) for r in organizer_rows if isinstance(r.get(key), (int, float))]
        if values:
            lines.append(f"- {key}: 平均 {sum(values) / len(values):.1f}，中位 {median(values)}，合计 {int(sum(values))}")
    endpoints: dict[str, int] = {}
    for row in organizer_rows:
        endpoints[str(row.get("llm_endpoint"))] = endpoints.get(str(row.get("llm_endpoint")), 0) + 1
    lines.append(f"- 端点分布: {endpoints}")
    audits = [row["audit"] for row in rows]
    lines.append("- 审计合计: " + json.dumps({key: sum(a.get(key) or 0 for a in audits)
                                              for key in ("reads", "unread", "shape_only", "unknown")}, ensure_ascii=False))
    flagged = {row["name"]: row["audit"]["axes_missing_needs"] for row in rows if row["audit"]["axes_missing_needs"]}
    lines.append(f"- 触发「轴缺依赖类别」的样本: {len(flagged)}/{len(rows)}")
    for name, flag in list(flagged.items())[:8]:
        lines.append(f"  - {name}: {json.dumps(flag, ensure_ascii=False)}")
    flips = []
    for row in rows:
        for axis in AXES:
            if row.get(axis) != row.get(f"{axis}__base"):
                flips.append(f"{row['name']} {axis}: {row.get(f'{axis}__base')} → {row.get(axis)}")
    lines.append(f"\n## 结论变化（{len(flips)} 处）\n")
    for axis in AXES:
        flips_axis = [f for f in flips if f.split()[1] == axis]
        if flips_axis:
            lines.append(f"### {axis}（{len(flips_axis)}）")
            lines.extend(f"- {item}" for item in flips_axis)
    lines.append("\n### 全部变化")
    lines.extend(f"- {item}" for item in flips)

    report = "\n".join(lines)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "b3-comparison.md").write_text(report)
    (OUT / "b3-comparison.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1))
    print(report)


if __name__ == "__main__":
    main()
