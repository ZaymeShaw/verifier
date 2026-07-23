#!/usr/bin/env python3
"""
诊断 LLM 调用失败的 3 个 case。

失败 cases:
1. mpi#4: "我要做明年的目标达成规划"
2. cs#10: "已购买保险的客户"
3. cs#17: "男性或者女性客户"

目标：
- 重新运行这 3 个 case 的 judge/attribute
- 捕获详细的错误信息
- 判断是随机失败还是系统性问题
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from impl.core.pipeline import live_run, judge, attribute
from impl.core.schema import SingleTurnCase


def diagnose_llm_failures():
    """重跑 3 个失败 case，记录详细错误信息。"""

    test_cases = [
        {
            "project": "marketting-planning-intent",
            "case_id": "mpi-required-slot-missing-1",
            "input": {"user_text": "我要做明年的目标达成规划"},
            "user_intent": '{"intent":"nbev_planning","min_confidence":0.7,"required_slots":["year"],"allow_fallback":false}',
        },
        {
            "project": "client_search",
            "case_id": "crosssell_car_customer_insurance-status-011",
            "input": {"query": "已购买保险的客户"},
            "user_intent": '{"expected_logic":"AND","expected_conditions":[{"field":"isBuyInsurance","operator":"MATCH","value":"是"}]}',
        },
        {
            "project": "client_search",
            "case_id": "logic_negative_existence-001",
            "input": {"query": "男性或者女性客户"},
            "user_intent": '{"expected_logic":"AND","expected_conditions":[{"field":"clientSex","operator":"MATCH","value":"男"},{"field":"clientSex","operator":"MATCH","value":"女"}]}',
        },
    ]

    results = []

    for i, tc in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}/3: {tc['project']} - {tc['case_id']}")
        print(f"Input: {tc['input']}")
        print(f"{'='*60}")

        try:
            # Run the case
            trace = live_run(
                project_id=tc["project"],
                case=SingleTurnCase(
                    id=tc["case_id"],
                    input=tc["input"],
                    user_intent=tc.get("user_intent") or "",
                ),
            )

            # Judge the trace
            judge_result = judge(
                project_id=tc["project"],
                trace=trace,
                user_intent=tc.get("user_intent"),
            )

            # Attribute the result
            attr_result = attribute(
                project_id=tc["project"],
                trace=trace,
                judge_result=judge_result,
            )

            # Check judge result
            judge_ok = judge_result and judge_result.verdict and judge_result.verdict != "uncertain"
            judge_has_llm_error = (
                judge_result
                and ("llm_call_failed" in (judge_result.quality_flags or []))
            )

            # Check attribute result
            attr_ok = attr_result and attr_result.causal_category != "未归因"
            attr_has_llm_error = (
                attr_result
                and ("llm_call_failed" in (attr_result.quality_flags or []))
            )

            status = {
                "case": f"{tc['project']} - {tc['case_id']}",
                "judge_ok": judge_ok,
                "judge_verdict": judge_result.verdict if judge_result else None,
                "judge_has_llm_error": judge_has_llm_error,
                "judge_quality_flags": judge_result.quality_flags if judge_result else [],
                "attr_ok": attr_ok,
                "attr_category": attr_result.causal_category if attr_result else None,
                "attr_has_llm_error": attr_has_llm_error,
                "attr_quality_flags": attr_result.quality_flags if attr_result else [],
            }

            results.append(status)

            print(f"\n[Judge]")
            print(f"  OK: {judge_ok}")
            print(f"  Verdict: {status['judge_verdict']}")
            print(f"  Has LLM error: {judge_has_llm_error}")
            print(f"  Quality flags: {status['judge_quality_flags']}")

            print(f"\n[Attribute]")
            print(f"  OK: {attr_ok}")
            print(f"  Category: {status['attr_category']}")
            print(f"  Has LLM error: {attr_has_llm_error}")
            print(f"  Quality flags: {status['attr_quality_flags']}")

        except Exception as e:
            print(f"\n✗ EXCEPTION: {e}")
            import traceback

            traceback.print_exc()
            results.append(
                {
                    "case": f"{tc['project']} - {tc['case_id']}",
                    "exception": str(e),
                }
            )

    # Summary
    print(f"\n\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    total = len(test_cases)
    judge_failures = sum(
        1 for r in results if r.get("judge_has_llm_error") or not r.get("judge_ok")
    )
    attr_failures = sum(
        1 for r in results if r.get("attr_has_llm_error") or not r.get("attr_ok")
    )
    exceptions = sum(1 for r in results if "exception" in r)

    print(f"Total cases: {total}")
    print(f"Judge LLM failures: {judge_failures}/{total}")
    print(f"Attr LLM failures: {attr_failures}/{total}")
    print(f"Exceptions: {exceptions}/{total}")

    # Write results
    output_file = Path("tmp/llm_failure_diagnosis.json")
    output_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nDetailed results written to: {output_file}")

    if judge_failures == 0 and attr_failures == 0 and exceptions == 0:
        print("\n✓ All cases passed on retry - failures were likely transient")
    else:
        print("\n✗ Some failures reproduced - systematic issue detected")


if __name__ == "__main__":
    diagnose_llm_failures()
