"""schema fixture 数据：用于测试和 demo。

spec/info-volume.md 后的精简版：JudgeResult/AttributeResult 只保留通用最小字段集。
项目特有字段已下沉到项目层，这里只构造通用层字段。
"""
from __future__ import annotations

from typing import Any

from impl.core.schema.attribute import AttributeResult, ExpectationAttribution
from impl.core.schema.evidence import EvidenceRef, ExecutionTraceEvent, ProbeResult
from impl.core.schema.fallback import FallbackDecision
from impl.core.schema.judge import BusinessExpectation, FulfillmentAssessment, GapItem, JudgeResult
from impl.core.schema.cluster import ClusterSummary
from impl.core.schema.check import CheckReport
from impl.core.schema.frontend import FrontendViewModel
from impl.core.schema.mock import MockCase, MockIntentOutput, SingleTurnCase
from impl.core.schema.project import ProjectAnalysis, ProjectSpec
from impl.core.schema.trace import RunTrace
from .fixture import register_fixture

TRACE_ID = "trace-fixture-001"
PROJECT_ID = "fixture-project"
CASE_ID = "case-fixture-001"

EXPECTED_CONDITIONS = [
    {"field": "client_age", "op": "between", "value": [30, 40]},
    {"field": "asset_level", "op": "eq", "value": "高净值"},
]


def _reference() -> dict[str, Any]:
    return {"conditions": EXPECTED_CONDITIONS, "query_logic": "AND"}


def _output() -> dict[str, Any]:
    return {"conditions": EXPECTED_CONDITIONS, "query_logic": "AND"}


def business_expectation() -> BusinessExpectation:
    return BusinessExpectation(
        expectation_id="exp-conditions-covered",
        downstream_consumer="client_search",
        user_intent="搜索上海、30到40岁、高净值客户",
        expected_outcome="搜索条件包含 client_age 和 asset_level",
        required_capabilities=["client_age_filter", "asset_level_filter"],
        acceptance_criteria=EXPECTED_CONDITIONS,
        boundary={"within_evaluable_scope": True},
        priority="blocking",
    )


def fulfillment_assessment() -> FulfillmentAssessment:
    return FulfillmentAssessment(
        expectation_id="exp-conditions-covered",
        status="fulfilled",
        score=1.0,
        expected_evidence=EXPECTED_CONDITIONS,
        actual_evidence=EXPECTED_CONDITIONS,
        downstream_impact="下游客户检索条件完整",
        blocking=True,
        confidence=0.95,
    )


def judge_result() -> JudgeResult:
    return JudgeResult(
        trace_id=TRACE_ID,
        project_id=PROJECT_ID,
        business_expectations=[business_expectation()],
        fulfillment_assessments=[fulfillment_assessment()],
        overall_fulfillment={"status": "fulfilled", "blocking_expectations": []},
        expected=_reference(),
        actual=_output(),
        evidence=["所有必要条件均被正确提取。"],
        reasoning_summary="所有必要条件均被正确提取。",
    )


def incorrect_judge_result() -> JudgeResult:
    result = judge_result()
    result.actual = {"conditions": EXPECTED_CONDITIONS[:2]}
    result.overall_fulfillment = {"status": "not_fulfilled", "blocking_expectations": ["exp-conditions-covered"]}
    result.fulfillment_assessments = [
        FulfillmentAssessment(
            expectation_id="exp-conditions-covered",
            status="not_fulfilled",
            score=0.67,
            expected_evidence=EXPECTED_CONDITIONS,
            actual_evidence=EXPECTED_CONDITIONS[:2],
            downstream_impact="资产等级缺失会扩大搜索结果范围",
            blocking=True,
            confidence=0.9,
        )
    ]
    result.missing = [GapItem(kind="missing", error_type="missing_condition", expected={"field": "asset_level", "op": "eq", "value": "高净值"})]
    result.reasoning_summary = "actual output 缺少 asset_level 条件。"
    return result


def expectation_attribution() -> ExpectationAttribution:
    return ExpectationAttribution(
        expectation_id="exp-conditions-covered",
        fulfillment_status="not_fulfilled",
        suspected_locations=["impl/projects/client_search/adapter.py:extract_output"],
        root_cause_hypothesis="extract_output 丢弃了 asset_level 条件。",
        evidence=["raw_response contains asset_level but extracted_output drops it"],
    )


