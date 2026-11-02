"""按 benchmark 的标签集和 hard_case.yaml 给题目表打上 tags 和是否 hard case，按 id 关联。

判定逻辑直接复用 benchmark/tools/tags.py（load_hard_case、hard_case），与 classifier/batch.py pick 一致：
1. tags：标签集 labels/<NAME>.jsonl 里该题的全部标签（JSON 列表，原样合并在一列）。
2. 生效标签：hard_case.yaml 的难点标签和 exclude 标签中，只保留标签集 meta.yaml 的 usable 里的。
3. hard：命中任一生效难点标签、且不命中任何生效 exclude 标签；hard_hits 为命中的难点标签。
标签集里没有的题，tags / hard / hard_hits 留空，并打印条数。

输入、输出：CSV、JSONL 或 XLSX，按扩展名识别；保留全部原始列和行序，末尾追加 tags、hard、hard_hits。

用法：
    python scripts/annotate_hard.py --input sampled.xlsx --output annotated.xlsx \
        [--bench <benchmark 目录>] [--labels jev-v0.9-56b5683ad5eb] [--id-column id]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cluster_sample import read_records, write_records  # noqa: E402

DEFAULT_BENCH = Path("/Users/xiaozijian/WorkSpace/package/insurance_qa_agent/insurance-qa-agent/benchmark")
DEFAULT_LABELS = "jev-v0.9-56b5683ad5eb"
OUTPUT_COLUMNS = ("tags", "hard", "hard_hits")


def load_rule(bench: Path, labels: str) -> tuple[dict[str, list[str]], Any]:
    """返回 ({id: tags}, 判定函数 tags -> (是否 hard, 命中的难点标签))。"""
    sys.path.insert(0, str(bench / "tools"))
    import tags as bench_tags  # benchmark/tools/tags.py

    meta = yaml.safe_load((bench / "labels" / f"{labels}.meta.yaml").read_text(encoding="utf-8"))
    if "usable" not in meta:
        raise ValueError(f"标签集 {labels} 的 meta 没有 usable，不能按可用标签判 hard case")
    usable = set(meta["usable"])
    rule = bench_tags.load_hard_case()
    hard = [t for t in rule["hard"] if t in usable]
    exclude = [t for t in rule["exclude"] if t in usable]
    rows = (json.loads(line) for line in (bench / "labels" / f"{labels}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip())
    tags_by_id = {r["id"]: r["tags"] for r in rows}

    def judge(tags: list[str]) -> tuple[bool, list[str]]:
        is_hard, hits, _ = bench_tags.hard_case(tags, hard, exclude)
        return is_hard, hits

    return tags_by_id, judge


def annotate(records: list[dict[str, Any]], id_column: str, tags_by_id: dict[str, list[str]],
             judge: Any) -> tuple[list[dict[str, Any]], int]:
    """返回 (加了三列的记录, 标签集里没有的条数)。"""
    out, missing = [], 0
    for r in records:
        tags = tags_by_id.get(str(r[id_column]))
        if tags is None:
            missing += 1
            out.append({**r, "tags": None, "hard": None, "hard_hits": None})
            continue
        is_hard, hits = judge(tags)
        out.append({**r, "tags": tags, "hard": is_hard, "hard_hits": hits})
    return out, missing


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bench", type=Path, default=DEFAULT_BENCH, help="benchmark 目录")
    parser.add_argument("--labels", default=DEFAULT_LABELS, help="标签集名，对应 labels/<NAME>.jsonl 和 .meta.yaml")
    parser.add_argument("--id-column", default="id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    records, columns = read_records(args.input)
    clash = [c for c in OUTPUT_COLUMNS if c in columns]
    if clash:
        print(f"错误：输入已包含输出列 {clash}", file=sys.stderr)
        return 2
    if any(r.get(args.id_column) in (None, "") for r in records):
        print(f"错误：有记录缺少 {args.id_column}", file=sys.stderr)
        return 2
    tags_by_id, judge = load_rule(args.bench, args.labels)
    output, missing = annotate(records, args.id_column, tags_by_id, judge)
    write_records(args.output, output, [*columns, *OUTPUT_COLUMNS])
    n_hard = sum(1 for r in output if r["hard"])
    print(f"共 {len(output)} 条，hard {n_hard} 条，非 hard {len(output) - n_hard - missing} 条，标签集里没有 {missing} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
