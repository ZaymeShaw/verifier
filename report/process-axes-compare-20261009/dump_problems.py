"""把两臂的问题条目抽出来，去重、盲化、打乱，供人工独立分类。

- 现行臂：轴记录里的 `issues`，只取 outcome ∈ {fail, contract_missing}（缺证条目不是问题主张）。
- 新方案臂：每批的 `problems`（含程序判定条目，标 verified_by=程序）。
- 有 error / failed / bookkeeping_ok=False 的轴不参与（记录本身无效，见 DEVIATIONS.md）。

盲化：去掉 arm/axis 标签、按固定种子打乱、按证据引用保留 case（判问题必须看案卷）。
输出 `problems.json`（含原始归属）与 `blind_problems.md`（只给分类用）。
"""
from __future__ import annotations

import json
import random
import sys

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import doc_rebuild as D  # noqa: E402

STORED = {"fail", "contract_missing"}
SEED = 20261010


def axis_files(arm: str, pass_no: int):
    """优先取 pass<N>，坏掉的轴依次改用 pass<N>b / c / d 里同名的合格记录（与 current_arm.round_labels 一致）。"""
    root = io.HERE / "runs" / arm / f"pass{pass_no}"
    reruns = [io.HERE / "runs" / arm / f"pass{pass_no}{suffix}" for suffix in ("b", "c", "d")]
    for case_dir in sorted(p for p in root.glob("*") if p.is_dir()):
        for path in sorted(case_dir.glob("*.json")):
            record = io.load_json(path)
            if record.get("failed") or not io.bookkeeping_ok(record):
                alts = [rerun / case_dir.name / path.name for rerun in reruns]
                alts = [alt for alt in alts if alt.exists()]
                good = next((alt for alt in alts
                             if not io.load_json(alt).get("failed") and io.bookkeeping_ok(io.load_json(alt))), None)
                if good is None:
                    continue
                record, path = io.load_json(good), good
            yield path, record


def current_problems(pass_no: int):
    out = []
    for path, record in axis_files("current", pass_no):
        for issue in record.get("issues") or []:
            if issue.get("outcome") not in STORED:
                continue
            out.append({"case": record["tag"], "arm": "current", "axis": record["axis"],
                        "part": "issue", "outcome": issue.get("outcome"),
                        "text": issue.get("phenomenon") or "", "observed": issue.get("observed") or "",
                        "attribution": issue.get("attribution"),
                        "refs": sorted(set((issue.get("input_refs") or []) + (issue.get("output_refs") or []))),
                        "source": f"{path.parent.name}/{path.name}"})
    # 同一 problem_id 会被多个轴引用，去重（保留首次出现，合并轴归属）。
    seen, deduped = {}, []
    for row in out:
        key = (row["case"], row["text"][:120])
        if key in seen:
            seen[key]["axes"] = sorted(set(seen[key]["axes"] + [row["axis"]]))
            continue
        row["axes"] = [row["axis"]]
        seen[key] = row
        deduped.append(row)
    return deduped


def new_key(row):
    """同一包装行为的同一事实只算一条：缺口按缺口原文归并，余量提示/工具返回各按一类归并。"""
    text = row["text"]
    if "缺口" in text:
        return (row["case"], "缺口", text.split("：")[-1][:80])
    if "执行余量" in text:
        return (row["case"], "执行余量提示")
    if "工具返回" in text:
        return (row["case"], "工具返回", "、".join(row["refs"][:1]))
    return (row["case"], text[:120])


def new_problems(pass_no: int, arm: str = "new"):
    out, index = [], {}
    for path, record in axis_files(arm, pass_no):
        for batch in record.get("batches") or []:
            if batch.get("error"):
                continue
            for problem in batch.get("problems") or []:
                row = {"case": record["tag"], "arm": arm, "axis": record["axis"],
                       "part": f"batch{batch['batch']}",
                       "outcome": "fail", "text": problem.get("phenomenon") or "",
                       "observed": problem.get("impact") or "", "attribution": problem.get("attribution"),
                       "verified_by": problem.get("verified_by") or "模型",
                       "refs": sorted(set((problem.get("refs") or []) + (problem.get("items") or []))),
                       "source": f"{path.parent.name}/{path.name}"}
                key = new_key(row)
                if key in index:
                    kept = index[key]
                    kept["axes"] = sorted(set(kept.get("axes", [kept["axis"]]) + [row["axis"]]))
                    kept["parts"] = sorted(set(kept.get("parts", [kept["part"]]) + [row["part"]]))
                    kept["refs"] = sorted(set(kept["refs"] + row["refs"]))
                    if kept["verified_by"] != "程序" and row["verified_by"] == "程序":
                        kept["verified_by"] = "程序"
                    continue
                row["axes"], row["parts"] = [row["axis"]], [row["part"]]
                index[key] = row
                out.append(row)
    return out


