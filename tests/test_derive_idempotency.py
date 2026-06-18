"""
Test idempotency of derive_verdict_from_fulfillment() after fix.

After the fix, calling derive_verdict_from_fulfillment() multiple times
should be idempotent when LLM has provided a verdict.
"""

from impl.core.schema import JudgeResult, FulfillmentAssessment


def test_derive_is_idempotent():
    """Multiple calls should not change the verdict when LLM provided one."""

    judge = JudgeResult(
        trace_id="test-idempotent",
        project_id="client_search",
        verdict="correct",
        score=1.0,
        judge_basis="LLM analysis concludes correct",
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="test_expectation",
                status="not_evaluable",
                blocking=True,
            )
        ],
    )

    # First call
    result1 = judge.derive_verdict_from_fulfillment()
    verdict_after_first = judge.verdict
    overall_after_first = judge.overall_fulfillment

    # Second call (simulating pipeline's redundant call)
    result2 = judge.derive_verdict_from_fulfillment()
    verdict_after_second = judge.verdict
    overall_after_second = judge.overall_fulfillment

    # Third call
    result3 = judge.derive_verdict_from_fulfillment()
    verdict_after_third = judge.verdict

    # Verify idempotency
    assert result1 == "correct", "First call should return correct"
    assert result2 == "correct", "Second call should return correct"
    assert result3 == "correct", "Third call should return correct"

    assert verdict_after_first == "correct", "Verdict should stay correct after first call"
    assert verdict_after_second == "correct", "Verdict should stay correct after second call"
    assert verdict_after_third == "correct", "Verdict should stay correct after third call"

    # Verify overall_fulfillment is stable
    assert overall_after_first == overall_after_second, "overall_fulfillment should be stable"

    print("✓ derive_verdict_from_fulfillment() is idempotent")


if __name__ == "__main__":
    try:
        test_derive_is_idempotent()
        print("\n[PASS] Idempotency test passed - redundant calls in pipeline are safe")
    except AssertionError as e:
        print(f"\n[FAIL] Idempotency test failed: {e}")
        exit(1)
