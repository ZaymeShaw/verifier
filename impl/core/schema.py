from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SubagentResult:
    executor_id: str
    executor_type: str
    role: str
    status: str = "succeeded"
    output: Any = None
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    claims: List[Any] = field(default_factory=list)
    contradictions: List[Any] = field(default_factory=list)
    missing_evidence: List[Any] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class GateDecision:
    gate_id: str
    gate_type: str
    passed: bool
    checked_inputs: Dict[str, Any] = field(default_factory=dict)
    missing_evidence: List[Any] = field(default_factory=list)
    unsupported_claims: List[Any] = field(default_factory=list)
    contradictions: List[Any] = field(default_factory=list)
    recoverable: bool = False
    recommended_transition: str = ""
    reason: str = ""


@dataclass
class TransitionDecision:
    from_state: str
    to_state: str
    condition: str = ""
    reason: str = ""
    gate_ids: List[str] = field(default_factory=list)
    retry_count: int = 0
    stop_reason: str = ""


@dataclass
class TraceStateRecord:
    state_id: str
    role: str
    status: str = "succeeded"
    attempt: int = 1
    started_at: str = field(default_factory=now_iso)
    finished_at: str = field(default_factory=now_iso)
    input_summary: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    subagent_results: List[SubagentResult] = field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    transition_decision: Optional[TransitionDecision] = None
    errors: List[str] = field(default_factory=list)


@dataclass
class ProjectSpec:
    project_id: str
    name: str
    description: str = ""
    adapter: str = "adapter.py"
    capabilities: List[str] = field(default_factory=list)
    documents: Dict[str, str] = field(default_factory=dict)
    api: Dict[str, Any] = field(default_factory=dict)
    application: Dict[str, Any] = field(default_factory=dict)
    frontend_extensions: Dict[str, Any] = field(default_factory=dict)
    root: str = ""


@dataclass
class RunTrace:
    trace_id: str
    project_id: str
    input: Dict[str, Any]
    normalized_request: Dict[str, Any]
    raw_response: Any = None
    extracted_output: Dict[str, Any] = field(default_factory=dict)
    project_fields: Dict[str, Any] = field(default_factory=dict)
    runtime_logs: List[str] = field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    execution_trace: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "ok"
    error: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    state_history: List[TraceStateRecord] = field(default_factory=list)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    transition_decisions: List[TransitionDecision] = field(default_factory=list)
    stop_reason: str = ""


@dataclass
class BusinessExpectation:
    expectation_id: str
    downstream_consumer: str = ""
    user_intent: str = ""
    expected_outcome: str = ""
    required_capabilities: List[str] = field(default_factory=list)
    acceptance_criteria: List[Any] = field(default_factory=list)
    boundary: Dict[str, Any] = field(default_factory=dict)
    priority: str = "normal"
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class FulfillmentAssessment:
    expectation_id: str
    status: str
    score: Optional[float] = None
    expected_evidence: List[Any] = field(default_factory=list)
    actual_evidence: List[Any] = field(default_factory=list)
    boundary_decision: Dict[str, Any] = field(default_factory=dict)
    downstream_impact: str = ""
    blocking: bool = False
    confidence: Optional[float] = None
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExpectationAttribution:
    expectation_id: str
    fulfillment_status: str
    causal_category: str = ""
    earliest_divergence: Dict[str, Any] = field(default_factory=dict)
    causal_chain: List[Dict[str, Any]] = field(default_factory=list)
    local_verifications: List[Dict[str, Any]] = field(default_factory=list)
    suspected_locations: List[Any] = field(default_factory=list)
    improvement_direction: List[str] = field(default_factory=list)
    source_evidence: List[Any] = field(default_factory=list)
    probe_evidence: List[Any] = field(default_factory=list)
    incomplete_reason: str = ""