V2_AXIS = {"工具返回原样进入下一次模型输入": "tool_execution",
           "执行余量提示随用量更新": "context_memory",
           "交付缺口说明有逐字出处": "context_memory"}


def program_v2_problems():
    """程序判定 v2（program_checks_v2.py，CORRECTION-3）里判「没达到」的条目；与 pass 无关，每 case 一份。"""
    out = []
    for path in sorted((io.HERE / "program_v2").glob("*.json")):
        if path.stem == "summary":
            continue
        payload = io.load_json(path)
        for entry in payload["entries"]:
            if entry["verdict"] != "没达到":
                continue
            out.append({"case": payload["tag"], "arm": "new", "axis": V2_AXIS[entry["check"]],
                        "axes": [V2_AXIS[entry["check"]]], "part": "program_v2", "outcome": "fail",
                        "text": f"{entry['check']}：没达到", "observed": entry["observed"],
                        "attribution": "local", "verified_by": "程序", "refs": entry["refs"],
                        "source": f"program_v2/{path.name}#{entry['id']}",
                        "blind_id": f"V2-{payload['tag']}-{entry['id']}"})
    return out


def impl_problems(pass_no: int):
    """正式实现（impl_check.py → runs/impl/pass<N>）的问题记录：已跨批合并，直接一条一行。"""
    out = []
    for path in sorted((io.HERE / "runs" / "impl" / f"pass{pass_no}").glob("*/*.json")):
        if "before" in path.name:
            continue
        record = io.load_json(path)
        for issue in (record.get("output") or {}).get("issues") or []:
            out.append({"case": record["tag"], "arm": "impl", "axis": record["axis"], "axes": [record["axis"]],
                        "part": "impl", "outcome": "fail", "text": issue["phenomenon"], "observed": issue["observed"],
                        "attribution": issue["attribution_detail"], "verified_by": "模型",
                        "refs": issue["output_refs"], "source": f"{path.parent.name}/{path.name}#{issue['problem_id']}"})
    return out


def main():
    pass_no = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    current = current_problems(pass_no)
    new = new_problems(pass_no)
    program_v2 = program_v2_problems()
    extra = {}
    for extra_arm in ("new2", "new3", "new4"):
        if (io.HERE / "runs" / extra_arm / f"pass{pass_no}").exists():
            extra[extra_arm] = new_problems(pass_no, extra_arm)
    if (io.HERE / "runs" / "impl" / f"pass{pass_no}").exists():
        extra["impl"] = impl_problems(pass_no)
    for extra_arm, rows in extra.items():  # 不进洗牌，已有盲 id 不变
        for n, row in enumerate(rows, 1):
            row["blind_id"] = f"{extra_arm.upper()}-{pass_no}-{n:02d}"
    everything = current + new
    order = list(range(len(everything)))
    random.Random(SEED).shuffle(order)
    for index, position in enumerate(order, 1):
        everything[position]["blind_id"] = f"{'P' if pass_no == 1 else 'Q'}{index:02d}"
    io.save_json(io.HERE / f"problems/pass{pass_no}.json",
                 {"current": current, "new": new, "new_program_v2": program_v2, **extra, "all": everything}, exclusive=False)
    lines = [f"# 盲测问题清单 pass{pass_no}（{len(everything)} 条，已打乱，不含臂标签）", ""]
    for row in sorted(everything, key=lambda r: r["blind_id"]):
        lines += [f"## {row['blind_id']}  case={row['case']}",
                  f"- 主张：{row['text']}",
                  f"- 观察：{row['observed'][:600]}",
                  f"- 证据：{', '.join(row['refs'][:8])}",
                  f"- 归属（模型自述）：{row['attribution']}", ""]
    io.save_text(io.HERE / f"problems/blind_pass{pass_no}.md", "\n".join(lines), exclusive=False)
    print(json.dumps({"pass": pass_no, "current": len(current), "new": len(new),
                      "program_side_new": sum(1 for r in new if r["verified_by"] == "程序")}, ensure_ascii=False))
    for arm, rows in (("current", current), ("new", new)):
        counts = {}
        for row in rows:
            counts[row["case"]] = counts.get(row["case"], 0) + 1
        print(arm, json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
