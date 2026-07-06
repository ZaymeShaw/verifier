from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import GateDecision, TransitionDecision
from .fallback import FallbackDecision


@dataclass
class BusinessExpectation:
    # Judge 层：从用户意图推导出的业务期望。
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
    # Judge 层：某个业务期望是否被 actual output 满足。
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
class GapItem:
    # Judge 层：expected 与 actual 之间的 wrong/missing/extra 结构化差异项。
    kind: str = ""
    error_type: str = ""
    expected: Any = None
    actual: Any = None
    evidence_ref: str = ""
    raw: Any = None
    incomplete: bool = False


@dataclass
class JudgeResult:
    # Judge 层：评估输出是否满足业务期望的完整结果。
    trace_id: str
    project_id: str
    verdict: str = ""
    score: Optional[float] = None
    confidence: Optional[float] = None
    probability: Optional[float] = None
    expected: Any = None
    actual: Any = None
    consumer_contract: Dict[str, Any] = field(default_factory=dict)
    intent_model: Dict[str, Any] = field(default_factory=dict)
    business_expectations: List[BusinessExpectation] = field(default_factory=list)
    fulfillment_assessments: List[FulfillmentAssessment] = field(default_factory=list)
    overall_fulfillment: Dict[str, Any] = field(default_factory=dict)
    reconstructed_intent: str = ""
    judge_basis: str = ""
    judge_method: str = ""
    semantic_equivalence_checks: List[Dict[str, Any]] = field(default_factory=list)
    reference_generation_basis: Dict[str, Any] = field(default_factory=dict)
    verdict_derivation: Dict[str, Any] = field(default_factory=dict)
    boundary_decision: Dict[str, Any] = field(default_factory=dict)
    evaluation_boundary: Dict[str, Any] = field(default_factory=dict)
    missing: List[GapItem] = field(default_factory=list)
    wrong: List[GapItem] = field(default_factory=list)
    extra: List[GapItem] = field(default_factory=list)
    evidence: List[Any] = field(default_factory=list)
    reasoning_summary: str = ""
    needs_human_review: Optional[bool] = None
    scenario: str = ""
    quality_flags: List[str] = field(default_factory=list)
    # summary 是基于 fulfillment_assessments/verdict 派生的展示摘要
    # (reason / reason_source / primary_failure_dimensions)，由 judge 阶段统一产出，
    # 下游 table_view/check/前端直接复用，避免各处重复派生导致不一致。
    summary: Dict[str, Any] = field(default_factory=dict)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    transition_decisions: List[TransitionDecision] = field(default_factory=list)
    # raw_model_output 仅保存 judge LLM 的不透明原始返回，业务事实应落到 typed 字段。
    raw_model_output: Any = None
    overrides: List[Dict[str, Any]] = field(default_factory=list)
    fallbacks: List[FallbackDecision] = field(default_factory=list)
    # JudgeLLMOutput：LLM 应产出的结构化部分（spec/struct_output.md）。
    # 代码派生字段（trace_id/project_id/gate_decisions/summary/raw_model_output 等）不在此处，
    # 由 _build_judge_result_from_data 组装进 JudgeResult 的其余字段。
    llm_output: Optional["JudgeLLMOutput"] = None


@dataclass
class JudgeLLMOutput:
    # spec/struct_output.md：judge 调用 LLM 时应产出的结构（不含代码派生字段）。
    # 作为 StructuredOutputSpec.from_dataclass 的 dataclass 来源，传给 complete_json。
    # 嵌套层级只含可序列化内容：基本类型 / list / dict / 嵌套 dataclass（BusinessExpectation 等）。
    #
    # 与 JudgeResult 的关系：LLM 只负责本 dataclass，代码负责组装 JudgeResult 的派生字段
    # （trace_id/project_id/verdict/score/gate_decisions/summary 等）。
    business_expectations: List[BusinessExpectation] = field(default_factory=list)
    fulfillment_assessments: List[FulfillmentAssessment] = field(default_factory=list)
    overall_fulfillment: Dict[str, Any] = field(default_factory=dict)
    expected: Any = None
    # actual 是 live 系统真实输出，由代码从 RunTrace 填充；LLM 不产 actual，避免把摘要/比较中间态污染主字段。
    intent_model: Dict[str, Any] = field(default_factory=dict)
    consumer_contract: Dict[str, Any] = field(default_factory=dict)
    reconstructed_intent: str = ""
    judge_basis: str = ""
    judge_method: str = "current_case_llm_judge"
    semantic_equivalence_checks: List[Dict[str, Any]] = field(default_factory=list)
    reference_generation_basis: Dict[str, Any] = field(default_factory=dict)
    verdict_derivation: Dict[str, Any] = field(default_factory=dict)
    boundary_decision: Dict[str, Any] = field(default_factory=dict)
    evaluation_boundary: Dict[str, Any] = field(default_factory=dict)
    missing: List[GapItem] = field(default_factory=list)
    wrong: List[GapItem] = field(default_factory=list)
    extra: List[GapItem] = field(default_factory=list)
    evidence: List[Any] = field(default_factory=list)
    reasoning_summary: str = ""
    needs_human_review: Optional[bool] = None
    scenario: str = ""
    quality_flags: List[str] = field(default_factory=list)


@dataclass
class JudgeReferenceOutput:
    # spec/struct_output.md / spec/reference.md：仅生成 reference（expected）模式。
    # 无 actual + 有意图时，judge 只产 expected 相关字段，不做 fulfillment 判定。
    business_expectations: List[BusinessExpectation] = field(default_factory=list)
    expected: Any = None
    reconstructed_intent: str = ""
    judge_basis: str = ""
    reference_generation_basis: Dict[str, Any] = field(default_factory=dict)


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    # 兼容 dict 和 dataclass/object 的字段读取工具，供前端和 check 复用。
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)
