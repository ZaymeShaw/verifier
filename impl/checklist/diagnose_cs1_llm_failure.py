#!/usr/bin/env python3
"""
深度诊断 client_search case #1 LLM 调用失败
捕获原始错误信息和 LLM 响应
"""
import sys
import json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from impl.core.pipeline import run_chain
from impl.core.schema import SingleTurnCase


def diagnose_cs1():
    print("=" * 60)
    print("深度诊断 cs#1: 45岁女性保费10万以上")
    print("=" * 60)

    # Define test input
    test_input = {
        "query": "45岁女性保费10万以上"
    }

    print(f"\n[Step 1] Test input:")
    print(f"  Query: {test_input['query']}")

    # Run full chain
    print(f"\n[Step 2] Running full chain...")
    try:
        result = run_chain("client_search", SingleTurnCase(id="cs1-diagnostic", input=test_input))
        trace = result.get("trace")
        judge_result = result.get("judge")

        if trace:
            print(f"  Trace ID: {trace.trace_id}")
            print(f"  Trace status: {trace.status}")
            if trace.error:
                print(f"  Trace error: {trace.error}")
        else:
            print(f"  ⚠️ No trace returned")
    except Exception as e:
        print(f"  ❌ Chain failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Analyze judge result
    print(f"\n[Step 3] Analyzing judge result...")
    if not judge_result:
        print("  ❌ No judge result returned")
        return

    try:
        print(f"  Verdict: {judge_result.verdict}")
        print(f"  Score: {judge_result.score}")
        print(f"  Quality flags: {judge_result.quality_flags}")

        # Check raw model output
        print(f"\n[Step 4] Raw LLM output analysis:")
        if judge_result.raw_model_output:
            print(f"  Type: {type(judge_result.raw_model_output)}")
            if isinstance(judge_result.raw_model_output, dict):
                print(f"  Keys: {list(judge_result.raw_model_output.keys())}")
                if "error" in judge_result.raw_model_output:
                    print(f"  ❌ Error in raw output: {judge_result.raw_model_output['error']}")
                if "raw_response" in judge_result.raw_model_output:
                    print(f"  Raw response type: {type(judge_result.raw_model_output['raw_response'])}")
                    raw_resp_str = str(judge_result.raw_model_output['raw_response'])
                    print(f"  Raw response preview: {raw_resp_str[:500]}")
                    if len(raw_resp_str) > 500:
                        print(f"  Raw response length: {len(raw_resp_str)} chars")
            else:
                print(f"  Content: {str(judge_result.raw_model_output)[:500]}")
        else:
            print(f"  ⚠️ No raw_model_output available")

        # Check for LLM call failure indicators
        print(f"\n[Step 5] LLM call failure indicators:")
        llm_failed = False
        if "llm_call_failed" in judge_result.quality_flags:
            print(f"  ✓ Quality flag: llm_call_failed")
            llm_failed = True
        if judge_result.verdict == "uncertain" and not judge_result.business_expectations:
            print(f"  ✓ Verdict: uncertain + empty business_expectations")
            llm_failed = True
        if not judge_result.fulfillment_assessments:
            print(f"  ✓ Empty fulfillment_assessments")

        # Save full result
        output_path = project_root / "tmp" / "cs1_llm_failure_diagnosis.json"
        output_path.parent.mkdir(exist_ok=True)

        from impl.core.schema import to_dict
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "trace": to_dict(trace) if trace else None,
                "judge": to_dict(judge_result)
            }, f, indent=2, ensure_ascii=False)

        print(f"\n[Result] Full diagnosis saved to: {output_path}")

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        if llm_failed:
            print("✗ LLM call failed")
            print("\n根因分析：")
            print("检查 raw_model_output 中的 error 字段获取详细错误信息")
        else:
            print("✓ LLM call succeeded")

    except Exception as e:
        print(f"  ❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    diagnose_cs1()
