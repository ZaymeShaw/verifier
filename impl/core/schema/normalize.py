from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional

from .attribute import AttributeResult, ExpectationAttribution
from .check import CheckReport
from .cluster import ClusterSummary
from .fallback import FallbackDecision
from .evidence import EvidenceRef, ExecutionTraceEvent, ProbeResult
from .frontend import FrontendViewModel
from .judge import BusinessExpectation, FulfillmentAssessment, GapItem, JudgeResult
from .live import LiveRequest, LiveMultiTurnState
from .mock import MockDataset, MockIntentOutput, MockSpec, MultiTurnCase, MultiTurnInteraction, MultiTurnPolicy, MultiTurnTurnExpectation, SingleTurnCase
from .table import CasePoolTable, ConversationTurn, TraceTableRow
from .trace import MultiTurnTraceSummary, RunTrace, TraceExecutionContext


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return {}


def _as_list(value: Any) -> list[Any]:
    return list(value or []) if isinstance(value, list) else []


CALL_STATUSES = {"succeeded", "failed", "skipped"}
TRACE_STATUSES = {"ok", "error", "skipped"}
VERDICTS = {"correct", "incorrect", "uncertain", "not_evaluable"}
FULFILLMENT_STATUSES = {"fulfilled", "not_fulfilled", "not_evaluable"}
INTERACTION_MODES = {"single_turn", "static_turns", "interactive_intent"}
EVENT_STATUSES = {"succeeded", "failed", "skipped", "not_verified", "suspicious"}
CHAIN_STATUSES = {"verified", "failed", "not_verified", "partial", "suspicious"}
FALLBACK_STATUSES = {"used", "not_used", "failed", "pending", "error", "needs_human_review"}


def _one_of(value: Any, allowed: set[str], default: str, aliases: Optional[Dict[str, str]] = None) -> str:
    raw = str(value or "").strip()
    normalized = (aliases or {}).get(raw, raw)
    return normalized if normalized in allowed else default


def _normalize_call_status(value: Any) -> str:
    return _one_of(value, CALL_STATUSES, "succeeded", {"ok": "succeeded", "success": "succeeded", "error": "failed"})


def _normalize_trace_status(value: Any) -> str:
    return _one_of(value, TRACE_STATUSES, "ok", {"succeeded": "ok", "success": "ok", "failed": "error"})


def _normalize_verdict(value: Any) -> str:
    return _one_of(value, VERDICTS, "uncertain", {"fulfilled": "correct", "failed": "incorrect", "error": "not_evaluable", "partial": "incorrect", "partially_correct": "incorrect"})


def _normalize_fulfillment_status(value: Any) -> str:
    return _one_of(value, FULFILLMENT_STATUSES, "not_evaluable", {"correct": "fulfilled", "incorrect": "not_fulfilled", "failed": "not_fulfilled", "uncertain": "not_evaluable", "partial": "not_fulfilled", "partially_fulfilled": "not_fulfilled", "contested": "not_evaluable"})


def _normalize_interaction_mode(value: Any) -> str:
    return _one_of(value, INTERACTION_MODES, "single_turn", {"multi_turn": "interactive_intent"})


def _normalize_event_status(value: Any) -> str:
    return _one_of(value, EVENT_STATUSES, "not_verified", {"ok": "succeeded", "success": "succeeded", "error": "failed"})


def _normalize_chain_status(value: Any) -> str:
    """向前兼容：ChainNode 已删除，保留函数仅为兼容 normalize_chain_node 调用方。"""
    return _one_of(value, CHAIN_STATUSES, "not_verified", {"succeeded": "verified", "ok": "verified", "error": "failed"})


def _normalize_fallback_status(value: Any) -> str:
    return _one_of(value, FALLBACK_STATUSES, "pending", {"succeeded": "used", "success": "used", "skipped": "not_used"})


