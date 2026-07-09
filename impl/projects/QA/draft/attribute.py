from __future__ import annotations

from typing import Any

from impl.core.attribute_protocol import run_project_attribute_protocol
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace
from impl.projects.QA.draft.tools.grounding_gap import analyze_grounding_gap


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _input_payload(request: dict[str, Any]) -> dict[str, Any]:
    payload = request.get("input") if isinstance(request.get("input"), dict) else request
    return payload if isinstance(payload, dict) else {}


def _answer_from(payload: Any) -> str:
    if not isinstance(payload, dict):
        return _as_text(payload)
    for key in ("actual_answer", "answer", "output", "text"):
        text = _as_text(payload.get(key))
        if text:
            return text
    return ""


def _qa_draft_probe(trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
    input_payload = _input_payload(request)
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else request.get("reference") or {}
    actual = judge_result.actual or trace.extracted_output or request.get("output") or {}
    if not isinstance(reference, dict):
        reference = {}
    if not isinstance(actual, dict):
        actual = {"actual_answer": _answer_from(actual)}
    grounding = analyze_grounding_gap(reference=reference, actual=actual, question=_as_text(input_payload.get("question")))
    return {
        "question_present": bool(_as_text(input_payload.get("question"))),
        "reference_answer_present": bool(_answer_from(reference)),
        "actual_answer_present": bool(_answer_from(actual)),
        "judge_status": (judge_result.overall_fulfillment or {}).get("status"),
        "fulfillment_assessment_count": len(judge_result.fulfillment_assessments or []),
        "grounding_gap_tool": {
            "status": grounding.status,
            "actual": grounding.actual,
            "evidence": grounding.evidence,
            "missing_evidence": grounding.missing_evidence,
            "boundary_limits": grounding.boundary_limits,
        },
    }


def _build_project_attribute_context(spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
    input_payload = _input_payload(request)
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else request.get("reference") or {}
    actual = judge_result.actual or trace.extracted_output or request.get("output") or {}
    return {
        "tool_call_limit": 3,
        "system_prompt_override": """你是 QA 项目的 draft attribute agent。
只基于当前 RunTrace、JudgeResult、qa_draft_probe 和 grounding_gap_tool 归因；不要复用历史 case，不要把其他项目字段带入 QA。
如果 grounding_gap_tool 缺少 reference/actual，evidence_strength 必须为 none 或 weak；只有当前 case probe 明确显示 unsupported_exact_claims 时才允许 strong/medium。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": ["input_normalization", "provided_output_extraction", "reference_alignment", "semantic_judge", "answer_grounding_attribution"],
                "root_cause_policy": "Use qa_draft_probe.grounding_gap_tool before LLM inference; exact payout claims require current reference support.",
                "evidence_contract": ["current question", "current reference answer", "current actual answer", "judge_result", "grounding_gap_tool"],
                "service_boundary": "provided output only; no external QA service call is executed by this verifier project",
            },
            "question": _as_text(input_payload.get("question")),
            "reference_contract": reference if isinstance(reference, dict) else {},
            "actual_answer": actual if isinstance(actual, dict) else {},
            "qa_draft_probe": _qa_draft_probe(trace, judge_result),
        },
    }


def attribute_failure(spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    return run_project_attribute_protocol(
        spec,
        adapter,
        trace,
        judge_result,
        project_attribute_context=_build_project_attribute_context(spec, adapter, trace, judge_result),
    )
