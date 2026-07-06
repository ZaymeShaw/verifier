from __future__ import annotations

from impl.core.schema.attribute import AttributeResult, ChainNode, ExpectationAttribution
from impl.core.schema.base import GateDecision, SubagentResult, TransitionDecision
from impl.core.schema.batch import BatchRunResult
from impl.core.schema.check import CheckReport
from impl.core.schema.cluster import ClusterSummary
from impl.core.schema.config import LayerConfig, SchemaLayerConfig
from impl.core.schema.evidence import EvidenceRef, ExecutionTraceEvent, ProbeResult
from impl.core.schema.fallback import FallbackDecision
from impl.core.schema.fixture.fixture import register_fixture
from impl.core.schema.frontend import FrontendViewModel
from impl.core.schema.judge import BusinessExpectation, FulfillmentAssessment, GapItem, JudgeResult
from impl.core.schema.live import LiveExecutionResult, LiveMultiTurnResult, LiveMultiTurnState, LiveRequest
from impl.core.schema.mock import MockDataset, MockSpec, MultiTurnCase, MultiTurnInteraction, MultiTurnPolicy, MultiTurnTurnExpectation, SingleTurnCase
from impl.core.schema.project import ProjectAnalysis, ProjectSpec
from impl.core.schema.table import CasePoolTable, ConversationTurn, TraceTableRow
from impl.core.schema.trace import MultiTurnTraceSummary, RunTrace, TraceExecutionContext, TraceStateRecord


PROJECT_ID = "fixture_project"
CASE_ID = "fixture-case-001"
TRACE_ID = "trace-fixture-case-001"
QUERY = "帮我找上海、年龄30到40岁的高净值客户"
EXPECTED_CONDITIONS = [
    {"field": "city", "op": "eq", "value": "上海"},
    {"field": "age", "op": "between", "value": [30, 40]},
    {"field": "asset_level", "op": "eq", "value": "高净值"},
]
ACTUAL_CONDITIONS = list(EXPECTED_CONDITIONS)


def _input() -> dict:
    return {"query": QUERY, "case_id": CASE_ID, "scenario": "schema-fixture-single-turn"}


def _reference() -> dict:
    return {"conditions": list(EXPECTED_CONDITIONS)}


def _output() -> dict:
    return {"conditions": list(ACTUAL_CONDITIONS)}


def _conversation() -> list[dict]:
    return [
        {"turn_index": 1, "role": "user", "content": "帮我找高净值客户", "stage": "initial_intent"},
        {"turn_index": 2, "role": "system", "content": "请补充地域和年龄范围", "stage": "clarification"},
        {"turn_index": 3, "role": "user", "content": "上海，30到40岁", "stage": "completion"},
    ]


def subagent_result() -> SubagentResult:
    return SubagentResult(
        executor_id="fixture-subagent-001",
        executor_type="llm_agent",
        role="judge-reviewer",
        status="succeeded",
        output={"summary": "fixture subagent completed"},
        evidence_refs=[evidence_ref()],
        claims=[{"claim": "conditions are covered", "status": "supported"}],
    )


def gate_decision() -> GateDecision:
    return GateDecision(
        gate_id="gate-fixture-001",
        gate_type="schema_invariant",
        passed=True,
        checked_inputs={"trace_id": TRACE_ID},
        reason="fixture inputs satisfy the invariant",
    )


def transition_decision() -> TransitionDecision:
    return TransitionDecision(
        from_state="live_executed",
        to_state="judge_ready",
        condition="trace.status == ok",
        reason="live result produced extracted output",
        gate_ids=["gate-fixture-001"],
    )


def execution_trace_event() -> ExecutionTraceEvent:
    return ExecutionTraceEvent(stage="adapter.extract_output", status="succeeded", evidence="conditions extracted", outputs=_output())


def evidence_ref() -> EvidenceRef:
    return EvidenceRef(
        ref_id="evidence-fixture-001",
        source="schema_fixture",
        kind="trace_event",
        stage="adapter.extract_output",
        summary="Fixture evidence for extracted output",
        payload=_output(),
    )


def probe_result() -> ProbeResult:
    return ProbeResult(
        probe_id="probe-fixture-001",
        status="succeeded",
        stage="adapter.extract_output",
        evidence=[{"raw_response_has_conditions": True}],
        findings={"missing_condition": False},
    )


def fallback_decision() -> FallbackDecision:
    return FallbackDecision(
        fallback_id="fallback-fixture-001",
        source_stage="judge",
        fallback_type="human_review",
        status="not_used",
        reason="primary fixture path succeeded",
    )