def normalize_execution_trace_event(value: Any) -> Optional[ExecutionTraceEvent]:
    if value is None:
        return None
    if isinstance(value, ExecutionTraceEvent):
        value.status = _normalize_event_status(value.status)
        return value
    data = _as_dict(value)
    if not data:
        return None
    return ExecutionTraceEvent(
        stage=str(data.get("stage") or data.get("name") or ""),
        status=_normalize_event_status(data.get("status")),
        evidence=data.get("evidence"),
        timestamp=str(data.get("timestamp") or data.get("time") or ""),
        inputs=data.get("inputs") if isinstance(data.get("inputs"), dict) else {},
        outputs=data.get("outputs") if isinstance(data.get("outputs"), dict) else {},
        error=str(data.get("error") or ""),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {key: item for key, item in data.items() if key not in {"stage", "name", "status", "evidence", "timestamp", "time", "inputs", "outputs", "error"}},
    )


def normalize_execution_trace_events(values: Iterable[Any]) -> List[ExecutionTraceEvent]:
    return [item for item in (normalize_execution_trace_event(value) for value in values or []) if item is not None]


def normalize_evidence_ref(value: Any) -> Optional[EvidenceRef]:
    if value is None or isinstance(value, EvidenceRef):
        return value
    data = _as_dict(value)
    if not data:
        return None
    return EvidenceRef(
        ref_id=str(data.get("ref_id") or data.get("id") or data.get("key") or ""),
        source=str(data.get("source") or ""),
        kind=str(data.get("kind") or data.get("type") or ""),
        stage=str(data.get("stage") or ""),
        summary=str(data.get("summary") or data.get("description") or ""),
        location=str(data.get("location") or data.get("path") or ""),
        payload=data.get("payload") if "payload" in data else data.get("evidence"),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {key: item for key, item in data.items() if key not in {"ref_id", "id", "key", "source", "kind", "type", "stage", "summary", "description", "location", "path", "payload", "evidence"}},
    )


def normalize_evidence_refs(values: Iterable[Any]) -> List[EvidenceRef]:
    return [item for item in (normalize_evidence_ref(value) for value in values or []) if item is not None]


def normalize_probe_result(value: Any) -> Optional[ProbeResult]:
    if value is None:
        return None
    if isinstance(value, ProbeResult):
        value.status = _normalize_event_status(value.status)
        return value
    data = _as_dict(value)
    if not data:
        return None
    return ProbeResult(
        probe_id=str(data.get("probe_id") or data.get("id") or ""),
        status=_normalize_event_status(data.get("status")),
        stage=str(data.get("stage") or ""),
        evidence=_as_list(data.get("evidence")),
        findings=data.get("findings") if isinstance(data.get("findings"), dict) else {},
        error=str(data.get("error") or ""),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {key: item for key, item in data.items() if key not in {"probe_id", "id", "status", "stage", "evidence", "findings", "error"}},
    )


def normalize_probe_results(values: Iterable[Any]) -> List[ProbeResult]:
    return [item for item in (normalize_probe_result(value) for value in values or []) if item is not None]


def normalize_fallback_decision(value: Any) -> Optional[FallbackDecision]:
    if value is None:
        return None
    if isinstance(value, FallbackDecision):
        value.status = _normalize_fallback_status(value.status)
        return value
    data = _as_dict(value)
    if not data:
        return None
    return FallbackDecision(
        fallback_id=str(data.get("fallback_id") or ""),
        source_stage=str(data.get("source_stage") or ""),
        fallback_type=str(data.get("fallback_type") or ""),
        status=_normalize_fallback_status(data.get("status")),
        reason=str(data.get("reason") or ""),
        missing_evidence=_as_list(data.get("missing_evidence")),
        recoverable=bool(data.get("recoverable")),
        needs_human_review=bool(data.get("needs_human_review")),
        quality_flags=_as_list(data.get("quality_flags")),
        evidence_refs=_as_list(data.get("evidence_refs")),
        failed_gate_ids=_as_list(data.get("failed_gate_ids")),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    )


def normalize_fallback_decisions(values: Iterable[Any]) -> List[FallbackDecision]:
    return [item for item in (normalize_fallback_decision(value) for value in values or []) if item is not None]


def normalize_conversation_turn(value: Any) -> Optional[ConversationTurn]:
    if value is None or isinstance(value, ConversationTurn):
        return value
    data = _as_dict(value)
    if not data:
        return None
    return ConversationTurn(
        turn_index=int(data.get("turn_index") or data.get("turn") or 0),
        role=str(data.get("role") or ""),
        content=str(data.get("content") or ""),
        stage=str(data.get("stage") or ""),
        extracted_summary=str(data.get("extracted_summary") or ""),
        call_status=str(data.get("call_status") or ""),
        runtime_ms=int(data.get("runtime_ms") or 0),
        error=str(data.get("error") or ""),
    )


