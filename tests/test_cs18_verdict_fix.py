"""
Regression test for cs#18 verdict bug fix.

This test simulates the exact scenario from cs#18:
- LLM analyzes "不是A类客户" and concludes "correct" with score=1.0
- Fulfillment status is "not_evaluable" because ES is unavailable
- Before fix: verdict gets overridden to "uncertain"
- After fix: verdict stays "correct" as LLM determined
"""

from impl.core.schema import JudgeResult, FulfillmentAssessment


def test_cs18_scenario():
    """
    Simulate cs#18: LLM says correct despite ES unavailable.

    Case: 不是A类客户
    - LLM analysis: "系统正确选择了newValueLabel字段...综上判定correct"
    - Score: 1.0 (full marks)
    - Fulfillment: not_evaluable (ES Connection refused)

    Expected: verdict should remain "correct" (LLM's judgment)
    Not: verdict should not be overridden to "uncertain" just because ES is down
    """

    # Setup: Mirror cs#18's judge_result structure
    judge = JudgeResult(
        trace_id="cs-18-test",
        project_id="client_search",
        verdict="correct",  # LLM's explicit verdict
        score=1.0,  # Full marks
        judge_basis=(
            "查询'不是A类客户'要求排除客户价值等级为A类的客户。"
            "系统正确选择了newValueLabel字段(客户价值标签)，"
            "使用NOT_CONTAINS操作符表达否定排除，"
            "值[A1,A2,A3,A4]完整覆盖A类所有子等级(A1/A2/A3/A4)。"
            "查询逻辑AND无问题。条件完全覆盖用户意图，无缺失、无错误、无多余条件。"
            "虽然capability_manifest对newValueLabel仅列出CONTAINS，"
            "但NOT_CONTAINS在ES搜索语义中是CONTAINS的标准否定形式，"
            "且下游适配器已接受该条件。综上判定correct。"
        ),
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="search_condition_correctness",
                status="not_evaluable",  # ES unavailable: Connection refused
                blocking=True,
            )
        ],
    )

    # Before fix: This would override verdict to "uncertain"
    # After fix: This should preserve verdict as "correct"
    derived = judge.derive_verdict_from_fulfillment()

    # Verify: LLM's "correct" verdict is preserved
    assert judge.verdict == "correct", (
        f"Expected verdict='correct' (LLM judgment), got '{judge.verdict}'. "
        "ES being unavailable should not override LLM's explicit analysis."
    )
    assert derived == "correct"
    assert judge.score == 1.0

    # Verify: overall_fulfillment is correctly set despite ES issue
    assert judge.overall_fulfillment["status"] == "fulfilled"
    assert judge.overall_fulfillment["assessment_count"] == 1

    # Verify: verdict_derivation shows it came from LLM
    assert judge.verdict_derivation["primary_source"] == "llm_explicit_verdict"

    print("✓ cs#18 scenario: LLM verdict preserved despite ES unavailable")


def test_cs18_contrast_no_llm_verdict():
    """
    Contrast case: When LLM verdict is missing, derive should infer "uncertain".

    If LLM failed to provide verdict (e.g., LLM call failed), then
    derive_verdict_from_fulfillment should infer "uncertain" from "not_evaluable".
    """

    judge = JudgeResult(
        trace_id="cs-18-contrast",
        project_id="client_search",
        verdict="",  # No LLM verdict (LLM call failed)
        score=None,
        judge_basis="",
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="search_condition_correctness",
                status="not_evaluable",
                blocking=True,
            )
        ],
    )

    derived = judge.derive_verdict_from_fulfillment()

    # When LLM provides no verdict, derive should infer from fulfillment
    assert judge.verdict == "uncertain"
    assert derived == "uncertain"
    assert judge.verdict_derivation["primary_source"] == "fulfillment_assessments"

    print("✓ Contrast case: Derive 'uncertain' when LLM verdict missing")


if __name__ == "__main__":
    print("Test: cs#18 verdict fix")
    print("-" * 60)

    try:
        test_cs18_scenario()
    except AssertionError as e:
        print(f"✗ FAIL: {e}")
        exit(1)

    try:
        test_cs18_contrast_no_llm_verdict()
    except AssertionError as e:
        print(f"✗ FAIL: {e}")
        exit(1)

    print("-" * 60)
    print("All cs#18 tests passed ✓")
