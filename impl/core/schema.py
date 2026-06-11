from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    raw_model_output: Any = None


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
    needs_human_review: Optional[bool] = None
    scenario: str = ""
    quality_flags: List[str] = field(default_factory=list)
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


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value