def normalize_conversation_turns(values: Iterable[Any]) -> List[ConversationTurn]:
    return [item for item in (normalize_conversation_turn(value) for value in values or []) if item is not None]


def normalize_trace_table_row(value: Any) -> Optional[TraceTableRow]:
    if value is None or isinstance(value, TraceTableRow):
        return value
    data = _as_dict(value)
    if not data:
        return None
    return TraceTableRow(
        id=str(data.get("id") or ""),
        input=str(data.get("input") or ""),
        scenario=str(data.get("scenario") or ""),
        output_summary=str(data.get("output_summary") or ""),
        reference_summary=str(data.get("reference_summary") or ""),
        status=_normalize_trace_status(data.get("status")),
        execution_mode=str(data.get("execution_mode") or ""),
        output_source=str(data.get("output_source") or ""),
        score=data.get("score"),
        fulfillment_status=_normalize_fulfillment_status(data.get("fulfillment_status")),
        judge_summary=data.get("judge_summary") if isinstance(data.get("judge_summary"), dict) else {},
        attribution_summary=data.get("attribution_summary") if isinstance(data.get("attribution_summary"), dict) else {},
        check_summary=data.get("check_summary") if isinstance(data.get("check_summary"), dict) else {},
        fallback_summary=data.get("fallback_summary") if isinstance(data.get("fallback_summary"), dict) else {},
        needs_human_review=bool(data.get("needs_human_review")),
        quality_flags=_as_list(data.get("quality_flags")),
        check_passed=data.get("check_passed"),
        issue_count=int(data.get("issue_count") or 0),
        fallback_count=int(data.get("fallback_count") or 0),
        divergence_stage=str(data.get("divergence_stage") or ""),
        root_cause_summary=str(data.get("root_cause_summary") or ""),
        created_at=str(data.get("created_at") or ""),
        stop_reason=str(data.get("stop_reason") or ""),
        interaction_mode=_normalize_interaction_mode(data.get("interaction_mode")),
        conversation_summary=data.get("conversation_summary") if isinstance(data.get("conversation_summary"), dict) else {},
        conversation_detail=normalize_conversation_turns(data.get("conversation_detail")) if isinstance(data.get("conversation_detail"), list) else None,
        trace_id=str(data.get("trace_id") or ""),
    )


def normalize_trace_table_rows(values: Iterable[Any]) -> List[TraceTableRow]:
    return [item for item in (normalize_trace_table_row(value) for value in values or []) if item is not None]


def normalize_case_pool_table(value: Any) -> Optional[CasePoolTable]:
    if value is None or isinstance(value, CasePoolTable):
        return value
    data = _as_dict(value)
    if not data:
        return None
    rows = normalize_trace_table_rows(data.get("rows"))
    return CasePoolTable(
        project_id=str(data.get("project_id") or ""),
        rows=rows,
        total=int(data.get("total") or len(rows)),
        summary=data.get("summary") if isinstance(data.get("summary"), dict) else {},
    )