def layer_config() -> LayerConfig:
    return LayerConfig(layer="judge", enabled=True, config={"scenario": "schema-fixture-single-turn"}, notes="fixture layer config")


def schema_layer_config() -> SchemaLayerConfig:
    return SchemaLayerConfig(
        project_id=PROJECT_ID,
        layers=[layer_config(), LayerConfig(layer="attribute", enabled=True, config={"taxonomy": ["implementation_bug", "no_issue"]})],
    )


def project_spec() -> ProjectSpec:
    return ProjectSpec(
        project_id=PROJECT_ID,
        name="Fixture Project",
        description="Project spec fixture for schema tests",
        capabilities=["semantic_parse", "condition_extract"],
        documents={"evaluation": "evaluation.md"},
        api={"endpoint": "/fixture/search", "method": "POST"},
    )


def project_analysis() -> ProjectAnalysis:
    return ProjectAnalysis(
        project_id=PROJECT_ID,
        api={"endpoint": "/fixture/search"},
        application={"boundary": "condition extraction only"},
        capabilities=["semantic_parse", "condition_extract"],
        mock_guidance="Build customer-search requests with explicit conditions.",
        evaluation_guidance="Judge condition semantic coverage.",
        attribution_guidance="Localize loss across request, response, extraction, and judge.",
    )


def mock_spec() -> MockSpec:
    return MockSpec(
        input_modes=["single_turn", "interactive_intent"],
        case_sources=["fixture", "user_written"],
        intent_generation_guidance="Generate customer-search intents with concrete filters.",
        expected_intent_format="goal + required conditions",
    )


def mock_dataset() -> MockDataset:
    return MockDataset(
        dataset_id="dataset-fixture-001",
        name="Schema Fixture Dataset",
        dimension_type="schema_fixture",
        description="One single-turn case and one multi-turn case for fixture consumers.",
        cases=[single_turn_case(), multi_turn_case()],
        case_count=2,
    )


def gap_item() -> GapItem:
    return GapItem(
        kind="missing",
        error_type="missing_condition",
        expected={"field": "asset_level", "op": "eq", "value": "高净值"},
        actual=None,
        evidence_ref="evidence-fixture-001",
    )


def chain_node() -> ChainNode:
    return ChainNode(name="extracted_output", status="failed", evidence=[{"missing": "asset_level"}], reason="condition dropped after raw response")


def trace_state_record() -> TraceStateRecord:
    return TraceStateRecord(
        state_id="judge_ready",
        role="state_machine",
        status="succeeded",
        input_summary={"trace_id": TRACE_ID},
        outputs={"next": "judge"},
        subagent_results=[subagent_result()],
        evidence_refs=[evidence_ref()],
        gate_decisions=[gate_decision()],
        transition_decision=transition_decision(),
    )


def trace_execution_context() -> TraceExecutionContext:
    return TraceExecutionContext(
        project_id=PROJECT_ID,
        input_data=_input(),
        expected_intent="搜索符合地域、年龄、资产条件的客户",
        trace=run_trace(),
        judge_result=judge_result(),
        attribute_result=attribute_result(),
        cluster_summary=cluster_summary(),
        check_report=check_report(),
        state_history=[trace_state_record()],
        metadata={"fixture": True},
    )


def cluster_summary() -> ClusterSummary:
    return ClusterSummary(
        project_id=PROJECT_ID,
        clusters=[{"id": "cluster-missing-condition", "root_cause": "adapter extraction loss", "case_count": 1}],
        representative_cases=[CASE_ID],
        common_root_cause="adapter.extract_output 丢弃条件",
        impact="搜索条件缺失导致结果范围扩大",
        priority="high",
        next_actions=["add extraction regression test"],
    )


def check_report() -> CheckReport:
    return CheckReport(
        passed=True,
        issues=[],
        verification_results=["schema fixture is internally consistent"],
        recommended_fixes=[],
    )


def batch_run_result() -> BatchRunResult:
    return BatchRunResult(
        project_id=PROJECT_ID,
        total=1,
        runs=[{"case_id": CASE_ID, "trace": run_trace(), "judge": judge_result(), "attribute": attribute_result()}],
        cluster=cluster_summary(),
        check=check_report(),
        table=case_pool_table(),
    )


def single_turn_case() -> SingleTurnCase:
    return SingleTurnCase(
        id=CASE_ID,
        input=_input(),
        scenario="schema-fixture-single-turn",
        expected_intent="搜索符合地域、年龄、资产条件的客户",
        reference=_reference(),
        source="fixture",
        status="completed",
    )


