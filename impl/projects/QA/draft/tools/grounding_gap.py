from __future__ import annotations

import re
from typing import Any

from impl.tools import ToolResult, VerifiableTool


_EXACT_AMOUNT_PATTERN = re.compile(r"(?:\d+(?:\.\d+)?\s*(?:万|万元|元)|\d+\s*%)")
_UNCERTAIN_REFERENCE_TERMS = ("无法直接给", "无法确定", "取决于", "具体条款", "基本保额", "等待期", "额外赔付")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _answer_from(payload: Any) -> str:
    if not isinstance(payload, dict):
        return _as_text(payload)
    for key in ("actual_answer", "answer", "output", "text"):
        text = _as_text(payload.get(key))
        if text:
            return text
    return ""


def analyze_grounding_gap(reference: dict[str, Any], actual: dict[str, Any], question: str = "") -> ToolResult:
    reference_answer = _answer_from(reference)
    actual_answer = _answer_from(actual)
    exact_claims = _EXACT_AMOUNT_PATTERN.findall(actual_answer)
    reference_warns_uncertain = any(term in reference_answer for term in _UNCERTAIN_REFERENCE_TERMS)
    unsupported_exact_claims = exact_claims if reference_warns_uncertain else []
    missing = [
        name
        for name, absent in (
            ("reference_answer", not bool(reference_answer)),
            ("actual_answer", not bool(actual_answer)),
        )
        if absent
    ]
    status = "failed" if missing else ("diverged" if unsupported_exact_claims else "passed")
    return ToolResult(
        tool_id="qa.grounding_gap_probe",
        status=status,
        actual={
            "question_present": bool(_as_text(question)),
            "reference_answer_present": bool(reference_answer),
            "actual_answer_present": bool(actual_answer),
            "reference_warns_uncertain": reference_warns_uncertain,
            "actual_exact_claims": exact_claims,
            "unsupported_exact_claims": unsupported_exact_claims,
        },
        evidence=(
            "actual answer makes exact payout/percentage claims while reference says payout depends on policy terms"
            if unsupported_exact_claims
            else "grounding probe did not find unsupported exact payout claims"
        ),
        missing_evidence=missing,
        boundary_limits=["This probe checks exact amount/percentage grounding only; it does not judge full QA helpfulness."],
    )


def build_qa_grounding_gap_tool(reference: dict[str, Any], actual: dict[str, Any], question: str = "") -> VerifiableTool:
    return VerifiableTool(
        tool_id="qa.grounding_gap_probe",
        description="Detects unsupported exact payout or percentage claims in the current QA answer when the reference says the exact payout depends on policy terms.",
        applicable_scenario="QA answer grounding attribution",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        execute_fn=lambda: analyze_grounding_gap(reference=reference, actual=actual, question=question),
    )


TOOL_EVIDENCE_CONTRACT: dict[str, Any] = {
    "name": "qa.grounding_gap_probe",
    "purpose": "Provide current-case evidence that a QA answer asserted an exact payout or percentage not supported by the reference answer.",
    "input_schema": {
        "reference": "current trace.reference_contract or normalized_request.reference",
        "actual": "judge_result.actual or trace.extracted_output",
        "question": "current normalized_request.input.question",
    },
    "output_schema": {
        "reference_warns_uncertain": "bool",
        "actual_exact_claims": "list[str]",
        "unsupported_exact_claims": "list[str]",
        "missing_evidence": "list[str]",
    },
    "evidence_type": "Can prove an answer-grounding divergence for exact payout/percentage claims; cannot prove every possible semantic QA failure.",
    "boundary": "Returns failed with missing_evidence when reference or actual answer is absent; never upgrades missing evidence to strong attribution.",
    "validation": "Run on QA grounding cases where the reference states the exact amount is policy-dependent; expect unsupported_exact_claims only when actual asserts exact payout or percentage without current reference support.",
}
