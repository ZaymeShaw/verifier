from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import GateDecision, TransitionDecision
from .evidence import ExecutionTraceEvent, ProbeResult
from .fallback import FallbackDecision


@dataclass
class ExpectationAttribution:
    # Attribute 层：对单个业务期望未满足/已满足原因的归因。
    expectation_id: str
    fulfillment_status: str
    causal_category: str = ""
    earliest_divergence: Dict[str, Any] = field(default_factory=dict)
    causal_chain: List[Dict[str, Any]] = field(default_factory=list)
    suspected_locations: List[Any] = field(default_factory=list)
    improvement_direction: List[str] = field(default_factory=list)
    source_evidence: List[Any] = field(default_factory=list)
    probe_evidence: List[Any] = field(default_factory=list)
    incomplete_reason: str = ""


@dataclass
class ChainNode:
    # Attribute 层：归因证据链上的一个可检查节点。
    name: str
    status: str = "not_verified"
    evidence: List[Any] = field(default_factory=list)
    reason: str = ""


@dataclass
class AttributeResult:
    # Attribute 层：从 trace/judge 走查到根因、证据、修复方向的完整归因结果。
    trace_id: str
    project_id: str
    case_id: str = ""
    analysis_method: str = ""
    chain_nodes: List[ChainNode] = field(default_factory=list)
    earliest_divergence: Dict[str, Any] = field(default_factory=dict)
    evidence_coverage: Dict[str, Any] = field(default_factory=dict)
    analysis_quality: Dict[str, Any] = field(default_factory=dict)
    incomplete_reason: str = ""
    suspected_locations: List[Any] = field(default_factory=list)
    root_cause_hypothesis: str = ""
    verification_steps: List[str] = field(default_factory=list)
    patch_direction: List[str] = field(default_factory=list)
    expectation_attributions: List[ExpectationAttribution] = field(default_factory=list)
    causal_category: str = ""
    probe_results: List[ProbeResult] = field(default_factory=list)
    needs_human_review: Optional[bool] = None
    scenario: str = ""
    quality_flags: List[str] = field(default_factory=list)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    transition_decisions: List[TransitionDecision] = field(default_factory=list)
    # summary 是基于 expectation_attributions/analysis_quality 派生的展示摘要
    # (causal_category / attribution_count / probe_count / summary_text / is_complete / is_formal_attribution)，
    # 由 attribute 阶段统一产出，下游 table_view/check/前端直接复用。
    summary: Dict[str, Any] = field(default_factory=dict)
    # raw_model_output 仅保存 attribute LLM 的不透明原始返回，归因事实应落到 typed 字段。
    raw_model_output: Any = None
    fallbacks: List[FallbackDecision] = field(default_factory=list)
    # spec/tool2.md: 可执行验证 tool 的调用记录（tool_id + params + actual + evidence + status），
    # 供后端 API/前端展示 tool 调用链与 expected/actual 对照。
    tool_call_log: List[Dict[str, Any]] = field(default_factory=list)
    # AttributeLLMOutput：LLM 应产出的结构化部分（spec/struct_output.md）。
    llm_output: Optional["AttributeLLMOutput"] = None


@dataclass
class AttributeLLMOutput:
    # spec/struct_output.md：attribute 调用 LLM 时应产出的结构（不含代码派生字段）。
    # 作为 StructuredOutputSpec.from_dataclass 的 dataclass 来源，传给 complete_json。
    expectation_attributions: List[ExpectationAttribution] = field(default_factory=list)
    causal_category: str = ""
    probe_results: List[Dict[str, Any]] = field(default_factory=list)
    analysis_method: str = ""
    chain_nodes: List[ChainNode] = field(default_factory=list)
    earliest_divergence: Dict[str, Any] = field(default_factory=dict)
    evidence_coverage: Dict[str, Any] = field(default_factory=dict)
    analysis_quality: Dict[str, Any] = field(default_factory=dict)
    incomplete_reason: str = ""
    suspected_locations: List[Any] = field(default_factory=list)
    root_cause_hypothesis: str = ""
    verification_steps: List[str] = field(default_factory=list)
    patch_direction: List[str] = field(default_factory=list)
    needs_human_review: Optional[bool] = None
    scenario: str = ""
    quality_flags: List[str] = field(default_factory=list)
