"""Test for verdict derivation bug: derive_verdict_from_fulfillment unconditionally overrides LLM verdict.

Bug: When LLM analyzes a case and concludes "correct" with score=1.0, but fulfillment status is
"not_evaluable" (e.g., due to ES unavailable), derive_verdict_from_fulfillment() unconditionally
overwrites verdict to "uncertain", causing contradiction between judge_basis and verdict.

Expected: derive_verdict_from_fulfillment() should only derive when LLM verdict is missing/empty.
If LLM provides explicit verdict, that should be preserved.
"""

from impl.core.schema import JudgeResult, FulfillmentAssessment


def test_derive_should_not_override_llm_verdict():
    """When LLM provides explicit verdict, derive should not override it."""

    # Setup: LLM analyzed and concluded "correct" with score=1.0
    judge = JudgeResult(
        trace_id="test-001",
        project_id="client_search",
        verdict="correct",  # LLM's explicit verdict
        score=1.0,
        judge_basis="查询'不是A类客户'...综上判定correct。",  # LLM's reasoning
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="search_condition_correctness",
                status="not_evaluable",  # ES unavailable
                blocking=True,
            )
        ],
    )

    # After fix: derive_verdict_from_fulfillment() should preserve LLM verdict
    derived = judge.derive_verdict_from_fulfillment()

    # Expected behavior: LLM's "correct" verdict should be preserved
    # because LLM explicitly analyzed and concluded correct despite ES being unavailable
    assert judge.verdict == "correct"  # Fixed: preserve LLM verdict
    assert derived == "correct"


def test_derive_should_work_when_llm_verdict_missing():
    """When LLM verdict is missing, derive should infer from fulfillment."""

    # Setup: No LLM verdict (maybe LLM call failed)
    judge = JudgeResult(
        trace_id="test-002",
        project_id="client_search",
        verdict="",  # No LLM verdict
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

    # Expected: Should derive "uncertain" when LLM provides no verdict
    derived = judge.derive_verdict_from_fulfillment()
    assert judge.verdict == "uncertain"
    assert derived == "uncertain"


def test_derive_should_respect_not_fulfilled():
    """When fulfillment is clearly not_fulfilled, derive should be 'incorrect'."""

    judge = JudgeResult(
        trace_id="test-003",
        project_id="client_search",
        verdict="",  # No explicit verdict
        score=None,
        judge_basis="",
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="search_condition_correctness",
                status="not_fulfilled",
                blocking=True,
            )
        ],
    )

    derived = judge.derive_verdict_from_fulfillment()
    assert judge.verdict == "incorrect"
    assert derived == "incorrect"


def test_derive_should_respect_fulfilled():
    """When all fulfillments are fulfilled, derive should be 'correct'."""

    judge = JudgeResult(
        trace_id="test-004",
        project_id="client_search",
        verdict="",
        score=None,
        judge_basis="",
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="search_condition_correctness",
                status="fulfilled",
                blocking=False,
            )
        ],
    )

    derived = judge.derive_verdict_from_fulfillment()
    assert judge.verdict == "correct"
    assert derived == "correct"


if __name__ == "__main__":
    print("Test 1: derive_should_not_override_llm_verdict")
    try:
        test_derive_should_not_override_llm_verdict()
        print("  ✓ PASS (bug confirmed: verdict overridden to uncertain)")
    except AssertionError as e:
        print(f"  ✗ FAIL: {e}")

    print("\nTest 2: derive_should_work_when_llm_verdict_missing")
    try:
        test_derive_should_work_when_llm_verdict_missing()
        print("  ✓ PASS")
    except AssertionError as e:
        print(f"  ✗ FAIL: {e}")

    print("\nTest 3: derive_should_respect_not_fulfilled")
    try:
        test_derive_should_respect_not_fulfilled()
        print("  ✓ PASS")
    except AssertionError as e:
        print(f"  ✗ FAIL: {e}")

    print("\nTest 4: derive_should_respect_fulfilled")
    try:
        test_derive_should_respect_fulfilled()
        print("  ✓ PASS")
    except AssertionError as e:
        print(f"  ✗ FAIL: {e}")
