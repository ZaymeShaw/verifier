"""把两臂四遍的问题条目合成一份盲测集合：去掉来源标记、统一打乱、写 blind_problems.jsonl。

- 输入：problems/pass<N>.json（dump_problems.py 产出的 {current, new, all}）。
- 输出：
  - `blind_problems.jsonl`：每题一行 {id, case, claim, observed, refs, attribution}，无臂标签、无 pass 标签。
  - `problems/blind_key.jsonl`：id → 来源（arm/pass/blind_id/axis/verified_by/source），只给评分脚本用。
"""
from __future__ import annotations

import hashlib
import json
import random
import sys

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

SEED = 20261010


def union_id(arm: str, pass_no: int, blind_id: str) -> str:
    """盲测 id 由来源确定性派生（哈希），这样新增 pass 后重建并集不会作废已完成的归类。"""
    return "U" + hashlib.sha1(f"{arm}|{pass_no}|{blind_id}".encode()).hexdigest()[:8]


def load_passes():
    rows = []
    for path in sorted((io.HERE / "problems").glob("pass*.json")):
        pass_no = int(path.stem.replace("pass", ""))
        payload = io.load_json(path)
        for arm in ("current", "new"):
            for row in payload.get(arm) or []:
                rows.append({"arm": arm, "pass": pass_no, "row": row})
        for row in payload.get("new_program_v2") or []:
            rows.append({"arm": "new", "pass": pass_no, "row": row})
        for extra_arm in ("new2", "new3", "new4", "impl"):
            for row in payload.get(extra_arm) or []:
                rows.append({"arm": extra_arm, "pass": pass_no, "row": row})
    return rows


def main():
    rows = load_passes()
    order = list(range(len(rows)))
    random.Random(SEED).shuffle(order)
    blind, key = [], []
    for index, position in enumerate(order, 1):
        item = rows[position]
        row = item["row"]
        uid = union_id(item["arm"], item["pass"], row["blind_id"])
        blind.append({"id": uid, "case": row["case"], "claim": row["text"],
                      "observed": row.get("observed") or "", "refs": row.get("refs") or [],
                      "attribution": row.get("attribution")})
        key.append({"id": uid, "arm": item["arm"], "pass": item["pass"], "case": row["case"],
                    "blind_id": row.get("blind_id"), "axis": row.get("axis"),
                    "axes": row.get("axes") or [], "verified_by": row.get("verified_by") or "模型",
                    "source": row.get("source")})
    io.save_text(io.HERE / "blind_problems.jsonl",
                 "\n".join(json.dumps(row, ensure_ascii=False) for row in blind) + "\n", exclusive=False)
    io.save_text(io.HERE / "problems/blind_key.jsonl",
                 "\n".join(json.dumps(row, ensure_ascii=False) for row in key) + "\n", exclusive=False)
    counts = {}
    for item in key:
        counts[(item["arm"], item["pass"])] = counts.get((item["arm"], item["pass"]), 0) + 1
    print(json.dumps({"union": len(blind),
                      "by_source": {f"{a}/pass{p}": c for (a, p), c in sorted(counts.items())}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
