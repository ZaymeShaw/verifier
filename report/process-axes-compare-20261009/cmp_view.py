"""逐轴对比：重建的 dossier_view 与导出 prompt 里记录的 dossier_view。

两边都把 shared_ref 还原成正文，先比编号顺序与字段集合，再比字段内容，最后才看 shared# 编号。
用法：python cmp_view.py [--tag TAG] [--axis AXIS] [--detail 3]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import experiment_io as io  # noqa: E402
import doc_rebuild as D  # noqa: E402
from impl.projects.llm_probe.business_trace.materials import material_view  # noqa: E402
from impl.projects.llm_probe.eval_axes.adapters.process_common import _axis_links  # noqa: E402


def unshare(value, shared):
    if isinstance(value, dict):
        if set(value) == {"shared_ref"}:
            return unshare(shared.get(value["shared_ref"]), shared)
        return {k: unshare(v, shared) for k, v in value.items()}
    if isinstance(value, list):
        return [unshare(v, shared) for v in value]
    return value


def share_map(view):
    shared = view.get("shared_contents") or {}
    if isinstance(shared, list):
        return {r["id"]: r.get("body") for r in shared}
    return shared


def normalize(view):
    shared = share_map(view)
    out = []
    for rec in view.get("records") or []:
        fields = {}
        for name, info in (rec.get("fields") or {}).items():
            row = {k: unshare(v, shared) for k, v in info.items()}
            fields[name] = row
        out.append({"id": rec.get("id"), "fields": fields})
    return out


def field_view(records):
    return {r["id"]: r["fields"] for r in records}


def compare(tag, axis, detail):
    frozen = io.load_json(HERE / "frozen" / f"case_{tag}.json")
    dossier = D.build(frozen)
    analysis = D.analysis_output(frozen, dossier)
    links = _axis_links(axis, dossier, analysis["structure"])
    extra = list((analysis.get("selections", {}).get(axis) or {}).get("refs") or [])
    mine = normalize(material_view(dossier, links, list(analysis["structure"].get("suspects") or []),
                                   extra_refs=extra))
    recorded = normalize(frozen["axes"][axis][0]["body"]["dossier_view"])
    result = {"tag": tag, "axis": axis, "recorded_ids": [r["id"] for r in recorded],
              "rebuilt_ids": [r["id"] for r in mine], "diffs": []}
    result["order_equal"] = result["recorded_ids"] == result["rebuilt_ids"]
    rm, mm = field_view(recorded), field_view(mine)
    for rid in result["recorded_ids"]:
        if rid not in mm:
            result["diffs"].append({"id": rid, "issue": "missing_record"})
            continue
        rf, mf = rm[rid], mm[rid]
        if set(rf) != set(mf):
            result["diffs"].append({"id": rid, "issue": "field_set",
                                    "recorded_only": sorted(set(rf) - set(mf)),
                                    "rebuilt_only": sorted(set(mf) - set(rf))})
        for name in sorted(set(rf) & set(mf)):
            if rf[name] != mf[name]:
                result["diffs"].append({"id": rid, "field": name, "issue": "value",
                                        "recorded": rf[name], "rebuilt": mf[name]})
    for rid in result["rebuilt_ids"]:
        if rid not in rm:
            result["diffs"].append({"id": rid, "issue": "extra_record"})
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="smoke-policy-detail-renyanlin")
    ap.add_argument("--axis", default=None)
    ap.add_argument("--detail", type=int, default=3)
    args = ap.parse_args()
    axes = [args.axis] if args.axis else list(io.AXES)
    total = 0
    for axis in axes:
        got = compare(args.tag, axis, args.detail)
        total += len(got["diffs"])
        print(f"{axis}: order_equal={got['order_equal']} records={len(got['recorded_ids'])}/{len(got['rebuilt_ids'])} diffs={len(got['diffs'])}")
        if not got["order_equal"]:
            print("   recorded", got["recorded_ids"])
            print("   rebuilt ", got["rebuilt_ids"])
        for item in got["diffs"][:args.detail]:
            print("   ", json.dumps(item, ensure_ascii=False)[:800])
    print("合计字段差异", total)


if __name__ == "__main__":
    main()