def normalize_mock_case(value: Any) -> Optional[SingleTurnCase | MultiTurnCase]:
    if value is None or isinstance(value, (SingleTurnCase, MultiTurnCase)):
        return value
    data = _as_dict(value)
    if not data:
        return None

    # MockCase 新格式：包含 intent + live_request 字段
    # 三层分离：标识 — intent — live_request。input 从 live_request 取。
    if "intent" in data and "live_request" in data:
        intent_data = data.get("intent") if isinstance(data.get("intent"), dict) else {}
        live_request = data.get("live_request") if isinstance(data.get("live_request"), dict) else {}
        base = {
            "id": str(data.get("id") or data.get("case_id") or ""),
            "input": dict(live_request),
            "output": data.get("output") if isinstance(data.get("output"), dict) else None,
            "scenario": str(data.get("scenario") or intent_data.get("scenario") or ""),
            "user_intent": str(intent_data.get("user_intent") or ""),
            "reference": data.get("reference") if isinstance(data.get("reference"), dict) else None,
            "source": str(data.get("source") or "mock_case_api"),
            "status": str(data.get("status") or "pending"),
            "metadata": {
                "project_id": str(data.get("project_id") or ""),
                "source": "mock_case_api",
                **(data.get("metadata") if isinstance(data.get("metadata"), dict) else {}),
            },
        }
        user_context = intent_data.get("user_context")
        if isinstance(user_context, dict) and user_context:
            base["metadata"]["user_context"] = dict(user_context)
        _check_normalized_case_with_live_schema(data)
        return SingleTurnCase(**base)

    input_data = data.get("input") if isinstance(data.get("input"), dict) else {key: item for key, item in data.items() if key not in {"id", "case_id", "source", "status", "scenario", "reference", "metadata", "interaction", "mock_agent", "intent_plan", "user_intent"}}
    base = {
        "id": str(data.get("id") or data.get("case_id") or ""),
        "input": input_data,
        "output": data.get("output") if isinstance(data.get("output"), dict) else None,
        "scenario": str(data.get("scenario") or ""),
        "user_intent": str(data.get("user_intent") or ""),
        "reference": data.get("reference") if isinstance(data.get("reference"), dict) else None,
        "source": str(data.get("source") or "user_written"),
        "status": str(data.get("status") or "pending"),
        "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    }
    interaction = data.get("interaction") if isinstance(data.get("interaction"), dict) else {}
    if interaction or isinstance(data.get("turns"), list) or isinstance(data.get("intent_plan"), dict):
        policy_data = interaction.get("policy") if isinstance(interaction.get("policy"), dict) else {}
        policy = MultiTurnPolicy(max_turns=int(policy_data.get("max_turns") or 5), stop_when=_as_list(policy_data.get("stop_when")))
        expectations = [
            MultiTurnTurnExpectation(
                turn=int(item.get("turn") or index + 1),
                stage=str(item.get("stage") or ""),
                missing_fields=_as_list(item.get("missing_fields")),
                required_path_types=_as_list(item.get("required_path_types")),
            )
            for index, item in enumerate(_as_list(interaction.get("turn_expectations")))
            if isinstance(item, dict)
        ]
        # 挂载 live_schema 校验
        _check_normalized_case_with_live_schema(data)
        return MultiTurnCase(
            **base,
            intent_plan=data.get("intent_plan") if isinstance(data.get("intent_plan"), dict) else input_data,
            interaction=MultiTurnInteraction(mode=str(interaction.get("mode") or ("static_turns" if isinstance(data.get("turns"), list) else "interactive_intent")), policy=policy, turn_expectations=expectations),
            mock_agent=data.get("mock_agent") if isinstance(data.get("mock_agent"), dict) else {},
        )
    # 挂载 live_schema 校验
    _check_normalized_case_with_live_schema(data)
    return SingleTurnCase(**base)


def _check_normalized_case_with_live_schema(data: Dict[str, Any]) -> None:
    """normalize_mock_case 解析时校验 case 是否符合 live_schema。

    校验不阻断。委托给 LiveSchemaCheck（统一从 SchemaValidator 取）。
    """
    try:
        from impl.core.mock_agent import load_live_schema
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        pid = meta.get("project_id")
        if not pid:
            cid = str(data.get("id") or data.get("case_id") or "")
            prefix = "mock-agent-"
            if cid.startswith(prefix):
                rest = cid[len(prefix):]
                idx = rest.rfind("-")
                if idx > 0:
                    pid = rest[:idx]
        if not pid:
            return
        ls = load_live_schema(pid)
        if ls is not None and hasattr(ls, "check"):
            ls.check.case(data)
    except Exception:
        pass


def normalize_mock_dataset(value: Any) -> Optional[MockDataset]:
    if value is None or isinstance(value, MockDataset):
        return value
    data = _as_dict(value)
    if not data:
        return None
    cases = [case for case in (normalize_mock_case(item) for item in _as_list(data.get("cases"))) if case is not None]
    return MockDataset(
        dataset_id=str(data.get("dataset_id") or data.get("id") or ""),
        name=str(data.get("name") or ""),
        dimension_type=str(data.get("dimension_type") or data.get("type") or ""),
        description=str(data.get("description") or ""),
        cases=cases,
        case_count=int(data.get("case_count") or len(cases)),
    )


def normalize_mock_spec(value: Any) -> Optional[MockSpec]:
    if value is None or isinstance(value, MockSpec):
        return value
    data = _as_dict(value)
    if not data:
        return None
    return MockSpec(
        input_modes=_as_list(data.get("input_modes")),
        case_sources=_as_list(data.get("case_sources")),
        intent_generation_guidance=str(data.get("intent_generation_guidance") or data.get("mock_guidance") or ""),
        user_intent_format=str(data.get("user_intent_format") or ""),
    )


def normalize_business_expectation(value: Any) -> Optional[BusinessExpectation]:
    if value is None or isinstance(value, BusinessExpectation):
        return value
    data = _as_dict(value)
    if not data:
        return None
    return BusinessExpectation(
        expectation_id=str(data.get("expectation_id") or data.get("id") or ""),
        downstream_consumer=str(data.get("downstream_consumer") or ""),
        user_intent=str(data.get("user_intent") or ""),
        expected_outcome=str(data.get("expected_outcome") or data.get("expectation") or ""),
        required_capabilities=_as_list(data.get("required_capabilities")),
        acceptance_criteria=_as_list(data.get("acceptance_criteria")),
        boundary=data.get("boundary") if isinstance(data.get("boundary"), dict) else {},
        priority=str(data.get("priority") or "normal"),
        evidence_refs=_as_list(data.get("evidence_refs")),
    )


def normalize_fulfillment_assessment(value: Any) -> Optional[FulfillmentAssessment]:
    if value is None:
        return None
    if isinstance(value, FulfillmentAssessment):
        value.status = _normalize_fulfillment_status(value.status)
        return value
    data = _as_dict(value)
    if not data:
        return None
    return FulfillmentAssessment(
        expectation_id=str(data.get("expectation_id") or data.get("id") or ""),
        status=_normalize_fulfillment_status(data.get("status")),
        score=data.get("score"),
        expected_evidence=_as_list(data.get("expected_evidence")),
        actual_evidence=_as_list(data.get("actual_evidence")),
        downstream_impact=str(data.get("downstream_impact") or ""),
        blocking=bool(data.get("blocking")),
        confidence=data.get("confidence"),
        evidence_refs=_as_list(data.get("evidence_refs")),
    )


def normalize_gap_item(value: Any, kind: str = "") -> GapItem:
    if isinstance(value, GapItem):
        return value
    data = _as_dict(value)
    if data:
        return GapItem(kind=str(data.get("kind") or kind), error_type=str(data.get("error_type") or data.get("status") or ""), expected=data.get("expected"), actual=data.get("actual"), evidence_ref=str(data.get("evidence_ref") or ""), raw=data.get("raw", value), incomplete=bool(data.get("incomplete")))
    return GapItem(kind=kind, raw=value)


def normalize_expectation_attribution(value: Any) -> Optional[ExpectationAttribution]:
    if value is None:
        return None
    if isinstance(value, ExpectationAttribution):
        value.fulfillment_status = _normalize_fulfillment_status(value.fulfillment_status)
        return value
    data = _as_dict(value)
    if not data:
        return None
    return ExpectationAttribution(
        expectation_id=str(data.get("expectation_id") or data.get("id") or ""),
        fulfillment_status=_normalize_fulfillment_status(data.get("fulfillment_status") or data.get("status")),
        suspected_locations=_as_list(data.get("suspected_locations")),
        root_cause_hypothesis=str(data.get("root_cause_hypothesis") or ""),
        evidence=_as_list(data.get("evidence")),
    )


def normalize_chain_node(value: Any) -> Any:
    """向前兼容：ChainNode 已从通用 schema 删除，始终返回空字典。"""
    return {} if isinstance(value, dict) else value


def normalize_live_request(value: Any) -> Optional[LiveRequest]:
    if value is None or isinstance(value, LiveRequest):
        return value
    data = _as_dict(value)
    if not data:
        return None
    return LiveRequest(
        project_id=str(data.get("project_id") or ""),
        raw_input=data.get("raw_input") if isinstance(data.get("raw_input"), dict) else {},
        case_id=str(data.get("case_id") or ""),
        turns=list(data.get("turns") or []),
        normalized_request=data.get("normalized_request") if isinstance(data.get("normalized_request"), dict) else {},
        execution_mode=str(data.get("execution_mode") or "live_service"),
        session_id=str(data.get("session_id") or ""),
        timestamp=str(data.get("timestamp") or LiveRequest(project_id="", raw_input={}).timestamp),
    )


def normalize_live_multi_turn_state(value: Any) -> Optional[LiveMultiTurnState]:
    if value is None or isinstance(value, LiveMultiTurnState):
        return value
    data = _as_dict(value)
    if not data:
        return None
    return LiveMultiTurnState(
        session_id=str(data.get("session_id") or ""),
        turn_index=int(data.get("turn_index") or 0),
        transcript=_as_list(data.get("transcript")),
        accumulated_fields=data.get("accumulated_fields") if isinstance(data.get("accumulated_fields"), dict) else {},
        missing_fields=_as_list(data.get("missing_fields")),
        stop_reason=str(data.get("stop_reason") or ""),
        turn_traces=_as_list(data.get("turn_traces")),
        conversation_summary=data.get("conversation_summary") if isinstance(data.get("conversation_summary"), dict) else {},
        final_stage=str(data.get("final_stage") or ""),
    )


def normalize_run_trace(value: Any) -> Optional[RunTrace]:
    if value is None:
        return None
    if isinstance(value, RunTrace):
        value.status = _normalize_trace_status(value.status)
        value.interaction_mode = _normalize_interaction_mode(value.interaction_mode)
        value.evidence_refs = normalize_evidence_refs(value.evidence_refs)
        value.execution_trace = normalize_execution_trace_events(value.execution_trace)
        value.fallbacks = normalize_fallback_decisions(value.fallbacks)
        if not value.reference_contract:
            input_data = value.input if isinstance(value.input, dict) else {}
            request_data = value.normalized_request if isinstance(value.normalized_request, dict) else {}
            value.reference_contract = input_data.get("reference") if isinstance(input_data.get("reference"), dict) else request_data.get("reference") if isinstance(request_data.get("reference"), dict) else {}
        if not value.scenario:
            input_data = value.input if isinstance(value.input, dict) else {}
            request_data = value.normalized_request if isinstance(value.normalized_request, dict) else {}
            value.scenario = str(input_data.get("scenario") or request_data.get("scenario") or "")
        if not value.conversation_summary:
            multi_turn_input = value.multi_turn_input if isinstance(value.multi_turn_input, dict) else {}
            value.conversation_summary = multi_turn_input.get("conversation_summary") if isinstance(multi_turn_input.get("conversation_summary"), dict) else value.extracted_output.get("conversation_summary") if isinstance(value.extracted_output, dict) and isinstance(value.extracted_output.get("conversation_summary"), dict) else {}
        value.turn_records = list(value.turn_records or [])
        if value.final_output_turn is not None:
            value.final_output_turn = int(value.final_output_turn)
        return value
    data = _as_dict(value)
    if not data:
        return None
    input_data = data.get("input") if isinstance(data.get("input"), dict) else {}
    request_data = data.get("normalized_request") if isinstance(data.get("normalized_request"), dict) else {}
    project_fields = data.get("project_fields") if isinstance(data.get("project_fields"), dict) else {}
    reference_contract = data.get("reference_contract") if isinstance(data.get("reference_contract"), dict) else input_data.get("reference") if isinstance(input_data.get("reference"), dict) else request_data.get("reference") if isinstance(request_data.get("reference"), dict) else {}
    application_boundary = data.get("application_boundary") if isinstance(data.get("application_boundary"), dict) else {}
    multi_turn_input = data.get("multi_turn_input") if isinstance(data.get("multi_turn_input"), dict) else None
    conversation_summary = data.get("conversation_summary") if isinstance(data.get("conversation_summary"), dict) else multi_turn_input.get("conversation_summary") if isinstance(multi_turn_input, dict) and isinstance(multi_turn_input.get("conversation_summary"), dict) else data.get("extracted_output", {}).get("conversation_summary") if isinstance(data.get("extracted_output"), dict) and isinstance(data.get("extracted_output", {}).get("conversation_summary"), dict) else {}
    mock_intent_data = data.get("mock_intent") if isinstance(data.get("mock_intent"), dict) else {}
    mock_intent = MockIntentOutput(
        user_intent=str(mock_intent_data.get("user_intent") or ""),
        query=str(mock_intent_data.get("query") or ""),
        user_context=dict(mock_intent_data.get("user_context") or {}),
        scenario=str(mock_intent_data.get("scenario") or ""),
        live_request=dict(mock_intent_data.get("live_request")) if isinstance(mock_intent_data.get("live_request"), dict) else None,
    ) if mock_intent_data else None
    return RunTrace(
        trace_id=str(data.get("trace_id") or ""),
        project_id=str(data.get("project_id") or ""),
        case_id=str(data.get("case_id") or input_data.get("case_id") or ""),
        mock_intent=mock_intent,
        input=input_data,
        normalized_request=request_data,
        raw_response=data.get("raw_response"),
        extracted_output=data.get("extracted_output") if isinstance(data.get("extracted_output"), dict) else {},
        execution_mode=str(data.get("execution_mode") or request_data.get("execution_mode") or ""),
        output_source=str(data.get("output_source") or ""),
        scenario=str(data.get("scenario") or input_data.get("scenario") or request_data.get("scenario") or ""),
        reference_contract=dict(reference_contract or {}),
        application_boundary=dict(application_boundary or {}),
        project_fields=project_fields,
        runtime_logs=list(data.get("runtime_logs") or []),
        evidence_refs=normalize_evidence_refs(data.get("evidence_refs")),
        execution_trace=normalize_execution_trace_events(data.get("execution_trace")),
        status=_normalize_trace_status(data.get("status")),
        error=data.get("error"),
        created_at=data.get("created_at") or RunTrace(trace_id="", project_id="", input={}, normalized_request={}).created_at,
        state_history=list(data.get("state_history") or []),
        gate_decisions=list(data.get("gate_decisions") or []),
        transition_decisions=list(data.get("transition_decisions") or []),
        stop_reason=str(data.get("stop_reason") or ""),
        interaction_mode=_normalize_interaction_mode(data.get("interaction_mode")),
        session_id=str(data.get("session_id") or ""),
        turn_index=int(data.get("turn_index") or 0),
        conversation_transcript=list(data.get("conversation_transcript") or []),
        conversation_summary=dict(conversation_summary or {}),
        turn_records=list(data.get("turn_records") or []),
        final_output_turn=int(data.get("final_output_turn")) if data.get("final_output_turn") is not None else None,
        completion_status=str(data.get("completion_status") or ""),
        multi_turn_input=multi_turn_input,
        fallbacks=normalize_fallback_decisions(data.get("fallbacks")),
        ready=list(data.get("ready") or []),
    )


def normalize_multi_turn_trace_summary(value: Any) -> Optional[MultiTurnTraceSummary]:
    if value is None or isinstance(value, MultiTurnTraceSummary):
        return value
    data = _as_dict(value)
    if not data:
        return None
    turn_traces = [item for item in (normalize_run_trace(item) for item in _as_list(data.get("turn_traces"))) if item is not None]
    return MultiTurnTraceSummary(
        trace_id=str(data.get("trace_id") or ""),
        project_id=str(data.get("project_id") or ""),
        session_id=str(data.get("session_id") or ""),
        input=data.get("input") if isinstance(data.get("input"), dict) else {},
        turn_traces=turn_traces,
        conversation_transcript=_as_list(data.get("conversation_transcript")),
        stop_reason=str(data.get("stop_reason") or ""),
        final_output=data.get("final_output") if isinstance(data.get("final_output"), dict) else {},
    )


def normalize_judge_result(value: Any) -> Optional[JudgeResult]:
    if value is None:
        return None
    if isinstance(value, JudgeResult):
        data = asdict(value)
    else:
        data = _as_dict(value)
    if not data:
        return None
    data = dict(data)
    for legacy_key in ("primary_assessment", "condition_assessments", "intent_decomposition", "contrast_assessments", "score_details",
                       "verdict", "score", "confidence", "probability", "intent_model", "consumer_contract",
                       "reconstructed_intent", "judge_basis", "judge_method", "semantic_equivalence_checks",
                       "reference_generation_basis", "verdict_derivation", "boundary_decision", "evaluation_boundary",
                       "needs_human_review", "quality_flags", "scenario", "raw_model_output", "llm_output",
                       "overrides", "gate_decisions", "transition_decisions", "fallbacks"):
        data.pop(legacy_key, None)
    overall = data.get("overall_fulfillment")
    if isinstance(overall, dict) and "status" in overall:
        overall = dict(overall)
        overall["status"] = _normalize_fulfillment_status(overall.get("status"))
        data["overall_fulfillment"] = overall
    data["business_expectations"] = [item for item in (normalize_business_expectation(item) for item in _as_list(data.get("business_expectations"))) if item is not None]
    data["fulfillment_assessments"] = [item for item in (normalize_fulfillment_assessment(item) for item in _as_list(data.get("fulfillment_assessments"))) if item is not None]
    data["wrong"] = [normalize_gap_item(item, "wrong") for item in _as_list(data.get("wrong"))]
    data["missing"] = [normalize_gap_item(item, "missing") for item in _as_list(data.get("missing"))]
    data["extra"] = [normalize_gap_item(item, "extra") for item in _as_list(data.get("extra"))]
    if not data.get("summary"):
        data["summary"] = _as_dict(data.get("summary"))
    return JudgeResult(**data)


def normalize_attribute_result(value: Any) -> Optional[AttributeResult]:
    if value is None:
        return None
    if isinstance(value, AttributeResult):
        value.expectation_attributions = [item for item in (normalize_expectation_attribution(item) for item in _as_list(value.expectation_attributions)) if item is not None]
        return value
    data = _as_dict(value)
    if not data:
        return None
    data = dict(data)
    for legacy_key in ("causal_category", "chain_nodes", "earliest_divergence", "evidence_coverage",
                       "analysis_quality", "incomplete_reason", "verification_steps", "patch_direction",
                       "needs_human_review", "scenario", "quality_flags", "raw_model_output", "llm_output",
                       "tool_call_log", "analysis_method", "probe_results", "gate_decisions",
                       "transition_decisions", "fallbacks"):
        data.pop(legacy_key, None)
    data["expectation_attributions"] = [item for item in (normalize_expectation_attribution(item) for item in _as_list(data.get("expectation_attributions"))) if item is not None]
    if not data.get("summary"):
        data["summary"] = _as_dict(data.get("summary"))
    return AttributeResult(**data)


def normalize_cluster_summary(value: Any) -> Optional[ClusterSummary]:
    if value is None or isinstance(value, ClusterSummary):
        return value
    data = _as_dict(value)
    return ClusterSummary(**data) if data else None


def normalize_check_report(value: Any) -> Optional[CheckReport]:
    if value is None:
        return None
    if isinstance(value, CheckReport):
        data = asdict(value)
    else:
        data = _as_dict(value)
    if not data:
        return None
    data = dict(data)
    data["fallbacks"] = normalize_fallback_decisions(data.get("fallbacks"))
    return CheckReport(**data)


def normalize_frontend_view(value: Any) -> Optional[FrontendViewModel]:
    if value is None:
        return None
    if isinstance(value, FrontendViewModel):
        value.table_row = normalize_trace_table_row(value.table_row)
        return value
    data = _as_dict(value)
    if not data:
        return None
    data = dict(data)
    data["table_row"] = normalize_trace_table_row(data.get("table_row"))
    return FrontendViewModel(**data)


def normalize_trace_execution_context(value: Any) -> Optional[TraceExecutionContext]:
    if value is None or isinstance(value, TraceExecutionContext):
        return value
    data = _as_dict(value)
    if not data:
        return None
    return TraceExecutionContext(
        project_id=str(data.get("project_id") or ""),
        input_data=data.get("input_data") if isinstance(data.get("input_data"), dict) else {},
        user_intent=data.get("user_intent"),
        trace=normalize_run_trace(data.get("trace")),
        judge_result=normalize_judge_result(data.get("judge_result")),
        attribute_result=normalize_attribute_result(data.get("attribute_result")),
        cluster_summary=normalize_cluster_summary(data.get("cluster_summary")),
        check_report=normalize_check_report(data.get("check_report")),
        state_history=list(data.get("state_history") or []),
        executor_outputs=data.get("executor_outputs") if isinstance(data.get("executor_outputs"), dict) else {},
        stop_reason=str(data.get("stop_reason") or ""),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    )


def normalize_attribute_results(values: Iterable[Any]) -> List[AttributeResult]:
    return [item for item in (normalize_attribute_result(value) for value in values or []) if item is not None]
