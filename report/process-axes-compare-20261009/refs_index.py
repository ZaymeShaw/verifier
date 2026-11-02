"""程序核验用的案卷索引：每个 case 里可解析的记录 id 集合（triage_rules.md §6 具体性 / F1）。

索引 = `frozen/case_<tag>.json` 的 `records` 键（含嵌套 span 路径）+ 交付 payload。
写 `score/refs_index.json`，供 score.py 的引用核验使用。
"""
from __future__ import annotations

import sys

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))


def build():
    out = {}
    for tag in io.CASES:
        frozen = io.load_json(io.HERE / "frozen" / f"case_{tag}.json")
        out[tag] = sorted(set((frozen.get("records") or {}).keys()) | {"turn1.delivered_output"})
    return out


def main():
    index = build()
    io.save_json(io.HERE / "score/refs_index.json", index, exclusive=False)
    print({tag: len(rows) for tag, rows in index.items()})


if __name__ == "__main__":
    main()
