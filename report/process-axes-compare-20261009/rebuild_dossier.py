"""从六轴 prompt 里记录的 dossier_view 反推程序内部案卷，并核对能否还原已记录的环节表。

实验里"现行臂"要在同一上游输入上重跑六轴；上游的案卷与选材没有落在导出 trace 里，
只能从六轴 prompt 中记录的 dossier_view（材料视图）合并还原成 dossier，再用仓库代码
的 build_links / material_view 重算，并逐条比对已记录环节表，确认还原充分。

用法：
  python rebuild_dossier.py --check           # 比对 8 个 case 的环节表/材料视图，打印差异
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import experiment_io as io

sys.path.insert(0, str(io.ROOT))


def frozen_path(tag: str) -> Path:
    return io.HERE / "frozen" / f"case_{tag}.json"


def load_frozen(tag: str) -> dict:
    return json.loads(frozen_path(tag).read_text())


def recorded_links(frozen: dict, axis: str) -> list[dict]:
    """该轴已记录的运行环节（跨批次取并集），并记录 match_candidates。"""
    links, seen = [], set()
    for batch in frozen["axes"][axis]:
        info = ((batch.get("body") or {}).get("links") or {})
        for link in info.get("links", []) or []:
            if link["link_id"] not in seen:
                seen.add(link["link_id"])
                links.append(link)
    return links


def rebuild(frozen: dict) -> dict:
    """把材料视图合并结果还原成 dossier（records/contents/model_calls/sources/gaps/coverage）。"""
    records = [dict(rec, id=ref) for ref, rec in frozen["records"].items()]
    by_id = {r["id"]: r for r in records}
    turns = sorted({r.get("turn") for r in records if r.get("turn")})
    model_calls = []
    for ref, rec in sorted(by_id.items()):
        if rec.get("kind") != "model_calls":
            continue
        fields = rec.get("fields") or {}
        exact = (fields.get("exact_request") or {}).get("status") == "available"
        model_calls.append({"id": ref, "turn": rec.get("turn"), "scope": rec.get("scope", "current"),
                            "exact_request": {"status": "available" if exact else "missing"},
                            "output_message_ref": None, "reconstructed_input": {"status": "reconstructed", "message_refs": []}})
    calls = {c["id"]: c for c in model_calls}
    for axis in io.AXES:
        for link in recorded_links(frozen, axis):
            lid = link["link_id"]
            if lid.startswith("model_capability:"):
                call = calls.get(lid.split(":", 1)[1])
                if call and link.get("output"):
                    ref, field = link["output"][0]["ref"], link["output"][0].get("field")
                    if field == "content":
                        call["output_message_ref"] = ref
                    if link["facts"].get("input_source") == "exact_request":
                        call["exact_request"] = {"status": "available"}
            elif lid.startswith("context_memory:input:"):
                call = calls.get(lid.split(":")[-1])
                if call:
                    refs = [e["ref"] for e in link.get("output", []) if e.get("field") == "content"]
                    if refs:
                        call["reconstructed_input"]["message_refs"] = list(dict.fromkeys(
                            call["reconstructed_input"]["message_refs"] + refs))
                    elif link.get("output") and link["output"][0].get("field") == "exact_request":
                        call["exact_request"] = {"status": "available"}
            elif lid.startswith("context_memory:tool→model:") and "→" in lid:
                call = calls.get(lid.rpartition("→")[2])
                if call:
                    refs = [e["ref"] for e in link.get("output", []) if e.get("field") == "content"]
                    call["reconstructed_input"]["message_refs"] = list(dict.fromkeys(
                        call["reconstructed_input"]["message_refs"] + refs))
            elif lid.startswith("intent_understanding:"):
                for end in link.get("output", []):
                    if end.get("field") == "tool_calls" and end["ref"] in calls:
                        calls[end["ref"]]["output_message_ref"] = calls[end["ref"]]["output_message_ref"]
    for call in model_calls:
        rec = by_id.get(call["id"]) or {}
        for ref, row in by_id.items():
            if row.get("kind") == "messages" and row.get("role") == "assistant" and row.get("run_id") and rec.get("run_id") == row.get("run_id"):
                pass
    gaps, sources = {}, {}
    for axis in io.AXES:
        for batch in frozen["axes"][axis]:
            body = batch.get("body") or {}
            for gap in ((body.get("dossier_view") or {}).get("gaps") or []):
                gaps[gap["id"]] = gap
    for turn in turns:
        sources[turn] = {"id": turn, "turn": turn}
    return {"records": records, "contents": {}, "model_calls": model_calls,
            "sources": [sources[t] for t in turns], "gaps": list(gaps.values()), "coverage": []}


def check(tag: str) -> dict:
    from impl.projects.llm_probe.business_trace.links import build_links
    from impl.projects.llm_probe.eval_axes.adapters.process_common import _axis_links
    frozen = load_frozen(tag)
    dossier = rebuild(frozen)
    structure = {"suspects": []}
    report = {}
    for axis in io.AXES:
        recorded = [l for l in recorded_links(frozen, axis) if l.get("origin") != "expectation_deduction"]
        got = [l for l in _axis_links(axis, dossier, structure) if not l["link_id"].endswith(":none")]
        rec_ids = sorted(l["link_id"] for l in recorded)
        got_ids = sorted(l["link_id"] for l in got)
        rec_by = {l["link_id"]: l for l in recorded}
        got_by = {l["link_id"]: l for l in got}
        diff = []
        for lid in sorted(set(rec_ids) | set(got_ids)):
            if lid not in got_by:
                diff.append({"link_id": lid, "issue": "missing_in_rebuild"})
            elif lid not in rec_by:
                diff.append({"link_id": lid, "issue": "extra_in_rebuild"})
            else:
                a, b = rec_by[lid], got_by[lid]
                for key in ("link_type", "turn", "input", "output", "facts"):
                    if json.dumps(a.get(key), sort_keys=True, ensure_ascii=False) != json.dumps(b.get(key), sort_keys=True, ensure_ascii=False):
                        diff.append({"link_id": lid, "issue": f"diff:{key}", "recorded": a.get(key), "rebuilt": b.get(key)})
        report[axis] = {"recorded": len(rec_ids), "rebuilt": len(got_ids), "diffs": diff}
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    io.init_secret_guard()
    tags = [args.tag] if args.tag else list(io.CASES)
    total = {}
    for tag in tags:
        if args.check:
            report = check(tag)
            bad = sum(len(v["diffs"]) for v in report.values())
            total[tag] = {"bad": bad, "axes": {a: (v["recorded"], v["rebuilt"], len(v["diffs"])) for a, v in report.items()}}
            print(f"{tag}: diffs={bad} " + " ".join(f"{a}={v['recorded']}/{v['rebuilt']}({len(v['diffs'])})" for a, v in report.items()))
            if bad:
                for axis, v in report.items():
                    for d in v["diffs"][:6]:
                        print("   ", axis, json.dumps(d, ensure_ascii=False)[:400])
    io.save_json(io.HERE / "rebuild" / "check.json", total)


if __name__ == "__main__":
    main()
