from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

# Occam-role annotations for schema fields.
# Updated for spec/info-volume.md slimmed schemas.

SCHEMA_FIELD_ROLES = {
    "RunTrace": {
        "canonical": [
            "trace_id", "project_id", "case_id", "status", "error",
            "state_history", "gate_decisions", "transition_decisions", "evidence_refs",
            "fallbacks", "scenario", "interaction_mode", "session_id", "created_at",
            "turn_records", "final_output_turn", "completion_status", "ready", "mock_intent",
        ],
        "derived_alias": [
            "input", "normalized_request", "raw_response", "extracted_output",
            "execution_mode", "output_source", "application_boundary", "project_fields",
            "execution_trace", "runtime_logs", "stop_reason", "conversation_transcript",
            "conversation_summary", "turn_index", "reference_contract",
        ],
        "legacy_alias": ["multi_turn_input"],
    },
    "MultiTurnTraceSummary": {
        "legacy_alias": ["trace_id", "project_id", "session_id", "input", "turn_traces",
                        "conversation_transcript", "stop_reason", "final_output"],
    },
    "JudgeResult": {
        "canonical": ["trace_id", "project_id", "business_expectations", "fulfillment_assessments", "overall_fulfillment"],
        "snapshot": ["expected", "actual"],
        "explanation": ["missing", "wrong", "extra", "evidence", "reasoning_summary"],
        "summary": ["summary"],
    },
    "AttributeResult": {
        "canonical": ["trace_id", "project_id", "case_id", "expectation_attributions",
                      "suspected_locations", "root_cause_hypothesis", "evidence", "evidence_strength"],
        "summary": ["summary"],
    },
    "FrontendViewModel": {
        "view_only": ["project_info", "run_trace_summary", "raw_sections", "reference_panel",
                      "judge_panel", "attribute_panel", "fulfillment_panel",
                      "expectation_attribution_panel", "cluster_panel", "check_panel",
                      "table_row", "project_extensions", "tool_call_log"],
    },
    "TraceTableRow": {
        "view_only": ["id", "input", "scenario", "output_summary", "reference_summary", "status",
                      "execution_mode", "output_source", "score", "fulfillment_status",
                      "judge_summary", "attribution_summary", "check_summary", "fallback_summary",
                      "needs_human_review", "quality_flags", "check_passed", "issue_count",
                      "fallback_count", "divergence_stage", "root_cause_summary",
                      "created_at", "stop_reason", "interaction_mode", "conversation_summary",
                      "conversation_detail", "trace_id"],
    },
    "CasePoolTable": {
        "view_only": ["project_id", "rows", "total", "summary"],
    },
    "ConversationTurn": {
        "view_only": ["turn_index", "role", "content", "stage", "extracted_summary",
                      "call_status", "runtime_ms", "error"],
    },
}

PUBLIC_SCHEMA_ROLES = {"canonical", "snapshot", "summary", "view_only"}
PUBLIC_SCHEMA_FIELDS = {
    schema_name: [
        field_name
        for role, field_names in roles.items()
        if role in PUBLIC_SCHEMA_ROLES
        for field_name in field_names
    ]
    for schema_name, roles in SCHEMA_FIELD_ROLES.items()
}
PUBLIC_SCHEMA_FIELDS.update({
    "RunTrace": [
        "trace_id", "project_id", "case_id", "mock_intent", "input", "normalized_request", "raw_response",
        "extracted_output", "execution_mode", "output_source", "scenario",
        "reference_contract", "application_boundary", "evidence_refs", "execution_trace",
        "status", "error", "fallbacks", "interaction_mode", "session_id", "created_at",
        "conversation_transcript", "conversation_summary", "turn_records", "final_output_turn",
        "completion_status", "stop_reason", "turn_index",
    ],
    "LiveMultiTurnState": [
        "session_id", "turn_index", "transcript", "accumulated_fields",
        "missing_fields", "stop_reason", "turn_traces",
        "conversation_summary", "final_stage",
    ],
    "TraceStateRecord": ["state", "attempt", "status", "reason", "started_at", "ended_at", "metadata"],
    "GateDecision": ["gate_id", "gate_type", "passed", "recoverable", "recommended_transition", "reason"],
    "TransitionDecision": ["from_state", "to_state", "condition", "reason", "retry_count", "stop_reason"],
    "EvidenceRef": ["ref_id", "source", "kind", "stage", "summary", "location", "payload", "metadata"],
    "ExecutionTraceEvent": ["stage", "status", "evidence", "timestamp", "inputs", "outputs", "error", "metadata"],
    "FallbackDecision": ["stage", "reason", "selected_strategy", "status"],
    "BusinessExpectation": ["expectation_id", "downstream_consumer", "user_intent", "expected_outcome",
                            "required_capabilities", "acceptance_criteria", "boundary", "priority", "evidence_refs"],
    "FulfillmentAssessment": ["expectation_id", "status", "score", "expected_evidence", "actual_evidence",
                              "downstream_impact", "blocking", "confidence", "evidence_refs"],
    "GapItem": ["kind", "error_type", "expected", "actual", "evidence_ref", "raw", "incomplete"],
    "ExpectationAttribution": ["expectation_id", "fulfillment_status", "suspected_locations",
                               "root_cause_hypothesis", "evidence"],
    "ProbeResult": ["probe_id", "status", "summary", "evidence"],
    "ClusterSummary": None,
    "CheckReport": None,
    "ProjectAnalysis": None,
    "MockCasesResponse": None,
    "MockDatasetsResponse": None,
    "MockBuildResponse": None,
    "MockCase": ["id", "project_id", "scenario", "intent", "live_request", "output", "reference"],
    "RunChainResponse": None,
    "CasePoolsResponse": None,
    "CasePoolSaveResponse": None,
    "ApiEnvelope": None,
    "SingleTurnCase": None,
    "MultiTurnCase": None,
    "MockDataset": None,
    "JudgeResult": [
        "trace_id", "project_id",
        "business_expectations", "fulfillment_assessments", "overall_fulfillment",
        "expected", "actual", "missing", "wrong", "extra", "evidence", "reasoning_summary",
        "summary",
    ],
    "AttributeResult": [
        "trace_id", "project_id", "case_id",
        "expectation_attributions", "suspected_locations", "root_cause_hypothesis",
        "evidence", "evidence_strength", "summary",
    ],
})
PUBLIC_DROP_KEYS = {
    "raw_model_output", "raw_sections", "raw_sse", "raw_cards", "raw_text",
    "downstream_payload", "project_fields", "runtime_logs",
    "multi_turn_input", "schema_protocol_extensions",
}

