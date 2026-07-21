import pytest

from impl.core.attribute_protocol import ProjectAttribute
from impl.core.schema import AttributeResult, AttributionFinding, EvidenceRef, FulfillmentAssessment, JudgeResult, ProjectSpec, RunTrace
from impl.projects.deerflow.attribute import DeerflowAttribute, _message_lists, _runtime_checks
from impl.projects.deerflow.draft.cases.attribute_iteration import load_cases
from impl.projects.deerflow.draft.tools.investigation_tools import build_budget_reconcile_tool, build_message_history_replay_tool
from impl.core.schema import normalize_judge_result, normalize_run_trace
from impl.core.project_loader import load_project


def _judge():
    return JudgeResult(
        trace_id="trace-1", project_id="deerflow",
        fulfillment_assessments=[FulfillmentAssessment(expectation_id="reply", status="not_fulfilled")],
        overall_fulfillment={"status": "not_fulfilled"},
    )


def _evidence(case_id=""):
    return EvidenceRef(
        ref_id="ev-1", source="context_unit", kind="runtime_result",
        stage="attribute-round-1-finalization", summary="材料记录了当前回复为空。",
        location="cu-reply", payload=None,
        metadata={"source_hash": "sha256:reply", "trace_id": "trace-1", "case_id": case_id},
    )


class _MinimalAttribute(ProjectAttribute):
    def build_context(self, trace, judge_result):
        return {}


def test_common_gate_rejects_finding_without_finalized_evidence():
    attribute = _MinimalAttribute(ProjectSpec(project_id="deerflow", name="deerflow"))
    result = AttributeResult("trace-1", "deerflow", findings=[AttributionFinding("finding-1", ["reply"], "回复提取为空。", [])])
    with pytest.raises(ValueError, match="finalized evidence"):
        attribute._validate_attribute_output(result, {}, _judge())


def test_common_gate_rejects_non_failed_expectation_coverage():
    attribute = _MinimalAttribute(ProjectSpec(project_id="deerflow", name="deerflow"))
    result = AttributeResult("trace-1", "deerflow", findings=[AttributionFinding("finding-1", ["other"], "回复提取为空。", [_evidence()])])
    with pytest.raises(ValueError, match="not_fulfilled"):
        attribute._validate_attribute_output(result, {}, _judge())


def test_common_gate_requires_unresolved_reason_for_partial_coverage():
    judge = _judge()
    judge.fulfillment_assessments.append(FulfillmentAssessment(expectation_id="tool", status="not_fulfilled"))
    attribute = _MinimalAttribute(ProjectSpec(project_id="deerflow", name="deerflow"))
    result = AttributeResult("trace-1", "deerflow", findings=[AttributionFinding("finding-1", ["reply"], "回复提取为空。", [_evidence()])])
    with pytest.raises(ValueError, match="partial attribution"):
        attribute._validate_attribute_output(result, {}, judge)


def test_deerflow_project_normalize_does_not_invent_or_upgrade_evidence():
    attribute = DeerflowAttribute(ProjectSpec(project_id="deerflow", name="deerflow"))
    result = AttributeResult("trace-1", "deerflow", unresolved_reason="缺少原始回复材料。")
    normalized = attribute.normalize_result(RunTrace(trace_id="trace-1", project_id="deerflow"), _judge(), result)
    assert normalized.findings == []
    assert normalized.unresolved_reason == "缺少原始回复材料。"


def test_historical_trace_replay_locates_stale_tool_extraction_before_stage():
    case = load_cases()[0]
    trace = normalize_run_trace(case["trace"])
    judge = normalize_judge_result(case["judge_result"])

    checks = _runtime_checks(trace, judge)

    assert checks["tool_call_extraction_mismatch_turns"] == [2]
    assert 2 in checks["stage_inference_mismatch_turns"]
    assert "tool_call_extraction" in checks["confirmed_code_locations"]


def test_message_history_replay_uses_latest_business_ai_message_only():
    case = load_cases()[0]
    final_turn = case["trace"]["turn_records"][-1]
    message_lists = _message_lists(final_turn["raw_response"])
    messages = message_lists[-1]
    tool = build_message_history_replay_tool()

    result = tool.execute_fn(messages=messages)

    assert result.status == "succeeded"
    assert result.actual["tool_calls"] == []
    assert result.actual["derived_stage"] == "planning"
    assert result.actual["stage_rule"] == "structured_planning_reply"
    assert "Gateway-provided business stage" in result.boundary_limits[-1]