def no_issue_expectation_attribution() -> ExpectationAttribution:
    return ExpectationAttribution(
        expectation_id="exp-conditions-covered",
        fulfillment_status="fulfilled",
        root_cause_hypothesis="业务预期已达成，无根因。",
        evidence=["judge 评估为 fulfilled"],
    )


def boundary_expectation_attribution() -> ExpectationAttribution:
    item = expectation_attribution()
    item.suspected_locations = []
    item.root_cause_hypothesis = "required signal is outside evaluable scope"
    return item


def attribute_result() -> AttributeResult:
    return AttributeResult(
        trace_id=TRACE_ID,
        project_id=PROJECT_ID,
        case_id=CASE_ID,
        expectation_attributions=[expectation_attribution()],
        suspected_locations=["impl/projects/client_search/adapter.py:extract_output"],
        root_cause_hypothesis="extract_output 丢弃了 asset_level 条件。",
        evidence=["raw_response contains asset_level but extracted_output drops it"],
        evidence_strength="medium",
    )


def run_trace() -> RunTrace:
    return RunTrace(
        trace_id=TRACE_ID,
        project_id=PROJECT_ID,
        case_id=CASE_ID,
        mock_intent=MockIntentOutput(user_intent="搜索上海、30到40岁、高净值客户", query="上海 30-40岁 高净值客户"),
        input={"query": "上海 30-40岁 高净值客户"},
        normalized_request={"query": "上海 30-40岁 高净值客户"},
        extracted_output=_output(),
        turn_records=[{
            "turn_index": 1,
            "mock_message": "上海 30-40岁 高净值客户",
            "request": {"query": "上海 30-40岁 高净值客户"},
            "raw_response": None,
            "extracted_output": _output(),
            "call_status": "succeeded",
        }],
        status="ok",
        scenario="schema-fixture-single-turn",
    )


def single_turn_case() -> SingleTurnCase:
    return SingleTurnCase(id=CASE_ID, input={"query": "上海 30-40岁 高净值客户"}, output=_output(), reference=_reference(), scenario="schema-fixture-single-turn", user_intent="搜索上海、30到40岁、高净值客户", metadata={"project_id": PROJECT_ID})


def mock_case() -> MockCase:
    case = single_turn_case()
    return MockCase(id=case.id, project_id=PROJECT_ID, scenario=case.scenario, intent=MockIntentOutput(user_intent=case.user_intent, query=case.input["query"], user_context={}), live_request=case.input, output=case.output, reference=case.reference)


def project_spec() -> ProjectSpec:
    return ProjectSpec(project_id=PROJECT_ID, name="Fixture Project", common={"ready": ["output", "reference"]})


register_fixture(RunTrace, "default", run_trace)
register_fixture(JudgeResult, "default", judge_result)
register_fixture(JudgeResult, "incorrect", incorrect_judge_result)
register_fixture(AttributeResult, "default", attribute_result)
register_fixture(AttributeResult, "no_issue", lambda: AttributeResult(trace_id=TRACE_ID, project_id=PROJECT_ID, case_id=CASE_ID, expectation_attributions=[no_issue_expectation_attribution()]))
register_fixture(AttributeResult, "boundary", lambda: AttributeResult(trace_id=TRACE_ID, project_id=PROJECT_ID, case_id=CASE_ID, expectation_attributions=[boundary_expectation_attribution()]))
register_fixture(ClusterSummary, "default", lambda: ClusterSummary(project_id=PROJECT_ID, clusters=[]))
register_fixture(CheckReport, "default", lambda: CheckReport(passed=True, verification_results=["fixture verified"]))
register_fixture(FrontendViewModel, "default", lambda: FrontendViewModel(project_info={"project_id": PROJECT_ID}))
register_fixture(ProjectSpec, "default", project_spec)
register_fixture(ProjectAnalysis, "default", lambda: ProjectAnalysis(project_id=PROJECT_ID))
register_fixture(SingleTurnCase, "default", single_turn_case)
register_fixture(MockCase, "default", mock_case)
