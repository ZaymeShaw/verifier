"""按簇规模分配名额，从带簇 id 的批次数据中抽出一个数据集，其他列原样保留。

两步：
1. 重映射簇 id：统计每个簇的大小，大小落在 tail_bins 某档内的簇改成该档的长尾簇 id，
   其余簇保持原 id。--tail-bins 1,3,5 表示 {1}、{2-3}、{4-5} 三档，分别得到
   tail:1、tail:2-3、tail:4-5；大于 5 的簇不变。结果写进新列 new_cluster_id。
2. 按 new_cluster_id 抽样：每个新簇权重 n^alpha，按权重瓜分 total；
   未被合并且大小 <= single_max_size 的小簇固定抽 1 条（保底且封顶），先从 total 中扣除；
   其余簇按 n^alpha 瓜分剩余名额，单簇名额不超过 min(n, cluster_cap)，超出部分按权重分给其他簇；
   取整后在簇内随机抽。
   给了 --fine-column 时，未被合并且大小 > single_max_size 的簇不再按 n^alpha 分配，而是按细簇 id
   拆开，每个细簇固定抽 1 条（与小簇同样计入保底）。细簇须嵌套在簇内，通常由 embed_cluster.py
   --fine-threshold 在同一棵树上按更高阈值切出。

记录按行区分，id 列允许重复，只用于校验字段存在。

输入：CSV（有表头）、JSONL 或 XLSX（第一个 sheet，首行表头），按扩展名识别，须包含 --id-column 和 --cluster-column 两列。
输出：被抽中的原始行（所有列不变，保持输入顺序），末尾追加三列：
  new_cluster_id：抽样用的新簇 id（被拆开的大簇为细簇 id）；
  segment：所在分段，由 --tail-bins 和 --single-max-size 自动推出，例如 1,3 和 5 得到
    tail:1、tail:2-3、small:4-5（每簇固定 1 条）、normal:>=6（按 n^alpha 分配）；
    给了 --fine-column 时 normal 段改为 split:>=6（按细簇拆开，每个细簇 1 条）；
  cluster_size：原簇大小；
格式按输出文件扩展名决定。--report 输出每个新簇的大小、配额和抽取数。

用法：
    python scripts/cluster_sample.py --input batch.csv --output sampled.csv \
        [--id-column id] [--cluster-column cluster_id] [--total 1000] [--alpha 0.6] \
        [--tail-bins 1,3] [--cluster-cap 10] [--single-max-size 5] [--fine-column fine_cluster_id] \
        [--rounding pps] [--seed 42] [--report report.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROUNDING_MODES = ("pps", "largest_remainder")
NEW_CLUSTER_COLUMN = "new_cluster_id"
SEGMENT_COLUMN = "segment"
CLUSTER_SIZE_COLUMN = "cluster_size"
OUTPUT_COLUMNS = (NEW_CLUSTER_COLUMN, SEGMENT_COLUMN, CLUSTER_SIZE_COLUMN)


@dataclass(frozen=True)
class SampleConfig:
    total: int = 1000
    alpha: float = 0.6
    tail_bins: tuple[int, ...] = (1, 3)
    cluster_cap: int | None = None
    single_max_size: int = 5
    rounding: str = "pps"
    seed: int = 42
    id_column: str = "id"
    cluster_column: str = "cluster_id"
    fine_column: str | None = None

    def __post_init__(self) -> None:
        if self.total <= 0:
            raise ValueError("total 必须是正整数")
        if self.alpha < 0:
            raise ValueError("alpha 不能为负")
        bins = list(self.tail_bins)
        if any(b <= 0 for b in bins) or bins != sorted(set(bins)):
            raise ValueError("tail_bins 必须是严格递增的正整数列表")
        if self.cluster_cap is not None and self.cluster_cap <= 0:
            raise ValueError("cluster_cap 必须是正整数")
        if self.single_max_size < 0:
            raise ValueError("single_max_size 不能为负")
        if self.rounding not in ROUNDING_MODES:
            raise ValueError(f"rounding 必须是 {ROUNDING_MODES} 之一")
        if not self.id_column or not self.cluster_column or self.id_column == self.cluster_column:
            raise ValueError("id_column 和 cluster_column 必须非空且不同")
        if self.fine_column is not None and self.fine_column in (self.id_column, self.cluster_column, ""):
            raise ValueError("fine_column 必须非空且不同于 id_column、cluster_column")
        if {self.id_column, self.cluster_column, self.fine_column} & set(OUTPUT_COLUMNS):
            raise ValueError(f"{OUTPUT_COLUMNS} 是输出列名，不能作为输入列")


def remap_clusters(clusters: list[str], tail_bins: tuple[int, ...]) -> list[str]:
    """输入每行的簇 id，返回每行的新簇 id。"""
    sizes = Counter(clusters)
    new_id: dict[str, str] = {}
    for cluster_id, size in sizes.items():
        new_id[cluster_id] = cluster_id
        lower = 1
        for upper in tail_bins:
            if size <= upper:
                new_id[cluster_id] = f"tail:{lower}" if lower == upper else f"tail:{lower}-{upper}"
                break
            lower = upper + 1
    return [new_id[c] for c in clusters]


def _span(lower: int, upper: int) -> str:
    return str(lower) if lower == upper else f"{lower}-{upper}"


def segment_names(config: SampleConfig) -> tuple[str | None, str]:
    """由 tail_bins 和 single_max_size 推出 small 段和 normal 段的名字。
    small 段覆盖 (最后一个长尾上界, single_max_size]，为空时返回 None；normal 段是更大的簇。"""
    lower = (config.tail_bins[-1] if config.tail_bins else 0) + 1
    if config.single_max_size >= lower:
        return f"small:{_span(lower, config.single_max_size)}", f"normal:>={config.single_max_size + 1}"
    return None, f"normal:>={lower}"


def split_name(config: SampleConfig) -> str:
    """按细簇拆开的大簇所在的段名。"""
    return segment_names(config)[1].replace("normal:", "split:", 1)


def small_clusters(sizes: dict[str, int], tail_ids: set[str], config: SampleConfig) -> set[str]:
    """未被合并且大小 <= single_max_size 的小簇：固定抽 1 条，不参与按权重分配。"""
    return {c for c, n in sizes.items() if c not in tail_ids and n <= config.single_max_size}


def capacities(sizes: dict[str, int], config: SampleConfig) -> dict[str, int]:
    """每个簇最多能抽几条，受 cluster_cap 限制。"""
    return {c: n if config.cluster_cap is None else min(n, config.cluster_cap) for c, n in sizes.items()}


def allocate(sizes: dict[str, int], capacity: dict[str, int], total: int, alpha: float) -> dict[str, float]:
    """按 n^alpha 分配连续配额；触顶的簇截断在容量，剩余名额在其余簇间重分。"""
    weights = {c: n ** alpha for c, n in sizes.items()}
    quota: dict[str, float] = {}
    remaining = float(min(total, sum(capacity.values())))
    open_clusters = sorted(sizes)
    while open_clusters:
        total_weight = sum(weights[c] for c in open_clusters)
        saturated = {c for c in open_clusters if remaining * weights[c] / total_weight >= capacity[c]}
        if not saturated:
            quota.update({c: remaining * weights[c] / total_weight for c in open_clusters})
            break
        for c in saturated:
            quota[c] = float(capacity[c])
            remaining -= capacity[c]
        open_clusters = [c for c in open_clusters if c not in saturated]
    return quota


def integerize(quota: dict[str, float], capacity: dict[str, int], budget: int,
               rounding: str, rng: random.Random) -> dict[str, int]:
    counts = {c: min(math.floor(q + 1e-9), capacity[c]) for c, q in quota.items()}
    remainder = budget - sum(counts.values())
    if remainder <= 0:
        return counts
    candidates = sorted(c for c in quota if counts[c] < capacity[c])
    fractions = {c: max(quota[c] - counts[c], 0.0) for c in candidates}
    by_fraction = sorted(candidates, key=lambda c: (-fractions[c], c))
    if rounding == "largest_remainder":
        chosen = by_fraction[:remainder]
    else:
        # 系统 PPS：随机起点、步长 1 落点，每个簇被选中的概率等于其小数部分
        fraction_sum = sum(fractions.values())
        scale = remainder / fraction_sum if fraction_sum > 0 else 0.0
        point, cumulative, chosen = rng.random(), 0.0, []
        for c in candidates:
            cumulative += fractions[c] * scale
            if point < cumulative and len(chosen) < remainder:
                chosen.append(c)
                point += 1
        picked = set(chosen)
        chosen += [c for c in by_fraction if c not in picked][:remainder - len(chosen)]  # 浮点误差补齐
    for c in chosen:
        counts[c] += 1
    return counts


def split_clusters(clusters: list[str], new_ids: list[str], fine: list[str],
                   config: SampleConfig) -> tuple[list[str], set[str]]:
    """把未被合并且大小 > single_max_size 的簇换成细簇 id，返回 (新簇 id, 细簇 id 集合)。"""
    sizes = Counter(clusters)
    nest: dict[str, set[str]] = defaultdict(set)
    for c, f in zip(clusters, fine):
        nest[f].add(c)
    crossed = sorted(f for f, cs in nest.items() if len(cs) > 1)
    if crossed:
        raise ValueError(f"细簇跨了多个簇，不是嵌套关系：{crossed[:5]}")
    big = {c for c, new in zip(clusters, new_ids) if c == new and sizes[c] > config.single_max_size}
    out = [f if c in big else new for c, new, f in zip(clusters, new_ids, fine)]
    split = {f for c, f in zip(clusters, fine) if c in big}
    clash = sorted(split & {new for c, new in zip(clusters, new_ids) if c not in big})
    if clash:
        raise ValueError(f"细簇 id 与其他簇 id 重名：{clash[:5]}")
    return out, split


def sample(clusters: list[str], config: SampleConfig,
           fine: list[str] | None = None) -> tuple[dict[int, str], dict[str, Any]]:
    """输入每行的簇 id（和可选的细簇 id），返回 ({被抽中的行号: 新簇 id}, 每个新簇的分配明细)。"""
    rng = random.Random(config.seed)
    new_ids = remap_clusters(clusters, config.tail_bins)
    tail_ids = {new for old, new in zip(clusters, new_ids) if old != new}
    split: set[str] = set()
    if fine is not None:
        new_ids, split = split_clusters(clusters, new_ids, fine, config)
    members: dict[str, list[int]] = defaultdict(list)
    for row, new_id in enumerate(new_ids):
        members[new_id].append(row)
    sizes = {c: len(m) for c, m in members.items()}
    small = small_clusters(sizes, tail_ids | split, config)
    fixed = small | split
    if len(fixed) > config.total:
        raise ValueError(f"需要保底的小簇和细簇有 {len(fixed)} 个，超过 total={config.total}；"
                         "请调大 --total、调小 --single-max-size 或把更多小簇并入 --tail-bins")
    others = {c: n for c, n in sizes.items() if c not in fixed}
    capacity = {**capacities(others, config), **{c: 1 for c in fixed}}
    budget = min(config.total - len(fixed), sum(capacity[c] for c in others))
    quota = {**allocate(others, capacity, budget, config.alpha), **{c: 1.0 for c in fixed}}
    counts = {**integerize({c: quota[c] for c in others}, capacity, budget, config.rounding, rng),
              **{c: 1 for c in fixed}}
    selected = {row: c for c in sorted(members) for row in rng.sample(members[c], counts[c])}
    small_name, normal_name = segment_names(config)
    segment = {c: c if c in tail_ids else split_name(config) if c in split else small_name if c in small
               else normal_name for c in members}
    detail = {c: {"segment": segment[c], "size": sizes[c], "capacity": capacity[c], "quota": round(quota[c], 4),
                  "sampled": counts[c]} for c in sorted(members)}
    return selected, detail


def read_records(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """返回 (原始记录, 列顺序)。CSV 的值保持字符串原样，JSONL 的值保持原 JSON 类型。"""
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        columns = list(dict.fromkeys(k for r in records for k in r))
    elif path.suffix == ".csv":
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            records, columns = list(reader), list(reader.fieldnames or [])
    elif path.suffix == ".xlsx":
        from openpyxl import load_workbook
        rows = load_workbook(path, read_only=True).active.iter_rows(values_only=True)
        columns = [str(c) for c in next(rows, ())]
        records = [dict(zip(columns, row)) for row in rows if any(v is not None for v in row)]
    else:
        raise ValueError("输入只支持 .csv、.jsonl 或 .xlsx")
    return records, columns


def cluster_keys(records: list[dict[str, Any]], config: SampleConfig) -> tuple[list[str], list[str] | None]:
    """返回 (每行的簇 id, 每行的细簇 id 或 None)。"""
    keys, fine = [], []
    required = [c for c in (config.id_column, config.cluster_column, config.fine_column) if c]
    for line, r in enumerate(records, 1):
        missing = [c for c in required if r.get(c) in (None, "")]
        if missing:
            raise ValueError(f"第 {line} 条记录缺少字段: {missing}")
        clash = [c for c in OUTPUT_COLUMNS if c in r]
        if clash:
            raise ValueError(f"输入已包含输出列 {clash}")
        keys.append(str(r[config.cluster_column]))
        if config.fine_column:
            fine.append(str(r[config.fine_column]))
    return keys, fine if config.fine_column else None


def _cell(value: Any) -> Any:
    """CSV / Excel 单元格：嵌套值序列化成 JSON 字符串。"""
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value


def write_records(path: Path, records: list[dict[str, Any]], columns: list[str]) -> None:
    """按 columns 的列顺序写出；格式按扩展名决定。"""
    if path.suffix == ".jsonl":
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    elif path.suffix == ".csv":
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for r in records:
                writer.writerow({k: _cell(v) for k, v in r.items()})
    elif path.suffix == ".xlsx":
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.append(columns)
        for r in records:
            sheet.append([_cell(r.get(c)) for c in columns])
        sheet.freeze_panes = "A2"
        book.save(path)
    else:
        raise ValueError("输出只支持 .csv、.jsonl 或 .xlsx")


def _int_list(text: str) -> list[int]:
    """解析逗号分隔的整数列表，允许逗号两侧有空格；空串返回空列表。"""
    parts = [p.strip() for p in text.split(",")] if text.strip() else []
    try:
        return [int(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"应为逗号分隔的整数，如 1,3,5：{text!r}") from None


def parse_args(argv: list[str] | None) -> tuple[argparse.Namespace, SampleConfig]:
    defaults = SampleConfig()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--id-column", default=defaults.id_column, help="行 id 列名，允许重复")
    parser.add_argument("--cluster-column", default=defaults.cluster_column, help="簇 id 列名")
    parser.add_argument("--total", type=int, default=defaults.total, help="目标抽取条数")
    parser.add_argument("--alpha", type=float, default=defaults.alpha, help="权重指数，越小越照顾小簇，1 为等比例")
    parser.add_argument("--tail-bins", type=_int_list, default=list(defaults.tail_bins),
                        help="长尾分档上界，逗号分隔、严格递增，如 1,3,5；空串 \"\" 表示不合并")
    parser.add_argument("--cluster-cap", type=int, default=defaults.cluster_cap, help="单簇最多抽几条，默认不限")
    parser.add_argument("--single-max-size", type=int, default=defaults.single_max_size,
                        help="未被合并且大小 <= 该值的簇固定抽 1 条（保底且封顶）；0 表示关闭")
    parser.add_argument("--fine-column", help="细簇 id 列名；给了则大于 --single-max-size 的簇按细簇拆开，每个细簇 1 条")
    parser.add_argument("--rounding", choices=ROUNDING_MODES, default=defaults.rounding)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    args = parser.parse_args(argv)
    try:
        config = SampleConfig(total=args.total, alpha=args.alpha, tail_bins=tuple(args.tail_bins),
                              cluster_cap=args.cluster_cap, single_max_size=args.single_max_size,
                              rounding=args.rounding, seed=args.seed,
                              id_column=args.id_column, cluster_column=args.cluster_column,
                              fine_column=args.fine_column)
    except ValueError as exc:
        parser.error(str(exc))
    return args, config


def main(argv: list[str] | None = None) -> int:
    args, config = parse_args(argv)
    records, columns = read_records(args.input)
    try:
        keys, fine = cluster_keys(records, config)
        selected, detail = sample(keys, config, fine)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    original_size = Counter(keys)
    output = [{**r, NEW_CLUSTER_COLUMN: selected[row], SEGMENT_COLUMN: detail[selected[row]]["segment"],
               CLUSTER_SIZE_COLUMN: original_size[keys[row]]}
              for row, r in enumerate(records) if row in selected]
    write_records(args.output, output, [*columns, *OUTPUT_COLUMNS])
    segments: dict[str, dict[str, int]] = {}
    for d in detail.values():
        seg = segments.setdefault(d["segment"], {"clusters": 0, "size": 0, "sampled": 0})
        seg["clusters"] += 1
        seg["size"] += d["size"]
        seg["sampled"] += d["sampled"]
    if args.report:
        args.report.write_text(json.dumps({"config": asdict(config), "segments": segments, "clusters": detail},
                                          ensure_ascii=False, indent=2))

    total_n = sum(d["size"] for d in detail.values())
    tail = [d for c, d in detail.items() if c.startswith("tail:")]
    tail_n, tail_k = sum(d["size"] for d in tail), sum(d["sampled"] for d in tail)
    print(f"原数据 {total_n} 条，目标抽取 {config.total} 条，可抽上限 {sum(d['capacity'] for d in detail.values())} 条，"
          f"实际抽取 {len(output)} 条")
    if len(output) < config.total:
        print("注意：目标超过可抽上限，已把能抽的全部抽出（受簇大小、--cluster-cap、--single-max-size 限制）")
    print(f"新簇 {len(detail)} 个，被抽到 {sum(1 for d in detail.values() if d['sampled'])} 个")
    print(f"长尾簇：数据占比 {tail_n / total_n:.1%}，样本占比 {tail_k / max(len(output), 1):.1%}")
    for name, seg in segments.items():
        print(f"  {name}：簇 {seg['clusters']} 个，原 {seg['size']} 条，抽 {seg['sampled']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
