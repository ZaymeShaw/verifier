"""TASK.md §3.2 要求的抽查：从盲测并集里确定性抽 ≥30%，由 Verifier 手工归类，再与模型归类算一致率。

用法：
  python spot_check.py sample   → 写 score/spot_check_sample.json（供 Verifier 阅读）
  python spot_check.py report   → 读 score/spot_check_labels.json，与 classification.json 比对，写 score/spot_check.md
"""
from __future__ import annotations

import json
import random
import sys

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

SEED = 20261010
RATIO = 0.35


def rows():
    path = io.HERE / "blind_problems.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sample():
    all_rows = rows()
    picked = sorted(random.Random(SEED).sample(all_rows, max(1, int(len(all_rows) * RATIO))),
                    key=lambda row: row["id"])
    out = [{"id": row["id"], "case": row["case"], "claim": row["claim"],
            "observed": (row["observed"] or "")[:300], "refs": row["refs"][:6]} for row in picked]
    io.save_json(io.HERE / "score/spot_check_sample.json", out, exclusive=False)
    print(json.dumps({"union": len(all_rows), "sampled": len(out),
                      "ratio": round(len(out) / len(all_rows), 3), "file": "score/spot_check_sample.json"}))


def report():
    labels_path = io.HERE / "score/spot_check_labels.json"
    labels = io.load_json(labels_path) if labels_path.exists() else {}
    model = io.load_json(io.HERE / "classification.json") if (io.HERE / "classification.json").exists() else {}
    root = io.HERE / "problems/blind_key.jsonl"
    keymap = {json.loads(line)["id"]: json.loads(line) for line in root.read_text(encoding="utf-8").splitlines() if line.strip()}
    lines = ["# 抽查一致率（TASK.md §3.2）", "",
             f"- 盲测并集：{len(rows())} 条；抽查：{len(labels)} 条",
             f"- 判定字段：verdict / gold_id（抽查只判到这一级，不细分 T/F 子码）", ""]
    stats = {"verdict": [0, 0], "gold_id": [0, 0]}
    detail = []
    for uid, mine in sorted(labels.items()):
        judged = model.get(uid) or {}
        row = {"id": uid, "case": (keymap.get(uid) or {}).get("case") or "", "mine": mine, "model": judged}
        for field in stats:
            if not mine.get(field) and not judged.get(field):
                continue
            stats[field][1] += 1
            if (mine.get(field) or "").replace("none", "") == (judged.get(field) or "").replace("none", ""):  # 空与 none 同义：无对应清单项
                stats[field][0] += 1
            else:
                row.setdefault("diff", []).append(field)
        if row.get("diff"):
            detail.append(row)
    for field, (hit, total) in stats.items():
        lines.append(f"- {field} 一致：{hit}/{total} = {round(hit / total, 3) if total else 'n/a'}")
    lines += ["", "## 分歧明细", ""]
    for row in detail:
        lines.append(f"- {row['id']}（{row['case']}）分歧字段 {row['diff']}："
                     f"人工 {json.dumps(row['mine'], ensure_ascii=False)} / 模型 "
                     f"{json.dumps({k: row['model'].get(k) for k in row['diff']}, ensure_ascii=False)}")
    io.save_text(io.HERE / "score/spot_check.md", "\n".join(lines) + "\n", exclusive=False)
    print("\n".join(lines[:8]))


if __name__ == "__main__":
    {"sample": sample, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