def multi_turn_case() -> MultiTurnCase:
    return MultiTurnCase(
        id="fixture-multiturn-001",
        input={"query": "帮我找高净值客户"},
        scenario="schema-fixture-multi-turn",
        expected_intent="通过澄清补齐地域和年龄后搜索客户",
        reference=_reference(),
        source="fixture",
        status="completed",
        user_intent={"goal": "搜索高净值客户", "known_fields": {"asset_level": "高净值"}},
        interaction=MultiTurnInteraction(
            mode="interactive_intent",
            policy=MultiTurnPolicy(max_turns=3, stop_when=["required_fields_collected"]),
            turn_expectations=[
                MultiTurnTurnExpectation(turn=1, stage="clarification", missing_fields=["city", "age"]),
                MultiTurnTurnExpectation(turn=2, stage="completion", required_path_types=["city", "age", "asset_level"]),
            ],
        ),
        mock_agent={"role": "clarify_missing_fields"},
    )


def live_request() -> LiveRequest:
    return LiveRequest(
        project_id=PROJECT_ID,
        case_id=CASE_ID,
        raw_input=_input(),
        normalized_request={"query": QUERY, "limit": 20},
        execution_mode="live_service",
        session_id="fixture-session-001",
    )


def live_execution_result() -> LiveExecutionResult:
    return LiveExecutionResult(
        project_id=PROJECT_ID,
        case_id=CASE_ID,
        session_id="fixture-session-001",
        raw_input=_input(),
        normalized_request={"query": QUERY, "limit": 20},
        call_status="succeeded",
        raw_response={"matched_level": "condition", "conditions": _output()["conditions"]},
        runtime_ms=120,
        extracted_output=_output(),
        output_source="live_service",
        execution_trace=[ExecutionTraceEvent(stage="adapter.extract_output", status="succeeded", outputs=_output())],
        application_boundary={"evaluates": "condition semantic coverage"},
        interaction_mode="single_turn",
    )


def live_multi_turn_state() -> LiveMultiTurnState:
    return LiveMultiTurnState(
        session_id="fixture-session-multi-001",
        turn_index=3,
        transcript=_conversation(),
        accumulated_fields={"city": "上海", "age": [30, 40], "asset_level": "高净值"},
        stop_reason="required_fields_collected",
    )


def live_multi_turn_result() -> LiveMultiTurnResult:
    turn_result = live_execution_result()
    turn_result.session_id = "fixture-session-multi-001"
    turn_result.interaction_mode = "interactive_intent"
    turn_result.multi_turn_state = live_multi_turn_state()
    return LiveMultiTurnResult(
        project_id=PROJECT_ID,
        case_id="fixture-multiturn-001",
        session_id="fixture-session-multi-001",
        turn_results=[turn_result],
        conversation_transcript=_conversation(),
        stop_reason="required_fields_collected",
        final_output=_output(),
    )


def run_trace() -> RunTrace:
    live_result = live_execution_result()
    return RunTrace(
        trace_id=TRACE_ID,
        project_id=PROJECT_ID,
        case_id=CASE_ID,
        input=_input(),
        normalized_request=live_result.normalized_request,
        raw_response=live_result.raw_response,
        extracted_output=live_result.extracted_output,
        live_result=live_result,
        execution_mode=live_result.call_status,
        output_source=live_result.output_source,
        scenario="schema-fixture-single-turn",
        reference_contract=_reference(),
        application_boundary=live_result.application_boundary,
        execution_trace=live_result.execution_trace,
        status="ok",
        interaction_mode="single_turn",
        session_id=live_result.session_id,
    )


def multi_turn_trace_summary() -> MultiTurnTraceSummary:
    trace = run_trace()
    trace.interaction_mode = "interactive_intent"
    trace.session_id = "fixture-session-multi-001"
    trace.conversation_transcript = _conversation()
    trace.conversation_summary = {"turn_count": 3, "stop_reason": "required_fields_collected"}
    trace.multi_turn_input = {"user_intent": {"goal": "搜索高净值客户"}}
    return MultiTurnTraceSummary(
        trace_id="trace-fixture-multiturn-001",
        project_id=PROJECT_ID,
        session_id="fixture-session-multi-001",
        input={"user_intent": {"goal": "搜索高净值客户"}},
        turn_traces=[trace],
        conversation_transcript=_conversation(),
        stop_reason="required_fields_collected",
        final_output=_output(),
    )


