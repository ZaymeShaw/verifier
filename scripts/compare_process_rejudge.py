"""冻结重判对比：旧实现（批次里保存的 eval_axes）vs 新实现（rejudge_process_axes.py 的输出目录）。

输出 P5 需要的统计：每轴 verdict 转移、ρ:repeat 一致性（每个重复环节是否 ρ 与 μ 都给了结果）、
地图外环节、contract_missing 汇总、修复/标注计数、错误用例。可对两个新输出目录比稳定性（--stability）。

用法：
    python scripts/compare_process_rejudge.py --batch report/process-axes-live-20260928/batch-status.json \
        --new report/process-axes-rejudge-20260929/run1 [--stability report/process-axes-rejudge-20260929/run2] \
        [--out report/process-axes-rejudge-20260929/compare.json]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SIX = ("intent_understanding", "planning_routing", "tool_execution", "context_memory", "knowledge_data",
       "model_capability")


def _short(case_id: str) -> str:
    parts = case_id.split("-")
    code = next((p for p in parts if len(p) == 3 and p[0].isalpha() and p[1:].isdigit()), None)
    # 冒烟/通用问答用例没有 A01 式编号：取 smoke-/main- 之后的整段名，保证可读且唯一
    return code or case_id.split("smoke-", 1)[-1].split("main-", 1)[-1]


def load_old(batch: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(batch.read_text())
    data = data.get("data", data)
    return {e["case_id"]: {r["type_id"]: r for r in ((e.get("run") or {}).get("eval_axes") or {}).get("results") or []}
            for e in data["events"]}


def load_new(folder: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(folder.glob("*.json")):
        payload = json.loads(path.read_text())
        out[payload["case_id"]] = ({"__error__": payload["error"]} if payload.get("error") else
                                   {r["type_id"]: r for r in payload["axes"]["results"]})
    return out


def _results(axis: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list(((axis or {}).get("output") or {}).get("results") or [])


def compare(old: dict, new: dict) -> dict[str, Any]:
    transitions: dict[str, Counter] = {a: Counter() for a in SIX}
    per_case: dict[str, dict[str, str]] = {}
    repeat_rows, offmap, contract, flags, repaired, errors = [], [], [], Counter(), [], {}
    outcome_counts: dict[str, Counter] = defaultdict(Counter)
    for case_id, axes in new.items():
        short = _short(case_id)
        if "__error__" in axes:
            errors[short] = axes["__error__"]
            continue
        per_case[short] = {}
        for axis_id in SIX:
            before = (old.get(case_id, {}).get(axis_id) or {}).get("verdict") or "-"
            after = (axes.get(axis_id) or {}).get("verdict") or (axes.get(axis_id) or {}).get("status") or "-"
            transitions[axis_id][f"{before}→{after}"] += 1
            per_case[short][axis_id] = f"{before}→{after}" if before != after else after
            output = (axes.get(axis_id) or {}).get("output") or {}
            if (output.get("view") or {}).get("repaired"):
                repaired.append({"case": short, "axis": axis_id, "notes": output["view"]["repaired"]})
            for r in _results(axes.get(axis_id)):
                outcome_counts[axis_id][r["outcome"]] += 1
                for f in r.get("flags") or []:
                    flags[f"{axis_id}:{f.split('：')[0]}"] += 1
                if r["outcome"] == "contract_missing":
                    contract.append({"case": short, "axis": axis_id, "obligation": r["obligation_id"],
                                     "link": r["link_id"], "expected": r.get("expected", "")})
                if r["link_id"].startswith("new:"):
                    offmap.append({"case": short, "axis": axis_id, "obligation": r["obligation_id"],
                                   "link": r["link_id"], "outcome": r["outcome"], "observed": r.get("observed", "")[:200]})
        # ρ:repeat 一致性：每个重复环节 ρ 必有结果；对应的模型调用 μ:tool_decision 也应有结果。
        rho = [r for r in _results(axes.get("planning_routing")) if r["link_id"].startswith("ρ:repeat:")]
        mu = [r for r in _results(axes.get("model_capability")) if r["obligation_id"] == "tool_decision"]
        for link_id in sorted({r["link_id"] for r in rho}):
            outcomes = {r["obligation_id"]: r["outcome"] for r in rho if r["link_id"] == link_id}
            repeat_rows.append({"case": short, "link": link_id.rsplit("/", 1)[-1], **outcomes,
                                "mu_tool_decision": dict(Counter(r["outcome"] for r in mu))})
    return {"per_case": per_case, "transitions": {a: dict(c) for a, c in transitions.items()},
            "outcomes": {a: dict(c) for a, c in outcome_counts.items()}, "repeat": repeat_rows,
            "offmap": offmap, "contract_missing": contract, "flags": dict(flags.most_common()),
            "repaired": repaired, "errors": errors}


def stability(first: dict, second: dict) -> list[dict[str, Any]]:
    flips = []
    for case_id in sorted(set(first) & set(second)):
        a, b = first[case_id], second[case_id]
        if "__error__" in a or "__error__" in b:
            continue
        for axis_id in SIX:
            left = {(r["obligation_id"], r["link_id"]): r["outcome"] for r in _results(a.get(axis_id))}
            right = {(r["obligation_id"], r["link_id"]): r["outcome"] for r in _results(b.get(axis_id))}
            for key in sorted(set(left) | set(right)):
                if left.get(key) != right.get(key):
                    flips.append({"case": _short(case_id), "axis": axis_id, "obligation": key[0], "link": key[1],
                                  "first": left.get(key), "second": right.get(key)})
    return flips


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--new", required=True, type=Path)
    parser.add_argument("--stability", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    new = load_new(args.new)
    report = compare(load_old(args.batch), new)
    if args.stability:
        report["stability_flips"] = stability(new, load_new(args.stability))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
