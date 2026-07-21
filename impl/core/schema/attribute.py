from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .evidence import EvidenceRef


@dataclass
class AttributionFinding:
    """One verified business defect, optionally covering several failed expectations."""

    finding_id: str
    affected_expectation_ids: List[str] = field(default_factory=list)
    conclusion: str = ""
    evidence: List[EvidenceRef] = field(default_factory=list)


@dataclass
class AttributeResult:
    """Public Attribute result. Only reviewed findings cross this boundary."""

    trace_id: str
    project_id: str
    case_id: str = ""
    findings: List[AttributionFinding] = field(default_factory=list)
    unresolved_reason: str = ""
    summary: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AttributeEvidenceSelection:
    """Private LLM I/O: a ContextUnit selected after Finalization reload."""

    context_unit_id: str
    reason: str


@dataclass
class AttributeFindingOutput:
    """Private LLM I/O before trusted EvidenceRef fields are materialized."""

    finding_id: str
    affected_expectation_ids: List[str] = field(default_factory=list)
    conclusion: str = ""
    evidence: List[AttributeEvidenceSelection] = field(default_factory=list)


@dataclass
class AttributeLLMOutput:
    """Private final output emitted after the main executor's Finalization self-review."""

    findings: List[AttributeFindingOutput] = field(default_factory=list)
    unresolved_reason: str = ""