def test_budget_reconcile_preserves_quotes_and_exposes_omitted_cost():
    result = build_budget_reconcile_tool().execute_fn(
        budget_limit=50_000,
        claimed_total=50_000,
        components=[
            {"name": "cash discount", "unit_cost": 40, "quantity": 1000, "source_quote": "会员让利（40元×1000份）4万元"},
            {"name": "gift", "unit_cost": 30, "quantity": 1000, "source_quote": "赠送礼品价值30元"},
            {"name": "media", "total": 10_000, "source_quote": "投放费用1万元"},
        ],
    )

    assert result.status == "succeeded"
    assert result.actual["computed_total"] == 80_000
    assert result.actual["over_budget_by"] == 30_000
    assert result.actual["claimed_total_delta"] == 30_000
    assert result.actual["within_budget"] is False
    assert result.actual["components"][1]["source_quote"] == "赠送礼品价值30元"


def test_budget_reconcile_exposes_conflicting_declared_component_total_in_one_call():
    result = build_budget_reconcile_tool().execute_fn(
        budget_limit=50_000,
        claimed_total=50_000,
        components=[
            {"name": "cash", "unit_cost": 40, "quantity": 1000, "total": 40_000, "source_quote": "40元×1000份=4万元"},
            {"name": "gift", "unit_cost": 30, "quantity": 1000, "total": 0, "source_quote": "30元×1000份，表中写0元"},
            {"name": "media", "total": 10_000, "source_quote": "投放1万元"},
        ],
    )

    assert result.actual["computed_total"] == 80_000
    assert result.actual["components"][1]["supplied_total"] == 0
    assert result.actual["components"][1]["unit_extended_total"] == 30_000
    assert result.actual["component_total_conflicts"] == [{
        "name": "gift",
        "supplied_total": 0.0,
        "unit_extended_total": 30_000.0,
        "delta": 30_000.0,
    }]


def test_budget_branch_requires_primary_output_and_derived_reconciliation_evidence():
    from impl.projects.deerflow.draft.attribute import DeerflowDraftAttribute

    context = DeerflowDraftAttribute(load_project("deerflow")).build_context(
        RunTrace(trace_id="trace-budget", project_id="deerflow"),
        _judge(),
    )
    prompt = context["system_prompt_override"]

    assert "failed_business_output current case runtime_checks" in prompt
    assert "必须同时引用 runtime_checks 原始业务输出和预算 Tool 重算结果" in prompt


def test_historical_fixture_migrates_schema_without_changing_verdicts():
    cases = load_cases()

    assert [case["judge_result"]["overall_fulfillment"]["status"] for case in cases] == [
        "not_fulfilled",
        "fulfilled",
        "not_fulfilled",
    ]
    for case in cases:
        assert all("blocking" in item for item in case["judge_result"]["business_expectations"])
        assert all("blocking" not in item for item in case["judge_result"]["fulfillment_assessments"])


def test_draft_context_exposes_only_material_extraction_deltas():
    from impl.projects.deerflow.draft.attribute import DeerflowDraftAttribute

    case = load_cases()[0]
    trace = normalize_run_trace(case["trace"])
    judge = normalize_judge_result(case["judge_result"])
    context = DeerflowDraftAttribute(load_project("deerflow")).build_context(trace, judge)

    assert context["runtime_checks"]["decisive_extraction_deltas"] == [{
        "turn_index": 2,
        "raw_reply_matches": True,
        "raw_tool_names": [],
        "extracted_tool_names": ["ask_clarification"],
        "stored_stage": "clarification",
        "raw_replay_stage": "planning",
        "raw_replay_stage_rule": "structured_planning_reply",
    }]


def test_unrecorded_raw_history_is_not_treated_as_empty_gateway_output():
    from impl.projects.deerflow.draft.attribute import DeerflowDraftAttribute

    trace = RunTrace(
        trace_id="trace-projected",
        project_id="deerflow",
        turn_records=[{
            "turn_index": 1,
            "request": {
                "input": {
                    "messages": [{"role": "user", "content": "预算五万元，目标一百名新会员。"}],
                },
            },
            "extracted_output": {
                "reply_text": "还需要补充什么信息？",
                "tool_calls": [{
                    "name": "ask_clarification",
                    "args": {"question": "还需要补充什么信息？"},
                }],
                "stage": "clarification",
            },
            "call_status": "succeeded",
        }],
    )
    context = DeerflowDraftAttribute(load_project("deerflow")).build_context(trace, _judge())
    checks = context["runtime_checks"]

    assert checks["raw_message_history_unrecorded_turns"] == [1]
    assert checks["reply_extraction_mismatch_turns"] == []
    assert checks["tool_call_extraction_mismatch_turns"] == []
    assert checks["stage_inference_mismatch_turns"] == []
    assert checks["decisive_extraction_deltas"] == []
    assert checks["clarification_sequence"] == [{
        "turn_index": 1,
        "user_text": "预算五万元，目标一百名新会员。",
        "ask_clarification_questions": ["还需要补充什么信息？"],
        "reply_text": "还需要补充什么信息？",
        "stage": "clarification",
        "call_status": "succeeded",
    }]
    assert checks["failed_business_output"]["not_fulfilled_assessments"] == [{
        "expectation_id": "reply",
        "expected_evidence": [],
        "actual_evidence": [],
    }]
