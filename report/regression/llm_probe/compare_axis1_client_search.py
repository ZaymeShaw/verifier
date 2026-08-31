"""轴1对照：同一批查询分别走 llm_probe 探测 client_search 与原生 client_search，比 judge 结果。

用法（repo 根目录，需 :8000 client_search 与 LLM 可达）：
    python report/regression/llm_probe/compare_axis1_client_search.py \
        --out report/regression/llm_probe/axis1-compare-YYYYMMDD.json

只比轴1（overall + 各 assessment 三态），轴2不在本对照范围。
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
from impl.core.schema import SingleTurnCase, to_dict  # noqa: E402

QUERIES = [
    ("name-exact", "客户姓名是张伟的人"),
    ("age-50plus", "五十岁以上的客户都有谁"),
    ("annuity-exclusion", "不要买了年金险的客户"),
    ("multi-cond", "我想找年龄超过45岁的女客户，而且她们每年交的保费要在一万块以上"),
    ("family-slang", "帮我查一下那些上有老下有小的客户"),
]

SHOW_SCHEMA = {
    "type": "object",
    "description": "关注解析出的搜索条件（字段、操作符、值），忽略路由、追踪字段和 matched_patterns 里的提示词泄漏",
}


def _probe_input(name: str, query: str) -> dict:
    return {
        "capability_ref": "client_search",
        "method": "POST",
        "body": {
            "user_text": query,
            "user_id": "mock_user_001",
            "trace_id": f"cmp-{name}",
            "session_id": f"cmp-{name}",
            "source": "axis1_compare",
            "extra_input_params": {},
        },
        "show_schema": SHOW_SCHEMA,
    }


def _judge_digest(judge_result) -> dict:
    payload = to_dict(judge_result)
    blocking = {
        str(item.get("expectation_id") or ""): bool(item.get("blocking"))
        for item in payload.get("business_expectations") or []
    }
    return {
        "overall": (payload.get("overall_fulfillment") or {}).get("status"),
        "assessments": [
            {
                "expectation_id": item.get("expectation_id"),
                "status": item.get("status"),
                "blocking": blocking.get(str(item.get("expectation_id") or "")),
            }
            for item in payload.get("fulfillment_assessments") or []
        ],
        "reasoning": str(payload.get("reasoning_summary") or "")[:400],
    }


def _run(project_id: str, case_id: str, live_input: dict) -> dict:
    started = time.time()
    try:
        trace = pipeline.live_run(project_id, SingleTurnCase(id=case_id, input=live_input))
        judge_result = pipeline.judge(project_id, trace)
        output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
        return {
            "judge": _judge_digest(judge_result),
            "output_head": json.dumps(output, ensure_ascii=False)[:400],
            "elapsed_s": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(time.time() - started, 1)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    records = []
    for name, query in QUERIES:
        record = {"name": name, "query": query}
        record["llm_probe"] = _run("llm_probe", f"cmp-probe-{name}", _probe_input(name, query))
        print(f"[{name}] llm_probe -> {record['llm_probe'].get('judge', {}).get('overall') or record['llm_probe'].get('error', '?')}", flush=True)
        record["client_search"] = _run("client_search", f"cmp-native-{name}", {"user_text": query})
        print(f"[{name}] client_search -> {record['client_search'].get('judge', {}).get('overall') or record['client_search'].get('error', '?')}", flush=True)
        records.append(record)

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"wrote {len(records)} comparisons -> {out_path}")


if __name__ == "__main__":
    main()
