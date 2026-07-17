from __future__ import annotations

from typing import Any, Dict, Optional

from .schema import FallbackDecision


def fallback_decision(
    fallback_id: str,
    source_stage: str,
    fallback_type: str,
    status: str,
    reason: str,
    missing_evidence: Optional[list[str]] = None,
    recoverable: bool = False,
    needs_human_review: bool = False,
    quality_flags: Optional[list[str]] = None,
    evidence_refs: Optional[list[Dict[str, Any]]] = None,
    failed_gate_ids: Optional[list[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> FallbackDecision:
    return FallbackDecision(
        fallback_id=fallback_id,
        source_stage=source_stage,
        fallback_type=fallback_type,
        status=status,
        reason=reason,
        missing_evidence=list(missing_evidence or []),
        recoverable=recoverable,
        needs_human_review=needs_human_review,
        quality_flags=list(quality_flags or []),
        evidence_refs=list(evidence_refs or []),
        failed_gate_ids=list(failed_gate_ids or []),
        metadata=dict(metadata or {}),
    )
