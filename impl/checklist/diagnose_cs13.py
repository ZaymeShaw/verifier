#!/usr/bin/env python3
"""
诊断 cs#13 归因失败问题。

Case: "客户姓名是张伟的人"
- Expected: value="张伟"
- Actual: value="张伟的人"
- Judge: not_fulfilled, wrong: gap
- Attr: 未归因, expectation_attributions=0

目标：
- 重新运行 cs#13 的 judge/attribute
- 检查 Attr LLM 返回的原始数据
- 判断为什么 expectation_attributions 为空
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from impl.core.pipeline import live_run, judge, attribute
from impl.core.schema import to_dict


def diagnose_cs13():
    """重跑 cs#13，检查 Attr 返回的原始数据。"""

    print("="*60)
    print("诊断 cs#13: 客户姓名是张伟的人")
    print("="*60)

    # Input
    input_data = {"query": "客户姓名是张伟的人"}
    user_intent = '{"expected_logic":"AND","expected_conditions":[{"field":"searchClientName","operator":"MATCH","value":"张伟"}]}'

    try:
        # Step 1: Run trace
        print("\n[Step 1] Running trace...")
        trace = live_run(
            project_id="client_search",
            input_data=input_data,
        )

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
        print(f"  Fulfillment: {(judge_result.overall_fulfillment or {}).get('status')}")
        print(f"  Quality flags: {judge_result.quality_flags}")

        # Step 3: Attribute
        print("\n[Step 3] Attributing...")
        attr_result = attribute(
            project_id="client_search",
            trace=trace,
            judge_result=judge_result,
        )

        print(f"  Causal category: {attr_result.causal_category}")
        print(f"  Failure category: {attr_result.failure_category}")
        print(f"  Attribution findings count: {len(attr_result.findings)}")
        print(f"  Incomplete reason: {attr_result.incomplete_reason}")
        print(f"  Quality flags: {attr_result.quality_flags}")

        # Step 4: 检查原始 LLM 输出
        print("\n[Step 4] Raw LLM output...")
        raw_output = attr_result.raw_model_output
        if isinstance(raw_output, dict):
            print(f"  Has error: {bool(raw_output.get('error'))}")
            print(f"  Has expectation_attributions: {bool(raw_output.get('expectation_attributions'))}")

            if raw_output.get('expectation_attributions'):
                print(f"  Expectation attributions: {json.dumps(raw_output['expectation_attributions'], ensure_ascii=False, indent=2)[:500]}")
            else:
                print(f"  ⚠️ expectation_attributions is empty or missing!")
                print(f"  Raw output keys: {list(raw_output.keys())}")

                # 显示部分原始输出以诊断
                if raw_output.get('raw_text'):
                    print(f"  Raw text (first 500 chars): {raw_output['raw_text'][:500]}")
                if raw_output.get('causal_category'):
                    print(f"  Causal category: {raw_output.get('causal_category')}")
                if raw_output.get('failure_category'):
                    print(f"  Failure category: {raw_output.get('failure_category')}")
        else:
            print(f"  Raw output type: {type(raw_output)}")
            print(f"  Raw output: {str(raw_output)[:500]}")

        # Step 5: 保存完整结果
        result = {
            "trace": to_dict(trace),
            "judge": to_dict(judge_result),
            "attribute": to_dict(attr_result),
        }

        output_file = Path("tmp/cs13_diagnosis.json")
        output_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\n[Result] Full diagnosis saved to: {output_file}")

        # Summary
        print("\n"+"="*60)
        print("SUMMARY")
        print("="*60)

        if len(attr_result.findings) == 0:
            print("✗ BUG REPRODUCED: expectation_attributions is empty")
            print("  Possible causes:")
            print("  1. LLM returned JSON without expectation_attributions field")
            print("  2. LLM call failed but error not caught")
            print("  3. LLM analysis concluded no attribution needed (wrong)")
        else:
            print("✓ Attribution successful")

    except Exception as e:
        print(f"\n✗ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    diagnose_cs13()
