"""
Test edge case: verdict modified by reconcile + empty fulfillment_assessments.

Scenario:
1. reconcile_equivalent_judge_result() changes verdict to "correct"
2. reconcile_equivalent_judge_result() clears fulfillment_assessments
3. derive_verdict_from_fulfillment() is called
4. Expected: verdict stays "correct", overall_fulfillment is set properly
"""

from impl.core.schema import JudgeResult


def test_verdict_correct_with_empty_fulfillment():
    """When verdict is 'correct' but fulfillment_assessments is empty."""

    # Simulate state after reconcile_equivalent_judge_result()
    judge = JudgeResult(
        trace_id="test-reconciled",
        project_id="client_search",
        verdict="correct",  # Changed by reconcile
        score=1,
        judge_basis="semantic_equivalence_reconciliation",
        fulfillment_assessments=[],  # Cleared by reconcile
        overall_fulfillment={},  # Cleared by reconcile
    )

    # Call derive (happens after reconcile in adapter.py)
    result = judge.derive_verdict_from_fulfillment()

    # Verify verdict is preserved
    assert judge.verdict == "correct", "Verdict should stay correct"
    assert result == "correct"

    # Check overall_fulfillment
    print(f"overall_fulfillment: {judge.overall_fulfillment}")

    # Issue: overall_fulfillment might be empty {}
    # because line 202 in schema.py checks "if statuses:" which is False when empty

    if not judge.overall_fulfillment or not judge.overall_fulfillment.get("status"):
        print("⚠️  WARNING: overall_fulfillment is empty or has no status")
        print("   This could cause inconsistency in frontend display")
        print("   Verdict says 'correct' but fulfillment status is unknown")
        return False
    else:
        print("✓ overall_fulfillment is properly set")
        return True


if __name__ == "__main__":
    success = test_verdict_correct_with_empty_fulfillment()
    if success:
        print("\n[PASS] Edge case handled correctly")
    else:
        print("\n[WARNING] Edge case needs attention")
        print("Recommendation: When verdict is set but fulfillment_assessments is empty,")
        print("derive_verdict_from_fulfillment() should still set a default overall_fulfillment")
