"""用 embedding 对文本做高阈值语义聚类，给每行加一列簇 id，产出可直接喂给 cluster_sample.py 的批次数据。

做法：
1. 取 --text-column 的文本（值是列表时按换行拼接，适合多轮 turns）；完全相同的文本只请求一次 embedding。
2. 通过 OpenAI SDK 调用配置的 /embeddings 接口。--base-url / --model 分别设置服务根地址和模型，
   也可用 EMBEDDING_BASE_URL / EMBEDDING_MODEL；命令行优先。密钥取 --api-key-env 指定的环境变量
   （默认 EMBEDDING_API_KEY），不读取 verifier 的 impl/config.yaml 或 .env。
   --dimension 可选；服务专用参数用 --extra-body JSON 对象传入（如 instruct），按服务实际协议填写。
   向量按 --cache 缓存，键包含服务地址、模型、维度、额外参数和文本；改阈值重跑不重复请求。
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

注意：文本会发到配置的 embedding 服务。该服务必须支持 embeddings，不只是聊天接口。

用法：
    python scripts/embed_cluster.py --input questions.jsonl --output clustered.jsonl \
        --base-url https://embedding.example.com/v1 --model your-embedding-model \
        [--id-column id] [--text-column turns] [--cluster-column cluster_id] \
        [--api-key-env EMBEDDING_API_KEY] [--dimension 1024] [--batch-size 20] [--timeout 60] \
        [--threshold 0.7] [--fine-threshold 0.85] [--fine-column fine_cluster_id] [--linkage complete] \
        [--cache tmp/embed_cache.jsonl] [--report report.json]
    python scripts/cluster_sample.py --input clustered.jsonl --output sampled.jsonl --total 60 ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

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
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    item = json.loads(line)
                    self.vectors[item["key"]] = item["vector"]

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_id}\n{text}".encode()).hexdigest()

    def add(self, items: dict[str, list[float]]) -> None:
        self.vectors.update(items)
        if self.path and items:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
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


def openai_embed(args: argparse.Namespace) -> tuple[Embed, str]:
    import httpx
    from openai import OpenAI

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"错误：未设置环境变量 {args.api_key_env}")
    base_url = args.base_url.rstrip("/")
    params: dict[str, Any] = {}
    if args.dimension is not None:
        params["dimensions"] = args.dimension

    def embed(texts: Sequence[str]) -> list[list[float]]:
        # 沿用原脚本不继承桌面代理的行为；失败直接交给调用方，不切换服务或模型。
        with OpenAI(base_url=base_url, api_key=api_key, timeout=args.timeout, max_retries=0,
                    http_client=httpx.Client(trust_env=False)) as client:
            resp = client.embeddings.create(model=args.model, input=list(texts), encoding_format="float",
                                            extra_body=args.extra_body, **params)
        items = sorted(resp.data, key=lambda x: x.index)
        if [item.index for item in items] != list(range(len(texts))):
            raise ValueError("embedding 返回的 index 必须与输入逐条对应，不能缺失或重复")
        vectors = np.asarray([item.embedding for item in items], dtype=float)
        if (vectors.ndim != 2 or vectors.shape[1] == 0 or not np.isfinite(vectors).all()
                or (np.linalg.norm(vectors, axis=1) == 0).any()):
            raise ValueError("embedding 必须返回等长、有限且非零的向量")
        if args.dimension is not None and vectors.shape[1] != args.dimension:
            raise ValueError(f"embedding 返回维度 {vectors.shape[1]}，请求维度 {args.dimension}")
        return vectors.tolist()

    identity = {"protocol": "openai-embeddings", "base_url": base_url, "model": args.model,
                "dimensions": args.dimension, "extra_body": args.extra_body}
    return embed, json.dumps(identity, sort_keys=True, ensure_ascii=False)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--excel-output", type=Path, help="额外输出完整聚类结果的 XLSX，与主输出使用同一批记录")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--id-column", default="id")
    parser.add_argument("--text-column", default="text", help="聚类用的文本列；值是列表时按换行拼接")
    parser.add_argument("--cluster-column", default="cluster_id", help="输出的簇 id 列名")
    parser.add_argument("--threshold", type=float, default=0.9, help="余弦相似度阈值，越高簇越细")
    parser.add_argument("--fine-threshold", type=float, help="细簇阈值，须 >= --threshold；不给则不输出细簇列")
    parser.add_argument("--fine-column", default="fine_cluster_id", help="输出的细簇 id 列名")
    parser.add_argument("--linkage", choices=LINKAGES, default="complete")
    parser.add_argument("--cache", type=Path, help="向量缓存 JSONL，不给则不缓存")
    parser.add_argument("--base-url", default=os.environ.get("EMBEDDING_BASE_URL"),
                        required=not os.environ.get("EMBEDDING_BASE_URL"), help="API 根地址，不含 /embeddings")
    parser.add_argument("--model", default=os.environ.get("EMBEDDING_MODEL"),
                        required=not os.environ.get("EMBEDDING_MODEL"), help="embedding 模型 ID")
    parser.add_argument("--api-key-env", default="EMBEDDING_API_KEY", help="保存 API 密钥的环境变量名")
    parser.add_argument("--dimension", type=int, help="可选向量维度；不设置时不发送 dimensions 参数")
    parser.add_argument("--extra-body", type=json.loads, default={}, help="服务专用请求参数，JSON 对象")
    parser.add_argument("--timeout", type=float, default=60, help="单次 HTTP 请求超时秒数")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="每次请求的文本数，按服务的批量上限设置")
    args = parser.parse_args(argv)
    if args.excel_output is not None:
        if args.excel_output.suffix != ".xlsx":
            parser.error("excel-output 必须是 .xlsx 文件")
        if args.excel_output.resolve() in {args.input.resolve(), args.output.resolve()}:
            parser.error("excel-output 不能与 input 或 output 使用同一路径")
    url = urlsplit(args.base_url)
    if url.scheme not in {"http", "https"} or not url.hostname or url.query or url.fragment or url.username or url.password:
        parser.error("base-url 必须是无凭据、查询参数或片段的 HTTP(S) API 根地址")
    if not args.model.strip() or not args.api_key_env.strip():
        parser.error("model 和 api-key-env 不能为空")
    if args.dimension is not None and args.dimension <= 0:
        parser.error("dimension 必须是正整数")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout 必须是有限正数")
    if not isinstance(args.extra_body, dict):
        parser.error("extra-body 必须是 JSON 对象")
    if {"model", "input", "encoding_format", "dimensions"} & args.extra_body.keys():
        parser.error("extra-body 不能覆盖 model、input、encoding_format 或 dimensions")
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
         embed_factory: Callable[[argparse.Namespace], tuple[Embed, str]] = openai_embed) -> int:
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
    output_columns = list(dict.fromkeys([*head, *columns]))
    write_records(args.output, output, output_columns)
    if args.excel_output is not None:
        write_records(args.excel_output, output, output_columns)

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
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    dist = sorted(Counter(sizes.values()).items())
    print(f"共 {len(records)} 条，不同文本 {len(set(texts))} 条，新请求 embedding {requested} 条")
    print(f"簇 {len(sizes)} 个，单例 {sum(1 for n in sizes.values() if n == 1)} 个，最大簇 {max(sizes.values())} 条")
    print("簇大小分布（大小: 簇数）：" + "、".join(f"{s}: {k}" for s, k in dist))
    if fine_ids:
        print(f"细簇（阈值 {args.fine_threshold}）{len(set(fine_ids))} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
