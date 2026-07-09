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
    # spec/info-volume.md：通用层只保留任何项目做判定都需要的最小产出。
    # 项目特有的判定字段（intent_model/consumer_contract/verdict_derivation/boundary_decision 等）
    # 下沉到 impl/projects/<project>/judge.py 自定义，不进通用 schema。
    trace_id: str
    project_id: str
    business_expectations: List[BusinessExpectation] = field(default_factory=list)
    fulfillment_assessments: List[FulfillmentAssessment] = field(default_factory=list)
    overall_fulfillment: Dict[str, Any] = field(default_factory=dict)
    expected: Any = None
    actual: Any = None
    missing: List[GapItem] = field(default_factory=list)
    wrong: List[GapItem] = field(default_factory=list)
    extra: List[GapItem] = field(default_factory=list)
    evidence: List[Any] = field(default_factory=list)
    reasoning_summary: str = ""
    # summary 是基于 fulfillment_assessments 派生的展示摘要
    # (reason / reason_source / primary_failure_dimensions)，由 judge 阶段统一产出，
    # 下游 table_view/check/前端直接复用，避免各处重复派生导致不一致。
    summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgeLLMOutput:
    # spec/struct_output.md：judge 调用 LLM 时应产出的结构（不含代码派生字段）。
    # 作为 StructuredOutputSpec.from_dataclass 的 dataclass 来源，传给 complete_json。
    business_expectations: List[BusinessExpectation] = field(default_factory=list)
    fulfillment_assessments: List[FulfillmentAssessment] = field(default_factory=list)
    overall_fulfillment: Dict[str, Any] = field(default_factory=dict)
    expected: Any = None
    # actual 是 live 系统真实输出，由代码从 RunTrace 填充；LLM 不产 actual，避免把摘要/比较中间态污染主字段。
    missing: List[GapItem] = field(default_factory=list)
    wrong: List[GapItem] = field(default_factory=list)
    extra: List[GapItem] = field(default_factory=list)
    evidence: List[Any] = field(default_factory=list)
    reasoning_summary: str = ""


@dataclass
class JudgeReferenceOutput:
    # spec/struct_output.md / spec/reference.md：仅生成 reference（expected）模式。
    # 无 actual + 有意图时，judge 只产 expected 相关字段，不做 fulfillment 判定。
    business_expectations: List[BusinessExpectation] = field(default_factory=list)
    expected: Any = None


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    # 兼容 dict 和 dataclass/object 的字段读取工具，供前端和 check 复用。
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)
