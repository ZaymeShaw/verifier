from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class FallbackDecision:
    fallback_id: str
    source_stage: str
    fallback_type: str
    status: str
    reason: str
    missing_evidence: List[str] = field(default_factory=list)
    recoverable: bool = False
    needs_human_review: bool = False
    quality_flags: List[str] = field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    failed_gate_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
