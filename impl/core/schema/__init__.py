from __future__ import annotations

# 兼容层：外部仍可使用 `from impl.core.schema import RunTrace`，
# 同时每个概念也可以从 `impl.core.schema.<layer>` 分层导入。
from .base import GateDecision, SubagentResult, TransitionDecision, now_iso, to_dict
from .batch import BatchRunResult
from .check import CheckReport
from .cluster import ClusterSummary
from .config import LayerConfig, SchemaLayerConfig
from .attribute import AttributeLLMOutput, AttributeResult, ExpectationAttribution
from .fallback import FallbackDecision
from .evidence import EvidenceRef, ExecutionTraceEvent, ProbeResult
from .frontend import FrontendViewModel
from .judge import BusinessExpectation, FulfillmentAssessment, GapItem, JudgeLLMOutput, JudgeReferenceOutput, JudgeResult, _item_value
from .live import LiveMultiTurnState, LiveRequest
from .mock import MockBuildResult, MockBuildSpec, MockCase, MockDataset, MockIntentOutput, MockNextTurnOutput, MockSpec, MultiTurnCase, MultiTurnInteraction, MultiTurnPolicy, MultiTurnTurnExpectation, SingleTurnCase
from .project import ProjectAnalysis, ProjectSpec
from .registry import SCHEMA_LAYERS
from .accessors import judge_expected_actual_gaps, judge_primary_signal, trace_application_boundary, trace_conversation_summary, trace_conversation_transcript, trace_execution_trace, trace_extracted_output, trace_input, trace_mock_intent, trace_normalized_request, trace_output_source, trace_project_fields, trace_raw_response, trace_stop_reason, trace_turn_records
from .api import API_ENDPOINT_SCHEMAS, ApiEnvelope, CasePoolSaveResponse, CasePoolsResponse, MockBuildResponse, MockCasesResponse, MockDatasetsResponse, RunChainResponse
from .occam import SCHEMA_FIELD_ROLES, field_role, to_public_dict
from .table import CasePoolTable, ConversationTurn, TraceTableRow
from .trace import MultiTurnTraceSummary, RunTrace, TraceExecutionContext, TraceStateRecord
from .normalize import CALL_STATUSES, CHAIN_STATUSES, EVENT_STATUSES, FALLBACK_STATUSES, FULFILLMENT_STATUSES, INTERACTION_MODES, TRACE_STATUSES, VERDICTS, normalize_attribute_result, normalize_attribute_results, normalize_business_expectation, normalize_case_pool_table, normalize_chain_node, normalize_check_report, normalize_cluster_summary, normalize_conversation_turn, normalize_conversation_turns, normalize_evidence_ref, normalize_evidence_refs, normalize_execution_trace_event, normalize_execution_trace_events, normalize_expectation_attribution, normalize_fallback_decision, normalize_fallback_decisions, normalize_frontend_view, normalize_fulfillment_assessment, normalize_gap_item, normalize_judge_result, normalize_live_multi_turn_state, normalize_live_request, normalize_mock_case, normalize_mock_dataset, normalize_mock_spec, normalize_multi_turn_trace_summary, normalize_probe_result, normalize_probe_results, normalize_run_trace, normalize_trace_execution_context, normalize_trace_table_row, normalize_trace_table_rows
from .utils import _first_list_key, _first_list_value, _non_empty_reference

__all__ = [
    "AttributeLLMOutput", "AttributeResult", "BatchRunResult", "BusinessExpectation", "CALL_STATUSES", "CasePoolSaveResponse", "CasePoolTable", "CasePoolsResponse", "CHAIN_STATUSES",
    "CheckReport", "ClusterSummary", "ConversationTurn", "EVENT_STATUSES", "EvidenceRef", "ExecutionTraceEvent",
    "ExpectationAttribution", "FALLBACK_STATUSES", "FULFILLMENT_STATUSES", "FallbackDecision", "FrontendViewModel",
    "FulfillmentAssessment", "GapItem", "GateDecision", "INTERACTION_MODES", "JudgeLLMOutput", "JudgeReferenceOutput", "JudgeResult", "LayerConfig",
    "LiveMultiTurnState", "LiveRequest", "MockBuildResponse", "MockBuildResult", "MockBuildSpec", "MockCase", "MockCasesResponse", "MockDatasetsResponse", "MockIntentOutput", "MockNextTurnOutput",
    "MockDataset", "MockSpec", "MultiTurnCase", "MultiTurnInteraction", "MultiTurnPolicy",
    "MultiTurnTraceSummary", "MultiTurnTurnExpectation", "ProbeResult", "ProjectAnalysis", "ProjectSpec", "RunChainResponse",
    "RunTrace", "SCHEMA_FIELD_ROLES", "SCHEMA_LAYERS", "SchemaLayerConfig", "SingleTurnCase", "SubagentResult",
    "TRACE_STATUSES", "TraceExecutionContext", "TraceStateRecord", "TraceTableRow", "TransitionDecision", "VERDICTS", "API_ENDPOINT_SCHEMAS", "ApiEnvelope", "_first_list_key",
    "_first_list_value", "_item_value", "_non_empty_reference", "normalize_attribute_result",
    "normalize_attribute_results", "normalize_business_expectation", "normalize_case_pool_table",
    "normalize_chain_node", "normalize_check_report", "normalize_cluster_summary",
    "normalize_conversation_turn", "normalize_conversation_turns", "normalize_evidence_ref",
    "normalize_evidence_refs", "normalize_execution_trace_event", "normalize_execution_trace_events",
    "normalize_expectation_attribution",
    "normalize_fallback_decision", "normalize_fallback_decisions", "normalize_frontend_view",
    "normalize_fulfillment_assessment", "normalize_gap_item",
    "normalize_judge_result", "normalize_live_multi_turn_state", "normalize_live_request", "normalize_mock_case",
    "normalize_mock_dataset", "normalize_mock_spec", "normalize_multi_turn_trace_summary",
    "normalize_probe_result", "normalize_probe_results", "normalize_run_trace", "normalize_trace_execution_context",
    "normalize_trace_table_row", "normalize_trace_table_rows", "now_iso", "field_role", "to_dict", "to_public_dict",
    "trace_application_boundary", "trace_conversation_summary", "trace_conversation_transcript", "trace_execution_trace", "trace_extracted_output", "trace_turn_records",
    "trace_input", "trace_mock_intent", "trace_normalized_request", "trace_output_source", "trace_project_fields", "trace_raw_response", "trace_stop_reason",
    "judge_expected_actual_gaps", "judge_primary_signal",
]
