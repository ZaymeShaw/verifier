from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExpectationAttribution:
    # Attribute 层：对单个业务期望未满足/已满足原因的归因。
    # spec/info-volume.md：通用层只保留最小字段，项目特有字段下沉到项目层。
    expectation_id: str
    fulfillment_status: str
    suspected_locations: List[Any] = field(default_factory=list)
    root_cause_hypothesis: str = ""
    evidence: List[Any] = field(default_factory=list)


@dataclass
class AttributeResult:
    # Attribute 层：从 trace/judge 走查到根因、证据的完整归因结果。
    # spec/info-volume.md：通用层只保留任何项目做归因都需要的最小产出。
    # 项目特有的产出（分类体系、链路结构、验证步骤、修复方向）全部下沉到
    # impl/projects/<project>/attribute.py 自定义，不进通用 schema。
    trace_id: str
    project_id: str
    case_id: str = ""
    expectation_attributions: List[ExpectationAttribution] = field(default_factory=list)
    suspected_locations: List[Any] = field(default_factory=list)
    root_cause_hypothesis: str = ""
    evidence: List[Any] = field(default_factory=list)
    evidence_strength: str = ""  # strong | medium | weak | none
    # summary 是基于 expectation_attributions 派生的展示摘要
    # (summary_text / is_complete / is_formal_attribution)，
    # 由 attribute 阶段统一产出，下游 table_view/check/前端直接复用。
    summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AttributeLLMOutput:
    # spec/struct_output.md：attribute 调用 LLM 时应产出的结构（不含代码派生字段）。
    expectation_attributions: List[ExpectationAttribution] = field(default_factory=list)
    suspected_locations: List[Any] = field(default_factory=list)
    root_cause_hypothesis: str = ""
    evidence: List[Any] = field(default_factory=list)
    evidence_strength: str = ""