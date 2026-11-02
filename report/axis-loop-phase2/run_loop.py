"""第二期验收（spec/implementation/axis_loop.md §9 S8）：22 条带 trace 存档的 verify 样本，用 axis loop 路线重判。

样本：report/eval-main-axis/verify33/old.jsonl 里 verify-insurance-agno / langfuse 的 22 条（10-19 8031 存档），不重新调业务。
轮一 `--round t`：场景只配 trace（verify-insurance-<agno|langfuse>）；轮二 `--round tk`：知识 + trace（场景名加 -tk）。
完整报告存 runs/<variant>/<样本>.json，便于逐条追。
用法（数据取实例 inst-f105511930554648）：python run_loop.py <variant> --round t|tk [--ids …] [--workers N]
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
CODE = HERE.parents[1]
sys.path.insert(0, str(CODE))
os.environ.setdefault("VERIFIER_INSTANCE_ID", "inst-f105511930554648")

from impl.core.project_loader import load_project  # noqa: E402
from impl.projects.llm_probe_loop.eval_axes import build_report  # noqa: E402
from impl.server.service import normalize_run_trace  # noqa: E402

SAMPLES = CODE / "report/eval-main-axis/verify33/old.jsonl"
PROCESS = ("intent_understanding", "planning_routing", "tool_execution", "context_memory", "knowledge_data", "model_capability")
SPEC = load_project("llm_probe_loop")
LOCK = threading.Lock()


def samples(ids):
    for line in SAMPLES.read_text().splitlines():
        row = json.loads(line)
        if "mcp" in row["scenario"] or (ids and not any(i in row["id"] for i in ids)):
            continue
        yield row


def run_one(row, round_, variant):
    scenario = row["scenario"] + ("-tk" if round_ == "tk" else "")
    trace = normalize_run_trace(row["trace"])
    started = time.monotonic()
    report = build_report(SPEC, trace, run_id=f"phase2-{round_}-{row['id'][17:]}", scenario_id=scenario)
    full = HERE / "runs" / variant
    full.mkdir(exist_ok=True)
    (full / f"{row['id'][17:]}.json").write_text(json.dumps(report, ensure_ascii=False, default=str))
    results = {r["type_id"]: r for r in report["results"]}
    loop = report.get("loop") or {}
    out = lambda k: (results.get(k) or {}).get("output") or {}
    return {
        "id": row["id"], "scenario": scenario, "round": round_, "seconds": round(time.monotonic() - started, 1),
        "status": loop.get("status"), "reason": str(loop.get("reason") or "")[:500],
        "main_verdict": report.get("main_verdict"),
        "six": {a: out(a).get("verdict") for a in PROCESS},
        "six_counts": {a: (out(a).get("composition") or {}).get("counts") for a in PROCESS},
        "six_issues": {a: [i.get("phenomenon") for i in out(a).get("issues") or []] for a in PROCESS},
        "assessments": out("fulfillment").get("fulfillment_assessments"),
        "expectations": [{k: e.get(k) for k in ("expectation_id", "statement", "needs")} for e in out("expectations").get("expectations") or []],
        "suspects": len(out("trace_analysis").get("suspects") or []),
        "llm_calls": loop.get("llm_calls"), "tool_calls": loop.get("tool_calls"), "loops": report.get("loops"),
        "usage": loop.get("usage"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("variant")
    ap.add_argument("--round", choices=("t", "tk"), required=True)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    path = HERE / "runs" / f"{args.variant}.jsonl"
    path.parent.mkdir(exist_ok=True)
    done = {json.loads(x)["id"] for x in path.read_text().splitlines()} if path.exists() else set()
    todo = [r for r in samples(args.ids) if r["id"] not in done]
    print(f"{len(todo)} to run ({len(done)} done)", flush=True)

    def task(row):
        try:
            rec = run_one(row, args.round, args.variant)
        except Exception as exc:  # 评测器崩溃：记下来、下次续跑
            print(row["id"], "CRASH", repr(exc)[:400], flush=True)
            return
        with LOCK, path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        print(row["id"], rec["status"], (rec["main_verdict"] or {}).get("verdict"), rec["six"], rec["llm_calls"], rec["seconds"], flush=True)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(task, todo))
    print(f"wall_clock_s {round(time.monotonic() - started, 1)}", flush=True)


if __name__ == "__main__":
    main()