@dataclass
class JudgeResult:
    trace_id: str
    project_id: str
    verdict: str
    score: Optional[float] = None
    confidence: Optional[float] = None
    probability: Optional[float] = None
    expected: Any = None
    actual: Any = None
    consumer_contract: Dict[str, Any] = field(default_factory=dict)
    intent_model: Dict[str, Any] = field(default_factory=dict)
    business_expectations: List[Any] = field(default_factory=list)
    fulfillment_assessments: List[Any] = field(default_factory=list)
    overall_fulfillment: Dict[str, Any] = field(default_factory=dict)
    reconstructed_intent: str = ""
    judge_basis: str = ""
    judge_method: str = ""
    intent_decomposition: List[Dict[str, Any]] = field(default_factory=list)
    condition_assessments: List[Dict[str, Any]] = field(default_factory=list)
    semantic_equivalence_checks: List[Dict[str, Any]] = field(default_factory=list)
    reference_generation_basis: Dict[str, Any] = field(default_factory=dict)
    verdict_derivation: Dict[str, Any] = field(default_factory=dict)
    boundary_decision: Dict[str, Any] = field(default_factory=dict)
    evaluation_boundary: Dict[str, Any] = field(default_factory=dict)
    primary_assessment: Dict[str, Any] = field(default_factory=dict)
    contrast_assessments: List[Dict[str, Any]] = field(default_factory=list)
    missing: List[Any] = field(default_factory=list)
    wrong: List[Any] = field(default_factory=list)
    extra: List[Any] = field(default_factory=list)
    evidence: List[Any] = field(default_factory=list)
    reasoning_summary: str = ""
    score_details: List[Dict[str, Any]] = field(default_factory=list)
    needs_human_review: Optional[bool] = None
    scenario: str = ""
    quality_flags: List[str] = field(default_factory=list)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    transition_decisions: List[TransitionDecision] = field(default_factory=list)
    raw_model_output: Any = None

    def derive_verdict_from_fulfillment(self) -> str:
        """
        Ensure verdict consistency with fulfillment assessments.

        Behavior:
        1. If LLM provided explicit verdict → preserve it, update overall_fulfillment
        2. If LLM verdict missing/empty → derive from fulfillment_assessments

        This method acts as a fallback mechanism, not a forced override.
        Called multiple times safely (idempotent).
        """
        # If LLM already provided an explicit verdict, preserve it instead of overriding
        # This method should only derive verdict when LLM verdict is missing/empty
        if self.verdict and self.verdict not in ("", "-", "unknown"):
            # LLM provided explicit verdict, keep it and only update overall_fulfillment
            statuses = [_item_value(item, "status") for item in self.fulfillment_assessments]
            failing_statuses = {"not_fulfilled", "partially_fulfilled", "not_evaluable", "contested"}
            blocking = [item for item in self.fulfillment_assessments if _item_value(item, "status") in failing_statuses]

            # Map existing verdict to fulfillment status
            verdict_to_status = {
                "correct": "fulfilled",
                "incorrect": "not_fulfilled",
                "uncertain": "partially_fulfilled" if any(s == "partially_fulfilled" for s in statuses) else "not_evaluable",
            }
            overall_status = verdict_to_status.get(self.verdict, "not_evaluable")

            # Always set overall_fulfillment, even if statuses is empty
            # (e.g., after reconcile_equivalent_judge_result clears fulfillment_assessments)
            self.overall_fulfillment = {
                **(self.overall_fulfillment or {}),
                "status": overall_status,
                "assessment_count": len(statuses),
                "blocking_expectations": [_item_value(item, "expectation_id") for item in blocking],
            }
            self.verdict_derivation = {
                **(self.verdict_derivation or {}),
                "primary_source": "llm_explicit_verdict",
                "fulfillment_statuses": statuses,
                "blocking_expectations": [_item_value(item, "expectation_id") for item in blocking],
            }
            return self.verdict

        # LLM verdict missing, derive from fulfillment assessments
        statuses = [_item_value(item, "status") for item in self.fulfillment_assessments]
        failing_statuses = {"not_fulfilled", "partially_fulfilled", "not_evaluable", "contested"}
        blocking = [item for item in self.fulfillment_assessments if _item_value(item, "status") in failing_statuses]
        if not statuses:
            non_evaluable_markers = {"LLM semantic judge unavailable; local QA probe cannot determine answer correctness.", "estimated_quality_only"}
            concrete_missing = [item for item in self.missing if not (isinstance(item, str) and item in non_evaluable_markers)]
            if self.wrong or self.extra or concrete_missing:
                derived = "incorrect"
            else:
                derived = "uncertain"
        elif any(status == "not_fulfilled" for status in statuses):
            derived = "incorrect"
        elif any(status in {"not_evaluable", "contested"} for status in statuses):
            derived = "uncertain"
        elif any(status == "partially_fulfilled" for status in statuses):
            derived = "uncertain"
        else:
            derived = "correct"
        if derived == "correct":
            self.missing = []
            self.wrong = []
            self.extra = []
        overall_status = {
            "correct": "fulfilled",
            "incorrect": "not_fulfilled",
            "uncertain": "partially_fulfilled" if any(status == "partially_fulfilled" for status in statuses) else "not_evaluable",
        }[derived]
        if statuses:
            self.overall_fulfillment = {
                **(self.overall_fulfillment or {}),
                "status": overall_status,
                "assessment_count": len(statuses),
                "blocking_expectations": [_item_value(item, "expectation_id") for item in blocking],
            }
        self.verdict = derived
        self.verdict_derivation = {
            **(self.verdict_derivation or {}),
            "primary_source": "fulfillment_assessments",
            "fulfillment_statuses": statuses,
            "blocking_expectations": [_item_value(item, "expectation_id") for item in blocking],
        }
        return derived


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


