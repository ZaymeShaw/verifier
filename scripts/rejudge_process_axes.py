"""冻结重判：用一次前端批次保存下来的案卷，重跑分析轴 + 过程六轴（不调业务、不跑主判）。

输入是批次状态文件（summary 页批次接口的原样导出）：每例取 `run.trace` 与旧实现在
`run.eval_axes.results[trace_analysis].output.dossier` 里保存的案卷。案卷原样注入，
所以新旧结果的差异只来自判定实现（分析轴与六轴）。输出每例一个 JSON，可续跑。

用法：
    python scripts/rejudge_process_axes.py --batch report/process-axes-live-20260928/batch-status.json \
        --out report/process-axes-rejudge-20260929/run1 [--only B01,D05] [--workers 4] [--force]
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from unittest import mock

from impl.core.project_loader import load_project
from impl.core.schema import normalize_run_trace
from impl.projects.llm_probe.business_trace.providers.agno_reader import STREAMED_EXECUTOR_STATUS_NOTE
from impl.projects.llm_probe.eval_axes import build_report
from impl.projects.llm_probe.eval_axes.adapters import trace_analysis

FROZEN_KEY = "frozen_dossier"


def load_cases(batch: Path) -> list[dict[str, Any]]:
    data = json.loads(batch.read_text())
    data = data.get("data", data)
    cases = []
    for event in data["events"]:
        run = event.get("run") or {}
        results = ((run.get("eval_axes") or {}).get("results")) or []
        analysis = next((r for r in results if r.get("type_id") == "trace_analysis"), {})
        dossier = (analysis.get("output") or {}).get("dossier")
        cases.append({"case_id": event.get("case_id") or run.get("case_id"), "trace": run.get("trace"),
                      "dossier": dossier, "old": results})
    return cases


def _frozen_build_dossier(trace: Any, snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or FROZEN_KEY not in snapshot:
        raise ValueError("冻结重判只接受注入的案卷")
    dossier = json.loads(json.dumps(snapshot[FROZEN_KEY]))   # 每次深拷贝，轴之间互不污染
    # 旧版案卷在没有模型调用时不写 model_calls（现行 build_dossier 总会写空表）。
    dossier.setdefault("model_calls", [])
    # 旧版案卷采集于执行器 status 附注之前；按现行 reader 的同一规则补上（有 workflow_step_id 的运行）。
    for row in dossier.get("records") or []:
        status = (row.get("fields") or {}).get("status")
        if row.get("kind") == "runs" and row.get("workflow_step_id") and status and status.get("status") != "missing":
            status["note"] = STREAMED_EXECUTOR_STATUS_NOTE
    return dossier


def rejudge(case: dict[str, Any], out: Path, force: bool) -> dict[str, Any]:
    target = out / f"{case['case_id']}.json"
    if target.exists() and not force:
        return {"case_id": case["case_id"], "status": "skipped"}
    started = time.monotonic()
    try:
        if not isinstance(case["trace"], dict) or not isinstance(case["dossier"], dict):
            raise ValueError("批次里没有该例的 trace 或冻结案卷")
        trace = normalize_run_trace(case["trace"])
        trace.project_fields = {**(trace.project_fields or {}), "business_trace": {FROZEN_KEY: case["dossier"]}}
        report = build_report(load_project("llm_probe"), trace)
        for item in report["results"]:
            if item.get("type_id") == "trace_analysis" and isinstance(item.get("output"), dict):
                item["output"].pop("dossier", None)   # 与输入相同，不重复存
        payload = {"case_id": case["case_id"], "seconds": round(time.monotonic() - started, 1), "axes": report}
    except Exception as exc:  # 单例失败不停批次
        payload = {"case_id": case["case_id"], "seconds": round(time.monotonic() - started, 1),
                   "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    verdicts = {r["type_id"]: r.get("verdict") or r.get("status") for r in (payload.get("axes") or {}).get("results", [])}
    return {"case_id": case["case_id"], "seconds": payload["seconds"], "axes": verdicts, "error": payload.get("error")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--only", default="", help="逗号分隔的用例编号子串")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    cases = load_cases(args.batch)
    needles = [n.strip() for n in args.only.split(",") if n.strip()]
    if needles:
        cases = [c for c in cases if any(n in str(c["case_id"]) for n in needles)]
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"{len(cases)} cases, workers={args.workers}", flush=True)
    # 只替换分析轴取案卷的入口；其余判定代码与生产一致。
    with mock.patch.object(trace_analysis, "build_dossier", _frozen_build_dossier), \
            ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(rejudge, case, args.out, args.force) for case in cases]
        for future in as_completed(futures):
            print(json.dumps(future.result(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
