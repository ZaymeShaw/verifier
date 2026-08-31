"""llm_probe 判定基线采集：live → judge（轴1）→ carrier（轴2），逐 case 落记录。

用法（repo 根目录）：
    python report/regression/llm_probe/run_baseline.py --out report/regression/llm_probe/baseline-YYYYMMDD.json
    可选 --only id1,id2 只跑部分 case；--cases 换用别的 case 文件。

产出记录字段：case_id / input / capability_ref / output_text / judge / capability_carrier / elapsed_s。
后续阶段改动后重跑同一脚本，diff 判定结果即为验收。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from impl.core import pipeline  # noqa: E402
from impl.core.capability_carrier import live_carrier_report  # noqa: E402
from impl.core.project_loader import load_project  # noqa: E402
from impl.core.schema import SingleTurnCase, to_dict  # noqa: E402


def run_case(spec, case: dict) -> dict:
    case_id = str(case.get("id") or "")
    live_request = dict(case.get("live_request") or {})
    record: dict = {
        "case_id": case_id,
        "capability_ref": live_request.get("capability_ref") or "",
        "input": (live_request.get("body") or {}),
    }
    started = time.time()
    try:
        trace = pipeline.live_run("llm_probe", SingleTurnCase(id=case_id, input=live_request))
        judge_result = pipeline.judge("llm_probe", trace)
        carrier = live_carrier_report(
            spec, judge_result, request=pipeline._request_from_trace(trace)
        )
        output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
        record.update(
            {
                "output_text": str(output.get("output_text") or ""),
                "judge": to_dict(judge_result),
                "capability_carrier": carrier,
            }
        )
    except Exception as exc:  # 采集脚本：单 case 失败不阻断批次，原样记录
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["elapsed_s"] = round(time.time() - started, 1)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="impl/data/llm_probe/mock_cases.json")
    parser.add_argument("--only", default="", help="逗号分隔的 case id 过滤")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    cases = json.loads((REPO_ROOT / args.cases).read_text(encoding="utf-8"))
    only = {item.strip() for item in args.only.split(",") if item.strip()}
    spec = load_project("llm_probe")

    records = []
    for case in cases:
        case_id = str(case.get("id") or "")
        if only and case_id not in only:
            continue
        record = run_case(spec, case)
        records.append(record)
        status = record.get("error") or (
            (record.get("judge") or {}).get("overall_fulfillment") or {}
        ).get("status", "?")
        print(f"[{case_id}] {status} ({record['elapsed_s']}s)", flush=True)

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"wrote {len(records)} records -> {out_path}")


if __name__ == "__main__":
    main()