def business_expectation() -> BusinessExpectation:
    return BusinessExpectation(
        expectation_id="exp-conditions-covered",
        downstream_consumer="client_search_parser",
        user_intent="搜索上海、30到40岁、高净值客户",
        expected_outcome="输出包含 city、age、asset_level 三个条件",
        required_capabilities=["semantic_parse", "condition_extract"],
        acceptance_criteria=[{"conditions": EXPECTED_CONDITIONS}],
        boundary={"scope": "only extracted conditions"},
        priority="high",
    )


def fulfillment_assessment() -> FulfillmentAssessment:
    return FulfillmentAssessment(
        expectation_id="exp-conditions-covered",
        status="fulfilled",
        score=1.0,
        expected_evidence=EXPECTED_CONDITIONS,
        actual_evidence=ACTUAL_CONDITIONS,
        downstream_impact="下游客户检索条件完整",
        blocking=True,
        confidence=0.95,
    )


def judge_result() -> JudgeResult:
    return JudgeResult(
        trace_id=TRACE_ID,
        project_id=PROJECT_ID,
        verdict="correct",
        score=1.0,
        confidence=0.95,
        expected=_reference(),
        actual=_output(),
        business_expectations=[business_expectation()],
        fulfillment_assessments=[fulfillment_assessment()],
        overall_fulfillment={"status": "fulfilled", "blocking_expectations": []},
        reconstructed_intent="用户要搜索上海、30到40岁、高净值客户",
        judge_basis="actual conditions 覆盖 reference conditions",
        judge_method="condition_semantic_match",
        reasoning_summary="所有必要条件均被正确提取。",
        scenario="schema-fixture-single-turn",
    )


def incorrect_judge_result() -> JudgeResult:
    result = judge_result()
    result.verdict = "incorrect"
    result.score = 0.67
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
        causal_category="implementation_bug",
        earliest_divergence={"stage": "adapter.extract_output", "reason": "asset_level condition dropped"},
        causal_chain=[{"stage": "raw_response", "status": "contains_asset_level"}, {"stage": "extracted_output", "status": "missing_asset_level"}],
        suspected_locations=["impl/projects/client_search/adapter.py:extract_output"],
        improvement_direction=["preserve asset_level condition during extraction"],
        source_evidence=[{"trace_id": TRACE_ID}],
    )


def no_issue_expectation_attribution() -> ExpectationAttribution:
    return ExpectationAttribution(
        expectation_id="exp-conditions-covered",
        fulfillment_status="fulfilled",
        causal_category="no_issue",
        causal_chain=[{"stage": "judge", "status": "fulfilled"}],
        improvement_direction=[],
    )


def boundary_expectation_attribution() -> ExpectationAttribution:
    item = expectation_attribution()
    item.causal_category = "boundary_limitation"
    item.earliest_divergence = {"stage": "judge_boundary", "reason": "required signal is outside evaluable scope"}
    item.suspected_locations = []
    item.improvement_direction = ["clarify evaluation boundary before treating as implementation bug"]
    return item


def attribute_result() -> AttributeResult:
    return AttributeResult(
        trace_id=TRACE_ID,
        project_id=PROJECT_ID,
        case_id=CASE_ID,
        analysis_method="trace_and_local_probe",
        chain_nodes=[ChainNode(name="raw_response", status="verified"), ChainNode(name="extracted_output", status="failed", evidence=["asset_level missing after extraction"])],
        earliest_divergence={"stage": "adapter.extract_output"},
        evidence_coverage={"query": True, "actual": True, "expected": True, "execution_trace": True, "code_or_config": True, "unsupported_claims": []},
        analysis_quality={"passed": True},
        suspected_locations=["impl/projects/client_search/adapter.py:extract_output"],
        root_cause_hypothesis="extract_output 丢弃了 asset_level 条件。",
        verification_steps=["构造包含 asset_level 的 raw_response", "调用 extract_output", "检查 extracted_output.conditions"],
        patch_direction=["补齐 asset_level 映射"],
        expectation_attributions=[expectation_attribution()],
        causal_category="implementation_bug",
        probe_results=[ProbeResult(probe_id="probe-asset-level", status="failed", stage="adapter.extract_output", evidence=["raw_response contains asset_level but extracted_output drops it"])],
        needs_human_review=False,
        scenario="schema-fixture-single-turn",
    )


def conversation_turn() -> ConversationTurn:
    return ConversationTurn(turn_index=1, role="user", content=QUERY, stage="initial_intent", extracted_summary="用户提出客户搜索需求")


