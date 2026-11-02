"""把 benchmark/questions/<来源>/<文件>.jsonl 汇总成聚类输入：每行 id、source、scenario、turns。

source 为「来源/文件名」（如 生产/faq_log），按文件路径排序输出，文件内保持原顺序。

用法：
    python scripts/export_questions.py --output input-questions.jsonl [--bench <benchmark 目录>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_BENCH = Path("/Users/xiaozijian/WorkSpace/package/insurance_qa_agent/insurance-qa-agent/benchmark")
FIELDS = ("id", "scenario", "turns")


def export(questions: Path) -> list[dict]:
    rows, seen = [], set()
    for path in sorted(questions.glob("*/*.jsonl")):
        source = f"{path.parent.name}/{path.stem}"
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            q = json.loads(line)
            if q["id"] in seen:
                raise ValueError(f"重复 id：{q['id']}（{path}）")
            seen.add(q["id"])
            rows.append({"id": q["id"], "source": source, "scenario": q["scenario"], "turns": q["turns"]})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bench", type=Path, default=DEFAULT_BENCH, help="benchmark 目录")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = export(args.bench / "questions")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} 题 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
