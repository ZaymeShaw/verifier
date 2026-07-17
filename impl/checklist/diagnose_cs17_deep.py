#!/usr/bin/env python3
"""
深度诊断 cs#17 LLM 失败。

Case: "男性或者女性客户"
- Judge LLM 调用失败
- 需要捕获原始 LLM 返回数据
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from impl.core.pipeline import live_run, judge
from impl.core.schema import to_dict


def deep_diagnose_cs17():
    """深度诊断 cs#17，检查 LLM 原始输出。"""

    print("="*60)
    print("深度诊断 cs#17: 男性或者女性客户")
    print("="*60)

    input_data = {"query": "男性或者女性客户"}
    user_intent = '{"expected_logic":"AND","expected_conditions":[{"field":"clientSex","operator":"MATCH","value":"男"},{"field":"clientSex","operator":"MATCH","value":"女"}]}'

    # Step 1: Run trace
    print("\n[Step 1] Running trace...")
    trace = live_run(project_id="client_search", input_data=input_data)
    print(f"  Trace ID: {trace.trace_id}")
    print(f"  Status: {trace.status}")

    output = trace.extracted_output or {}
    print(f"  Output: {json.dumps(output, ensure_ascii=False)[:200]}")

    # Step 2: Judge
    print("\n[Step 2] Judging...")
    judge_result = judge(
        project_id="client_search",
        trace=trace,
        user_intent=user_intent,
    )

    print(f"  Verdict: {judge_result.verdict}")
    print(f"  Score: {judge_result.score}")
    print(f"  Quality flags: {judge_result.quality_flags}")
    print(f"  Judge basis: {judge_result.judge_basis[:100] if judge_result.judge_basis else 'None'}")

    # Step 3: 检查原始 LLM 输出
    print("\n[Step 3] Raw LLM output analysis...")
    raw_output = judge_result.raw_model_output

    if isinstance(raw_output, dict):
        print(f"  Type: dict")
        print(f"  Keys: {list(raw_output.keys())}")

        if raw_output.get('error'):
            print(f"  ✗ ERROR FOUND: {raw_output['error']}")
            if raw_output.get('raw_text'):
                print(f"  Raw text: {raw_output['raw_text'][:500]}")
        elif raw_output.get('raw_text'):
            print(f"  Raw text (first 500 chars):\n{raw_output['raw_text'][:500]}")
        elif raw_output.get('verdict'):
            print(f"  Verdict in raw: {raw_output['verdict']}")
        else:
            print(f"  ⚠️ No error, no verdict, no raw_text")
            print(f"  Raw output sample: {json.dumps(raw_output, ensure_ascii=False)[:500]}")

        # 尝试找到具体错误信息
        for key in ['error', 'error_message', 'message', 'raw_text', 'content']:
            if key in raw_output and raw_output[key]:
                print(f"  [{key}]: {str(raw_output[key])[:300]}")

    else:
        print(f"  Type: {type(raw_output)}")
        print(f"  Content: {str(raw_output)[:500]}")

    # Step 4: 保存完整诊断
    result = {
        "input": input_data,
        "user_intent": user_intent,
        "trace": to_dict(trace),
        "judge": to_dict(judge_result),
    }

    output_file = Path("tmp/cs17_deep_diagnosis.json")
    output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[Result] Full diagnosis saved to: {output_file}")

    # Summary
    print("\n"+"="*60)
    print("SUMMARY")
    print("="*60)

    if "llm_call_failed" in (judge_result.quality_flags or []):
        print("✗ LLM call failed - BUG REPRODUCED")
        print(f"  Error type: {raw_output.get('error') if isinstance(raw_output, dict) else 'unknown'}")
        return False
    else:
        print("✓ LLM call succeeded")
        return True


if __name__ == "__main__":
    success = deep_diagnose_cs17()
    exit(0 if success else 1)