@dataclass
class AttributeResult:
    trace_id: str
    project_id: str
    case_id: str = ""
    failure_category: str = "未归因"
    failure_stage: str = "不确定"
    analysis_method: str = ""
    evidence_chain: List[Any] = field(default_factory=list)
    trace_analysis: List[Any] = field(default_factory=list)
    chain_nodes: List[Dict[str, Any]] = field(default_factory=list)
    local_verifications: List[Dict[str, Any]] = field(default_factory=list)
    earliest_divergence: Dict[str, Any] = field(default_factory=dict)
    evidence_coverage: Dict[str, Any] = field(default_factory=dict)
    analysis_quality: Dict[str, Any] = field(default_factory=dict)
    incomplete_reason: str = ""
    suspected_locations: List[Any] = field(default_factory=list)
    root_cause_hypothesis: str = ""
    verification_steps: List[str] = field(default_factory=list)
    patch_direction: List[str] = field(default_factory=list)
    business_impact: str = ""
    primary_error_type: str = ""
    error_types: List[str] = field(default_factory=list)
    severity: str = ""
    expectation_attributions: List[Any] = field(default_factory=list)
    causal_category: str = ""
    probe_results: List[Dict[str, Any]] = field(default_factory=list)
    needs_human_review: Optional[bool] = None
    scenario: str = ""
    quality_flags: List[str] = field(default_factory=list)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    transition_decisions: List[TransitionDecision] = field(default_factory=list)
    raw_model_output: Any = None


@dataclass
class ClusterSummary:
    project_id: str
    clusters: List[Dict[str, Any]] = field(default_factory=list)
    representative_cases: List[Any] = field(default_factory=list)
    common_root_cause: str = ""
    impact: str = ""
    priority: str = ""
    next_actions: List[str] = field(default_factory=list)


@dataclass
class FrontendViewModel:
    project_info: Dict[str, Any]
    run_trace_summary: Dict[str, Any] = field(default_factory=dict)
    raw_sections: Dict[str, Any] = field(default_factory=dict)
    reference_panel: Dict[str, Any] = field(default_factory=dict)
    judge_panel: Dict[str, Any] = field(default_factory=dict)
    attribute_panel: Dict[str, Any] = field(default_factory=dict)
    fulfillment_panel: Dict[str, Any] = field(default_factory=dict)
    expectation_attribution_panel: Dict[str, Any] = field(default_factory=dict)
    cluster_panel: Dict[str, Any] = field(default_factory=dict)
    check_panel: Dict[str, Any] = field(default_factory=dict)
    project_extensions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectAnalysis:
    project_id: str
    api: Dict[str, Any] = field(default_factory=dict)
    application: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    documents: Dict[str, str] = field(default_factory=dict)
    mock_guidance: str = ""
    evaluation_guidance: str = ""
    attribution_guidance: str = ""
    analysis_handoff: Dict[str, Any] = field(default_factory=dict)
    frontend_build_handoff: Dict[str, Any] = field(default_factory=dict)
    judge_handoff: Dict[str, Any] = field(default_factory=dict)
    attribute_handoff: Dict[str, Any] = field(default_factory=dict)
    quality_flags: List[str] = field(default_factory=list)


@dataclass
class BatchRunResult:
    project_id: str
    total: int
    runs: List[Dict[str, Any]] = field(default_factory=list)
    cluster: Dict[str, Any] = field(default_factory=dict)
    check: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckReport:
    passed: bool
    issues: List[str] = field(default_factory=list)
    boundary_violations: List[str] = field(default_factory=list)
    protocol_gaps: List[str] = field(default_factory=list)
    consistency_gaps: List[str] = field(default_factory=list)
    overfit_risks: List[str] = field(default_factory=list)
    data_only_patch_risks: List[str] = field(default_factory=list)
    verification_results: List[str] = field(default_factory=list)
    recommended_fixes: List[str] = field(default_factory=list)


# Shared utility functions (used by judge, frontend_view, etc.)
def _non_empty_reference(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(item not in (None, "", [], {}) for item in value.values())
    if isinstance(value, list):
        return bool(value)
    return value != ""


def _first_list_value(data: Any) -> Any:
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, list):
            return value
    return None


def _first_list_key(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for key, value in data.items():
        if isinstance(value, list):
            return key
    return None




def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value