# 以下类型的字段允许 None 值不过滤（ready 协议控制存在性）
_PUBLIC_ALLOW_NONE_FIELDS = frozenset({"output", "reference"})
_PUBLIC_ALLOW_NONE_SCHEMAS = frozenset({"MockCase", "MockBuildResponse"})


def field_role(schema_name: str, field_name: str) -> str:
    for role, fields in (SCHEMA_FIELD_ROLES.get(schema_name) or {}).items():
        if field_name in fields:
            return role
    return "unclassified"


def to_public_dict(value: Any) -> Any:
    return _to_public_dict(value, set())


def _json_safe_key(key: Any) -> Any:
    if isinstance(key, (str, int, float, bool)) or key is None:
        return key
    return str(key)


def _to_public_dict(value: Any, seen: set[int]) -> Any:
    if is_dataclass(value):
        value_id = id(value)
        if value_id in seen:
            return {"recursive_ref": type(value).__name__}
        seen.add(value_id)
        try:
            schema_name = type(value).__name__
            if schema_name == "MockCase":
                intent = value.intent
                return {
                    "id": value.id,
                    "project_id": value.project_id,
                    "scenario": value.scenario,
                    "intent": None if intent is None else {
                        "user_intent": intent.user_intent,
                        "query": intent.query,
                        "user_context": dict(intent.user_context or {}),
                        "system_understanding": intent.system_understanding,
                        "scenario": intent.scenario,
                    },
                    "live_request": dict(value.live_request or {}),
                    "output": value.output,
                    "reference": value.reference,
                }
            public_fields = PUBLIC_SCHEMA_FIELDS.get(schema_name)
            field_names = [item.name for item in fields(value)] if public_fields is None else public_fields
            # 部分类型允许 None 字段（ready 协议控制存在性）
            allow_none = _PUBLIC_ALLOW_NONE_FIELDS if schema_name in _PUBLIC_ALLOW_NONE_SCHEMAS else set()
            return {
                field_name: _to_public_dict(getattr(value, field_name), seen)
                for field_name in field_names
                if field_name not in PUBLIC_DROP_KEYS
                and hasattr(value, field_name)
                and (field_name in allow_none or getattr(value, field_name) not in (None, [], {}))
            }
        finally:
            seen.remove(value_id)
    if isinstance(value, list):
        value_id = id(value)
        if value_id in seen:
            return []
        seen.add(value_id)
        try:
            return [_to_public_dict(item, seen) for item in value]
        finally:
            seen.remove(value_id)
    if isinstance(value, dict):
        value_id = id(value)
        if value_id in seen:
            return {"recursive_ref": "dict"}
        seen.add(value_id)
        try:
            return {
                _json_safe_key(key): _to_public_dict(item, seen)
                for key, item in value.items()
                if key not in PUBLIC_DROP_KEYS and item not in (None, [], {})
            }
        finally:
            seen.remove(value_id)
    return value