def trace_table_row() -> TraceTableRow:
    return TraceTableRow(
        id=CASE_ID,
        input=QUERY,
        scenario="schema-fixture-single-turn",
        output_summary="已识别 city/age/asset_level 三个条件",
        reference_summary="期望 city/age/asset_level 三个条件",
        status="ok",
        execution_mode="live_service",
        output_source="live_service",
        verdict="correct",
        score=1.0,
        fulfillment_status="fulfilled",
        judge_summary={"verdict": "correct", "reason": "条件完整"},
        attribution_summary={"causal_category": "no_issue"},
        needs_human_review=False,
        interaction_mode="single_turn",
        trace_id=TRACE_ID,
    )


def case_pool_table() -> CasePoolTable:
    return CasePoolTable(project_id=PROJECT_ID, rows=[trace_table_row()], total=1, summary={"correct_count": 1, "by_scenario": {"schema-fixture-single-turn": 1}})


def frontend_view_model() -> FrontendViewModel:
    return FrontendViewModel(
        project_info={"project_id": PROJECT_ID, "name": "Fixture Project"},
        run_trace_summary={"trace_id": TRACE_ID, "extracted_output": _output()},
        reference_panel={"reference": _reference()},
        judge_panel={"verdict": "correct", "score": 1.0},
        attribute_panel={"causal_category": "no_issue"},
        table_row=trace_table_row(),
    )


def _register() -> None:
    register_fixture(SubagentResult, "default", subagent_result)
    register_fixture(GateDecision, "default", gate_decision)
    register_fixture(TransitionDecision, "default", transition_decision)
    register_fixture(ExecutionTraceEvent, "default", execution_trace_event)
    register_fixture(EvidenceRef, "default", evidence_ref)
    register_fixture(ProbeResult, "default", probe_result)
    register_fixture(FallbackDecision, "default", fallback_decision)
    register_fixture(LayerConfig, "default", layer_config)
    register_fixture(SchemaLayerConfig, "default", schema_layer_config)
    register_fixture(ProjectSpec, "default", project_spec)
    register_fixture(ProjectAnalysis, "default", project_analysis)
    register_fixture(MockSpec, "default", mock_spec)
    register_fixture(MockDataset, "default", mock_dataset)
    register_fixture(GapItem, "default", gap_item)
    register_fixture(ChainNode, "default", chain_node)
    register_fixture(TraceStateRecord, "default", trace_state_record)
    register_fixture(TraceExecutionContext, "default", trace_execution_context)
    register_fixture(ClusterSummary, "default", cluster_summary)
    register_fixture(CheckReport, "default", check_report)
    register_fixture(BatchRunResult, "default", batch_run_result)
    register_fixture(SingleTurnCase, "default", single_turn_case)
    register_fixture(MultiTurnPolicy, "default", lambda: MultiTurnPolicy(max_turns=3, stop_when=["required_fields_collected"]))
    register_fixture(MultiTurnTurnExpectation, "default", lambda: MultiTurnTurnExpectation(turn=1, stage="clarification", missing_fields=["city", "age"]))
    register_fixture(MultiTurnInteraction, "default", lambda: multi_turn_case().interaction)
    register_fixture(MultiTurnCase, "default", multi_turn_case)
    register_fixture(MultiTurnCase, "multi_turn", multi_turn_case)
    register_fixture(LiveRequest, "default", live_request)
    register_fixture(LiveExecutionResult, "default", live_execution_result)
    register_fixture(LiveMultiTurnState, "default", live_multi_turn_state)
    register_fixture(LiveMultiTurnResult, "default", live_multi_turn_result)
    register_fixture(RunTrace, "default", run_trace)
    register_fixture(MultiTurnTraceSummary, "default", multi_turn_trace_summary)
    register_fixture(BusinessExpectation, "default", business_expectation)
    register_fixture(FulfillmentAssessment, "default", fulfillment_assessment)
    register_fixture(JudgeResult, "default", judge_result)
    register_fixture(JudgeResult, "incorrect", incorrect_judge_result)
    register_fixture(ExpectationAttribution, "default", expectation_attribution)
    register_fixture(ExpectationAttribution, "implementation_bug", expectation_attribution)
    register_fixture(ExpectationAttribution, "no_issue", no_issue_expectation_attribution)
    register_fixture(ExpectationAttribution, "boundary_limitation", boundary_expectation_attribution)
    register_fixture(AttributeResult, "default", attribute_result)
    register_fixture(ConversationTurn, "default", conversation_turn)
    register_fixture(TraceTableRow, "default", trace_table_row)
    register_fixture(CasePoolTable, "default", case_pool_table)
    register_fixture(FrontendViewModel, "default", frontend_view_model)


_register()
