"""按题目来源给每道题标场景类型，追加 type 列。

来源（source 列，如 生产/faq_log）由题库路径决定，不依赖任何模型预测。映射见 SOURCE_TYPES：
- 名字能对应到单一类型的来源，直接标该类型；
- MIXED_SOURCES 里的来源混着多种问题，标 MIXED，留到业务系统实跑后按实际调用的工具再分；
- 其余来源标 UNMAPPED，打印出来，由人决定归到哪类。

用法：
    python scripts/annotate_type.py --input annotated.xlsx --output typed.xlsx
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cluster_sample import read_records, write_records  # noqa: E402

SOURCE_TYPES = {
    "外部/product_qa": "产品知识",
    "生产/product_qa_log": "产品知识",
    "外部/benefit_qa": "权益服务",
    "生产/benefit_qa_log": "权益服务",
    "生产/faq_log": "业务办理与FAQ",
    "外部/client_search": "客户筛选",
    "生产/client_search_badcase": "客户筛选",
    "生产/client_ops_weekly": "客户筛选",
    "外部/policy_search": "保单筛选",
}
MIXED_SOURCES = {"生产/practical_llm_log", "生产/practice_qa_eval", "生产/practice_qa_weekly", "生产/standard_llm_log"}
MIXED = "混合（待实跑按工具分）"
UNMAPPED = "未分类"
TYPE_COLUMN = "type"


def source_type(source: str) -> str:
    if source in SOURCE_TYPES:
        return SOURCE_TYPES[source]
    return MIXED if source in MIXED_SOURCES else UNMAPPED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    records, columns = read_records(args.input)
    if "source" not in columns or TYPE_COLUMN in columns:
        print("错误：输入须有 source 列且不能已有 type 列", file=sys.stderr)
        return 2
    output = [{**r, TYPE_COLUMN: source_type(str(r["source"]))} for r in records]
    write_records(args.output, output, [*columns, TYPE_COLUMN])
    counts = Counter(r[TYPE_COLUMN] for r in output)
    print(f"共 {len(output)} 条：" + "，".join(f"{k} {v}" for k, v in counts.most_common()))
    unmapped = Counter(str(r["source"]) for r in output if r[TYPE_COLUMN] == UNMAPPED)
    if unmapped:
        print("未分类的来源：" + "，".join(f"{k} {v}" for k, v in unmapped.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
