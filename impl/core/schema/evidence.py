from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ExecutionTraceEvent:
    stage: str
    status: str = ""
    evidence: Any = None
    timestamp: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceRef:
    ref_id: str
    source: str = ""
    kind: str = ""
    stage: str = ""
    summary: str = ""
    location: str = ""
    payload: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProbeResult:
    probe_id: str
    status: str = ""
    stage: str = ""
    evidence: List[Any] = field(default_factory=list)
    findings: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
