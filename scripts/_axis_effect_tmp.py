"""对比三版实现的「轴真实效果」：结论对照 + 引用可核查性。

三版：results/(原始：整棵案卷全倒) · verify-b3-full(B3：清单+逐条读) · verify-cat-full(目录+批量取件)
用法：python scripts/_axis_effect_tmp.py [run1,run2,...]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "report/process-dossier-20260920"
AXES = [
    "intent_understanding",
    "planning_routing",
    "tool_execution",
    "context_memory",
    "knowledge_data",
    "model_capability",
]
REF = re.compile(r"\b(?:turn\d|content#\d+|turn\d\.gap\.[a-z_]+|turn\d/[A-Za-z0-9_#/.]+)")


def axes_of(path: Path):
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    raw = data["axes"]
    axes = {row["type_id"]: row for row in (raw if isinstance(raw, list) else raw["results"])}
    return data, axes


def dossier_ids(stem: str) -> set[str]:
    """案卷的全部编号（用于「引用是否真实存在」核验）。"""
    from impl.core.schema import RunTrace, normalize_run_trace
    from impl.projects.llm_probe.business_trace.dossier import build_dossier, dossier_ids as ids_of

    kind, name = stem.split("--", 1)
    if kind == "frozen":
        snapshot = json.loads((ROOT / "report/business-trace-agno-20260913/snapshots" / f"{name}.json").read_text())
        run = snapshot["records"]["run"]
        request = run.get("run_input") if isinstance(run.get("run_input"), dict) else {}
        trace = RunTrace(
            trace_id=f"replay-{name}", project_id="llm_probe", case_id=f"frozen-{name[5:]}",
            normalized_request={"capability_ref": "x", "body": request.get("body") or {"messages": [{"role": "user", "content": "x"}]}},
            extracted_output={"output_text": run.get("content")}, project_fields={"business_trace": snapshot},
        )
        snapshot = trace.project_fields["business_trace"]
    else:
        trace = normalize_run_trace(json.loads((OUT / "clean-traces" / f"{name}.json").read_text()))
        snapshot = trace.project_fields["business_trace"]
    return ids_of(build_dossier(trace, snapshot))


def cited_refs(axis: dict) -> list[str]:
    out = axis.get("output") or {}
    found: list[str] = []
    for check in out.get("checks") or []:
        found += list(check.get("evidence_refs") or [])
    found += list(out.get("evidence_refs") or [])
    return [r for r in found if isinstance(r, str)]


def row(axis: dict, known: set[str]) -> dict:
    out = axis.get("output") or {}
    checks = out.get("checks") or []
    status = {}
    for check in checks:
        status[str(check.get("status"))] = status.get(str(check.get("status")), 0) + 1
    selection = set((out.get("selection") or {}).get("refs") or [])
    cited = cited_refs(axis)
    view = out.get("view") or {}
    return {
        "verdict": axis.get("verdict"),
        "checks": status,
        "checks_n": len(checks),
        "selection_n": len(selection),
        "view_chars": view.get("chars"),
        "view_records": view.get("records"),
        "dropped": list(view.get("dropped_refs") or []),
        "cited_n": len(cited),
        "cited_unique": len(set(cited)),
        "cited_not_selected": sorted({r for r in cited if r not in selection}),
        "cited_missing": sorted({r for r in cited if r not in known}),
        "missing_evidence_n": len(out.get("missing_evidence") or []),
        "desc": (axis.get("verdict_description") or axis.get("summary") or "")[:80],
    }


def main() -> None:
    runs = sys.argv[1].split(",") if len(sys.argv) > 1 else ["results", "verify-b3-full", "verify-cat-full"]
    stems = sorted(p.stem for p in (OUT / runs[-1]).glob("*.json"))
    print(f"对比轮次：{' · '.join(runs)}    样本数 {len(stems)}\n")
    for stem in stems:
        known = dossier_ids(stem)
        per_run = {}
        for run in runs:
            got = axes_of(OUT / run / f"{stem}.json")
            per_run[run] = None if got is None else {a: row(got[1][a], known) for a in AXES if a in got[1]}
            per_run[run + "__judge"] = None if got is None else (got[0].get("judge") or {}).get("overall_fulfillment")
        print("=" * 118)
        print(f"{stem}   案卷编号 {len(known)}")
        print(f"{'轴':22s}" + "".join(f"{r.replace('verify-','')[:14]:>16s}" for r in runs))
        for axis in AXES:
            cells = []
            for run in runs:
                cell = (per_run[run] or {}).get(axis)
                cells.append("—" if cell is None else f"{cell['verdict'] or '·'}")
            print(f"{axis:22s}" + "".join(f"{c:>16s}" for c in cells))
        print(f"{'主轴 fulfillment':22s}" + "".join(f"{str(per_run[r + '__judge']):>16s}" for r in runs))
        print("\n  [引用可核查性] 引用条数 / 未在本轴选段里 / 案卷里不存在 / 选段被剔(无正文回执) / 缺证项 / 视图")
        for axis in AXES:
            for run in runs:
                cell = (per_run[run] or {}).get(axis)
                if cell is None:
                    continue
                print(
                    f"  {run.replace('verify-', '')[:12]:12s} {axis:22s} 引用 {cell['cited_n']:>3d}"
                    f" 越界 {len(cell['cited_not_selected']):>3d} 不存在 {len(cell['cited_missing']):>3d}"
                    f" 剔除 {len(cell['dropped']):>3d} 缺证 {cell['missing_evidence_n']:>2d}"
                    f" | 选段 {cell['selection_n']:>3d} 视图 {str(cell['view_chars'] or 0):>7s}字/{cell['view_records']}条"
                    f" | {cell['checks']}"
                )
            print()


if __name__ == "__main__":
    main()
