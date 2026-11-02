"""用 embedding 对文本做高阈值语义聚类，给每行加一列簇 id，产出可直接喂给 cluster_sample.py 的批次数据。

做法：
1. 取 --text-column 的文本（值是列表时按换行拼接，适合多轮 turns）；完全相同的文本只请求一次 embedding。
2. 调百炼 DashScope 原生 embedding 接口，默认 qwen3.7-text-embedding（百炼当前推荐的文本向量模型），
   可用 --model / --dimension / --instruct 调整；API key 取 impl/config.yaml 的 embedding.api_key（.env 的 BAILIAN_API_KEY）。
   --instruct 非空时按官方要求以 text_type=query 发送，所有文本用同一条指令，聚类仍是对称的。
   向量按 --cache 缓存，键为 (模型, 维度, 指令, 文本) 的哈希；改阈值重跑不重复请求。
3. 层次聚类，余弦相似度阈值 --threshold。默认 complete linkage：簇内任意两条的相似度都 >= 阈值，
   不会像 single linkage 那样被模板句串成大簇。
4. 簇 id 按簇大小降序编号 c0、c1……，大小相同按首次出现顺序。
5. 可选 --fine-threshold：在同一棵树上再按更高阈值切一刀，多输出一列细簇 id（--fine-column，
   默认 fine_cluster_id），编号为 <粗簇 id>.<序号>，如 c1.0、c1.1。同一棵树切两刀，细簇必然嵌套在粗簇内；
   linkage 只看两组成员间的距离，所以结果等于在每个粗簇内单独按细阈值再聚一次。
   哪些簇要按细簇拆由 cluster_sample.py 的 --single-max-size 决定，这里不看簇大小。

输入：CSV（有表头）、JSONL 或 XLSX，按扩展名识别。
输出：全部原始行，保持输入顺序；列顺序为 id 列、簇 id 列，其后是其余原始列（与 cluster_sample.py 的
(id, 簇 id) 输入格式一致）。格式按扩展名：.jsonl / .csv / .xlsx。
--report 输出每个簇的大小和成员文本，用来人工看阈值合不合适。

注意：文本会发到百炼（外部服务）。

用法：
    python scripts/embed_cluster.py --input questions.jsonl --output clustered.jsonl \
        [--id-column id] [--text-column turns] [--cluster-column cluster_id] \
        [--model qwen3.7-text-embedding] [--dimension 1024] [--instruct "..."] [--batch-size 20] \
        [--threshold 0.9] [--fine-threshold 0.85] [--fine-column fine_cluster_id] [--linkage complete] \
        [--cache tmp/embed_cache.jsonl] [--report report.json]
    python scripts/cluster_sample.py --input clustered.jsonl --output sampled.jsonl --total 60 ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cluster_sample import read_records, write_records  # noqa: E402

LINKAGES = ("complete", "average", "single")
Embed = Callable[[Sequence[str]], Sequence[Sequence[float]]]


def record_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return "" if value is None else str(value)


def cluster_vectors(vectors: np.ndarray, thresholds: Sequence[float], method: str) -> list[list[int]]:
    """建一棵树，按每个阈值各切一刀，返回每个阈值下每个向量的簇标签（从 1 开始）。余弦距离 = 1 - 相似度。"""
    if len(vectors) == 1:
        return [[1] for _ in thresholds]
    tree = linkage(vectors, method=method, metric="cosine")
    return [[int(x) for x in fcluster(tree, t=1.0 - t, criterion="distance")] for t in thresholds]


def _name_by_size(labels: list[Any], prefix: str = "c") -> list[str]:
    """按组大小降序编号 prefix0、prefix1……，大小相同按首次出现顺序。"""
    sizes = Counter(labels)
    first = {lab: i for i, lab in reversed(list(enumerate(labels)))}
    order = sorted(sizes, key=lambda lab: (-sizes[lab], first[lab]))
    name = {lab: f"{prefix}{i}" for i, lab in enumerate(order)}
    return [name[lab] for lab in labels]


class VectorCache:
    """JSONL 缓存：每行 {"key", "vector"}。只追加，不改已有行。"""

    def __init__(self, path: Path | None, model_id: str) -> None:
        self.path, self.model_id = path, model_id
        self.vectors: dict[str, list[float]] = {}
        if path and path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    item = json.loads(line)
                    self.vectors[item["key"]] = item["vector"]

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_id}\n{text}".encode()).hexdigest()

    def add(self, items: dict[str, list[float]]) -> None:
        self.vectors.update(items)
        if self.path and items:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                for k, v in items.items():
                    f.write(json.dumps({"key": k, "vector": v}) + "\n")


def embed_texts(texts: list[str], embed: Embed, cache: VectorCache, batch_size: int) -> tuple[np.ndarray, int]:
    """返回 (单位化后的向量矩阵, 本次新请求的条数)。"""
    missing = [t for t in dict.fromkeys(texts) if cache.key(t) not in cache.vectors]
    for start in range(0, len(missing), batch_size):
        chunk = missing[start:start + batch_size]
        vectors = embed(chunk)
        if len(vectors) != len(chunk):
            raise ValueError(f"embedding 返回 {len(vectors)} 条，请求 {len(chunk)} 条")
        cache.add({cache.key(t): [float(x) for x in v] for t, v in zip(chunk, vectors)})
        print(f"embedding {min(start + batch_size, len(missing))}/{len(missing)}", file=sys.stderr)
    matrix = np.array([cache.vectors[cache.key(t)] for t in texts], dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("存在全零向量")
    return matrix / norms, len(missing)


def assign_clusters(texts: list[str], embed: Embed, cache: VectorCache, *, threshold: float,
                    method: str, batch_size: int,
                    fine_threshold: float | None = None) -> tuple[list[str], list[str] | None, int]:
    """返回 (每行的簇 id, 每行的细簇 id 或 None, 新请求条数)。相同文本必然同簇。"""
    unique = list(dict.fromkeys(texts))
    vectors, requested = embed_texts(unique, embed, cache, batch_size)
    cuts = cluster_vectors(vectors, [threshold] if fine_threshold is None else [threshold, fine_threshold], method)
    position = {t: i for i, t in enumerate(unique)}
    rows = [[labels[position[t]] for t in texts] for labels in cuts]
    coarse = _name_by_size(rows[0])
    if fine_threshold is None:
        return coarse, None, requested
    fine = [""] * len(texts)
    members: dict[str, list[int]] = {}
    for i, c in enumerate(coarse):
        members.setdefault(c, []).append(i)
    for c, idx in members.items():
        for i, name in zip(idx, _name_by_size([rows[1][i] for i in idx], prefix=f"{c}.")):
            fine[i] = name
    return coarse, fine, requested


DASHSCOPE_URL = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"


def bailian_embed(args: argparse.Namespace) -> tuple[Embed, str]:
    import requests
    from impl.core.config import get_embedding_config

    api_key = get_embedding_config().api_key
    if not api_key:
        raise SystemExit("错误：未配置 embedding.api_key（.env 的 BAILIAN_API_KEY）")
    params: dict[str, Any] = {"dimension": args.dimension}
    if args.instruct:
        params.update(text_type="query", instruct=args.instruct)
    session = requests.Session()
    session.trust_env = False  # 与 BailianEmbedder 一致，不走桌面代理

    def embed(texts: Sequence[str]) -> list[list[float]]:
        resp = session.post(DASHSCOPE_URL, timeout=60,
                            headers={"Authorization": f"Bearer {api_key}"},
                            json={"model": args.model, "input": {"texts": list(texts)}, "parameters": params})
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code != 200:
            raise RuntimeError(f"embedding 请求失败 {resp.status_code}: {body.get('code')} {body.get('message')}")
        items = sorted(body["output"]["embeddings"], key=lambda x: x["text_index"])
        return [item["embedding"] for item in items]

    instruct_hash = hashlib.sha256(args.instruct.encode()).hexdigest()[:12] if args.instruct else "none"
    return embed, f"{args.model}|dim={args.dimension}|instruct={instruct_hash}"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--id-column", default="id")
    parser.add_argument("--text-column", default="text", help="聚类用的文本列；值是列表时按换行拼接")
    parser.add_argument("--cluster-column", default="cluster_id", help="输出的簇 id 列名")
    parser.add_argument("--threshold", type=float, default=0.9, help="余弦相似度阈值，越高簇越细")
    parser.add_argument("--fine-threshold", type=float, help="细簇阈值，须 >= --threshold；不给则不输出细簇列")
    parser.add_argument("--fine-column", default="fine_cluster_id", help="输出的细簇 id 列名")
    parser.add_argument("--linkage", choices=LINKAGES, default="complete")
    parser.add_argument("--cache", type=Path, help="向量缓存 JSONL，不给则不缓存")
    parser.add_argument("--model", default="qwen3.7-text-embedding")
    parser.add_argument("--dimension", type=int, default=1024, help="向量维度，取值见百炼文档")
    parser.add_argument("--instruct", default="", help="英文任务指令，空表示不加")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="每次请求的文本数（qwen3.7-text-embedding 上限 20，text-embedding-v4 上限 10）")
    args = parser.parse_args(argv)
    if not 0 < args.threshold <= 1:
        parser.error("threshold 必须在 (0, 1] 内")
    if args.fine_threshold is not None and not args.threshold <= args.fine_threshold <= 1:
        parser.error("fine-threshold 必须在 [threshold, 1] 内")
    if args.batch_size <= 0:
        parser.error("batch-size 必须是正整数")
    if len({args.id_column, args.text_column, args.cluster_column, args.fine_column}) < 4:
        parser.error("id-column、text-column、cluster-column、fine-column 必须互不相同")
    return args


def main(argv: list[str] | None = None,
         embed_factory: Callable[[argparse.Namespace], tuple[Embed, str]] = bailian_embed) -> int:
    args = parse_args(argv)
    records, columns = read_records(args.input)
    texts = []
    for line, r in enumerate(records, 1):
        missing = [c for c in (args.id_column, args.text_column) if r.get(c) in (None, "", [])]
        if missing:
            print(f"错误：第 {line} 条记录缺少字段: {missing}", file=sys.stderr)
            return 2
        clash = [c for c in (args.cluster_column, args.fine_column if args.fine_threshold is not None else None)
                 if c and c in r]
        if clash:
            print(f"错误：输入已包含输出列 {clash}", file=sys.stderr)
            return 2
        texts.append(record_text(r[args.text_column]))

    embed, model_id = embed_factory(args)
    cache = VectorCache(args.cache, model_id)
    cluster_ids, fine_ids, requested = assign_clusters(texts, embed, cache, threshold=args.threshold,
                                                       method=args.linkage, batch_size=args.batch_size,
                                                       fine_threshold=args.fine_threshold)
    head = [args.id_column, args.cluster_column] + ([args.fine_column] if fine_ids else [])
    output = [{args.id_column: r[args.id_column], args.cluster_column: c,
               **({args.fine_column: fine_ids[i]} if fine_ids else {}), **r}
              for i, (r, c) in enumerate(zip(records, cluster_ids))]
    write_records(args.output, output, list(dict.fromkeys([*head, *columns])))

    sizes = Counter(cluster_ids)
    if args.report:
        members: dict[str, list[dict[str, Any]]] = {}
        for i, (r, t, c) in enumerate(zip(records, texts, cluster_ids)):
            members.setdefault(c, []).append({"id": r[args.id_column], "text": t,
                                              **({"fine_cluster_id": fine_ids[i]} if fine_ids else {})})
        args.report.write_text(json.dumps({
            "config": {"model": model_id, "threshold": args.threshold, "fine_threshold": args.fine_threshold,
                       "linkage": args.linkage},
            "clusters": [{"cluster_id": c, "size": n, "members": members[c]} for c, n in sizes.most_common()],
        }, ensure_ascii=False, indent=2))

    dist = sorted(Counter(sizes.values()).items())
    print(f"共 {len(records)} 条，不同文本 {len(set(texts))} 条，新请求 embedding {requested} 条")
    print(f"簇 {len(sizes)} 个，单例 {sum(1 for n in sizes.values() if n == 1)} 个，最大簇 {max(sizes.values())} 条")
    print("簇大小分布（大小: 簇数）：" + "、".join(f"{s}: {k}" for s, k in dist))
    if fine_ids:
        print(f"细簇（阈值 {args.fine_threshold}）{len(set(fine_ids))} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
