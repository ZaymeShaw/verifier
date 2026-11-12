"""加载本目录 .env，依次运行上一级的聚类、采样脚本。"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

MODULE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = MODULE_DIR.parent


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (MODULE_DIR / path).resolve() if not path.is_absolute() else path.resolve()


def optional_int(value: str) -> int | None:
    return int(value) if value.strip() else None


def optional_float(value: str) -> float | None:
    return float(value) if value.strip() else None


def main(argv: list[str] | None = None) -> int:
    # 不搜索父目录 .env；不修改当前进程环境；禁用隐式变量插值。
    env = {**{k: v for k, v in dotenv_values(MODULE_DIR / ".env", encoding="utf-8-sig", interpolate=False).items()
              if v is not None}, **os.environ}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=env.get("INPUT_PATH", "./example-input.jsonl"))
    parser.add_argument("--output-dir", default=env.get("OUTPUT_DIR", "./output"))
    parser.add_argument("--id-column", default=env.get("INPUT_ID_COLUMN", "id"))
    parser.add_argument("--text-column", default=env.get("INPUT_TEXT_COLUMN", "text"))
    parser.add_argument("--base-url", default=env.get("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    parser.add_argument("--model", default=env.get("EMBEDDING_MODEL", "qwen3.7-text-embedding"))
    parser.add_argument("--api-key-env", default=env.get("EMBEDDING_API_KEY_ENV", "EMBEDDING_API_KEY"))
    parser.add_argument("--dimension", type=optional_int, default=env.get("EMBEDDING_DIMENSION", "1024"))
    parser.add_argument("--batch-size", type=int, default=env.get("EMBEDDING_BATCH_SIZE", "20"))
    parser.add_argument("--timeout", type=float, default=env.get("EMBEDDING_TIMEOUT", "60"))
    parser.add_argument("--extra-body", default=env.get("EMBEDDING_EXTRA_BODY", "{}"))
    parser.add_argument("--threshold", type=float, default=env.get("CLUSTER_THRESHOLD", "0.7"))
    parser.add_argument("--fine-threshold", type=optional_float, default=env.get("CLUSTER_FINE_THRESHOLD", "0.85"))
    parser.add_argument("--linkage", choices=("complete", "average", "single"), default=env.get("CLUSTER_LINKAGE", "complete"))
    parser.add_argument("--total", type=int, default=env.get("SAMPLE_TOTAL", "1087"))
    parser.add_argument("--alpha", type=float, default=env.get("SAMPLE_ALPHA", "0.6"))
    parser.add_argument("--tail-bins", default=env.get("SAMPLE_TAIL_BINS", "1,3"))
    parser.add_argument("--tail-max-ratio", type=optional_float, default=env.get("SAMPLE_TAIL_MAX_RATIO", ""))
    parser.add_argument("--single-max-size", type=int, default=env.get("SAMPLE_SINGLE_MAX_SIZE", "20"))
    parser.add_argument("--cluster-cap", type=optional_int, default=env.get("SAMPLE_CLUSTER_CAP", ""))
    parser.add_argument("--rounding", choices=("pps", "largest_remainder"), default=env.get("SAMPLE_ROUNDING", "pps"))
    parser.add_argument("--seed", type=int, default=env.get("SAMPLE_SEED", "42"))
    args = parser.parse_args(argv)
    if args.tail_max_ratio is not None and not 0 <= args.tail_max_ratio <= 1:
        parser.error("SAMPLE_TAIL_MAX_RATIO/--tail-max-ratio 必须是 0 到 1 之间的有限数")
    for name, value in (("INPUT_PATH/--input", args.input), ("OUTPUT_DIR/--output-dir", args.output_dir),
                        ("EMBEDDING_BASE_URL/--base-url", args.base_url), ("EMBEDDING_MODEL/--model", args.model)):
        if not value or not value.strip():
            parser.error(f"缺少 {name}")
    if not env.get(args.api_key_env):
        parser.error(f"缺少密钥环境变量 {args.api_key_env}")
    input_path = resolve_path(args.input)
    if not input_path.is_file():
        parser.error(f"输入文件不存在：{input_path}")

    # 只复用原脚本公开入口，不在这里复制聚类、采样或数据读写逻辑。
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clustered = output_dir / "clustered.jsonl"
    clustered_excel = output_dir / "clustered.xlsx"
    sampled = output_dir / "sampled.xlsx"
    cluster_report = output_dir / "cluster-report.json"
    sample_report = output_dir / "sample-report.json"
    outputs = (clustered, clustered_excel, sampled, cluster_report, sample_report)
    if input_path in {path.resolve() for path in outputs}:
        parser.error("输入文件不能使用本工作流的输出文件路径，请先复制到其他位置")
    # 每次只保留本次结果；缓存和目录中的其他文件不动。
    for path in outputs:
        path.unlink(missing_ok=True)
    cluster_command = [sys.executable, str(SCRIPTS_DIR / "embed_cluster.py"),
                       "--input", str(input_path), "--output", str(clustered),
                       "--excel-output", str(clustered_excel),
                       "--report", str(cluster_report),
                       "--cache", str(output_dir / ".cache" / "embeddings.jsonl"),
                       "--id-column", args.id_column, "--text-column", args.text_column,
                       "--base-url", args.base_url, "--model", args.model, "--api-key-env", args.api_key_env,
                       "--batch-size", str(args.batch_size), "--timeout", str(args.timeout),
                       "--extra-body", args.extra_body, "--threshold", str(args.threshold),
                       "--linkage", args.linkage]
    if args.dimension is not None:
        cluster_command += ["--dimension", str(args.dimension)]
    if args.fine_threshold is not None:
        cluster_command += ["--fine-threshold", str(args.fine_threshold)]
    sample_command = [sys.executable, str(SCRIPTS_DIR / "cluster_sample.py"),
                      "--input", str(clustered), "--output", str(sampled),
                      "--report", str(sample_report), "--id-column", args.id_column,
                      "--total", str(args.total), "--alpha", str(args.alpha), "--tail-bins", args.tail_bins,
                      "--single-max-size", str(args.single_max_size), "--rounding", args.rounding,
                      "--seed", str(args.seed)]
    if args.cluster_cap is not None:
        sample_command += ["--cluster-cap", str(args.cluster_cap)]
    if args.tail_max_ratio is not None:
        sample_command += ["--tail-max-ratio", str(args.tail_max_ratio)]
    if args.fine_threshold is not None:
        sample_command += ["--fine-column", "fine_cluster_id"]
    print(f"覆盖输出：{output_dir}", flush=True)
    for stage, command in (("聚类", cluster_command), ("采样", sample_command)):
        print(f"开始{stage}", flush=True)
        result = subprocess.run(command, env=env, check=False)
        if result.returncode:
            if stage == "聚类":
                clustered_excel.unlink(missing_ok=True)
            sampled.unlink(missing_ok=True)
            sample_report.unlink(missing_ok=True)
            print(f"{stage}失败，未保留最终样本；中间产物位于：{output_dir}", file=sys.stderr)
            return result.returncode if result.returncode > 0 else 1
        if stage == "聚类":
            print(f"聚类结果：{clustered_excel}", flush=True)
    print(f"完成，最终样本：{sampled}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
