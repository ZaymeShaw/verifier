"""对全部 case × 六轴跑 cmp_view.compare，输出汇总（重建充分性证据）。

用法：python cmp_all.py
产出：cmp_view/<tag>.json（每 case 每轴 diffs）与 stdout 汇总表。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import experiment_io as io  # noqa: E402
import cmp_view as C  # noqa: E402


def main():
    index = io.load_json(HERE / "frozen" / "index.json")
    rows = []
    for tag in index["cases"]:
        summary = {}
        for axis in io.AXES:
            got = C.compare(tag, axis, 0 if False else 3)
            summary[axis] = {
                "order_equal": got["order_equal"],
                "records": [len(got["recorded_ids"]), len(got["rebuilt_ids"])],
                "diffs": len(got["diffs"]),
                "first": got["diffs"][:3],
            }
            rows.append((tag, axis, len(got["diffs"])))
        io.save_json(HERE / "cmp_view" / f"{tag}.json", summary, exclusive=False)
        total = sum(v["diffs"] for v in summary.values())
        bad = [k for k, v in summary.items() if v["diffs"] or not v["order_equal"]]
        print(f"{tag}: diffs={total} order_ok={not bad} {bad if bad else ''}", flush=True)
    print("TOTAL", sum(r[2] for r in rows))


if __name__ == "__main__":
    main()
