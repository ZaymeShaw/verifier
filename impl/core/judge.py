from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .llm_client import LlmClient
from .project_loader import load_project_document
from .schema import JudgeResult, ProjectSpec, RunTrace


def _extract_boundary_value(text: str, key: str) -> str:
    prefix = f"{key}:"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip().strip('"\'')
    return ""


def _line_after_label(text: str, label: str) -> str:
    prefix = f"{label}："
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return ""


def _fallback_evaluation_boundary(judge_boundary: str) -> Dict[str, Any]:
    verdict_standard = _line_after_label(judge_boundary, "判题目标") or _line_after_label(judge_boundary, "最终评估口径")
    limitation = _line_after_label(judge_boundary, "限制")
    evaluation_scope = _line_after_label(judge_boundary, "评价范围")
    boundary_sources = _line_after_label(judge_boundary, "边界依据") or _line_after_label(judge_boundary, "能力边界依据") or _line_after_label(judge_boundary, "边界来源")
    out_of_boundary_policy = _line_after_label(judge_boundary, "出界处理")
    project_boundary_notes = _line_after_label(judge_boundary, "项目边界说明")
    explanation_parts = [part for part in [limitation, evaluation_scope, out_of_boundary_policy, project_boundary_notes] if part]
    explanation = "\n".join(explanation_parts) or _line_after_label(judge_boundary, "口径说明") or _line_after_label(judge_boundary, "冲突处理")
    conflict_policy = _line_after_label(judge_boundary, "冲突处理") or out_of_boundary_policy or evaluation_scope or project_boundary_notes
    return {
        "primary_boundary_id": _extract_boundary_value(judge_boundary, "id") or "project_verdict_standard",
        "primary_boundary_name": verdict_standard or _extract_boundary_value(judge_boundary, "name") or "项目最终评估口径",
        "judge_question": _extract_boundary_value(judge_boundary, "final_verdict_question") or _extract_boundary_value(judge_boundary, "judge_question") or explanation,
        "verdict_basis": explanation or "fallback_from_project_judge_boundary",
        "boundary_sources": boundary_sources,
        "conflict_policy": conflict_policy,
    }


def _fallback_primary_assessment(boundary: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "boundary_id": boundary.get("primary_boundary_id") or "project_primary_boundary",
        "score": data.get("score"),
        "covered": [],
        "missing": list(data.get("missing") or []),
        "wrong": list(data.get("wrong") or []),
        "reasoning": str(data.get("reasoning_summary") or "judge 未返回口径内判断明细，已按项目最终评估口径补齐结构。"),
    }


def _trace_reference(trace: RunTrace) -> Any:
    input_data = trace.input or {}
    if input_data.get("reference") is not None:
        return input_data.get("reference")
    if trace.project_fields and trace.project_fields.get("reference"):
        return trace.project_fields.get("reference")
    request = trace.normalized_request or {}
    if request.get("reference"):
        return request.get("reference")
    return None


def _has_input_reference(trace: RunTrace) -> bool:
    return _trace_reference(trace) is not None


def _reference_text(data: Dict[str, Any]) -> str:
    return str(data.get("reconstructed_intent") or data.get("reasoning_summary") or data.get("judge_basis") or "需覆盖当前输入可评估需求的核心要点。")


def _reference_scalar(reference: Any, data: Dict[str, Any]) -> Any:
    if isinstance(reference, dict):
        for value in reference.values():
            if isinstance(value, (str, int, float, bool)) and str(value):
                return value
        return _reference_text(data)
    return reference


def _first_list_value(data: Any) -> Any:
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, list):
            return value
    return None


def _first_list_key(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    for key, value in data.items():
        if isinstance(value, list):
            return key
    return None


def _align_reference_shape(reference: Any, actual: Any, data: Dict[str, Any]) -> Any:
    if reference is None:
        reference = _reference_text(data)
    if isinstance(actual, dict):
        if isinstance(reference, dict):
            if set(actual).intersection(reference):
                return reference
            list_key = _first_list_key(actual)
            list_value = _first_list_value(reference)
            if list_key and list_value is not None:
                shaped = {key: actual.get(key) for key in actual}
                shaped[list_key] = list_value
                for key in shaped:
                    if isinstance(shaped.get(key), str) and isinstance(reference.get(key), str):
                        shaped[key] = reference.get(key)
                return shaped
        scalar = _reference_scalar(reference, data)
        string_keys = [key for key, value in actual.items() if isinstance(value, str)]
        if string_keys:
            return {string_keys[0]: str(scalar)}
        return {key: scalar if isinstance(actual.get(key), str) else actual.get(key) for key in actual}
    if isinstance(actual, list):
        return reference if isinstance(reference, list) else [reference]
    return reference


def _generated_expected(trace: RunTrace, data: Dict[str, Any], actual: Any) -> Any:
    output_shape = trace.extracted_output or actual
    provided = _trace_reference(trace)
    if provided is not None:
        return _align_reference_shape(provided, output_shape, data)
    expected = data.get("expected")
    if expected is not None:
        return _align_reference_shape(expected, output_shape, data)
    return _align_reference_shape(None, output_shape, data)


def judge_trace(spec: ProjectSpec, trace: RunTrace, expected_intent: Optional[str] = None, llm: Optional[LlmClient] = None) -> JudgeResult:
    evaluation = load_project_document(spec, "evaluation")
    judge_boundary = load_project_document(spec, "judge_boundary")
    judge_standard = load_project_document(spec, "judge_standard")
    source_readme = load_project_document(spec, "source_readme")
    source_config = load_project_document(spec, "source_config")
    source_prompt = load_project_document(spec, "source_prompt")
    source_judge_boundary = load_project_document(spec, "source_judge_boundary")
    system = "你是通用评估系统的 judge agent。只基于当前 RunTrace、项目评判标准和项目源文档判断，不继承历史 case。按项目文档定义的业务口径判断 expected-vs-actual；证据不足时返回 uncertain。分析文字尽量使用中文，输出 JSON。"
    user = json.dumps(
        {
            "evaluation_spec": evaluation,
            "judge_boundary_spec": judge_boundary,
            "judge_standard": judge_standard,
            "project_source_references": {
                "readme_md": source_readme,
                "config_md": source_config,
                "prompt_md": source_prompt,
                "judge_boundary_standard": source_judge_boundary,
            },
            "expected_intent": expected_intent,
            "run_trace": trace.__dict__,
            "required_output": {
                "verdict": "correct|incorrect|uncertain",
                "score": "number|null",
                "confidence": "number|null",
                "probability": "number|null",
                "reconstructed_intent": "string",
                "judge_basis": "string",
                "expected": "object|array|string|null. If the input/case has no reference answer, reconstruct a reference in the same general shape as actual.",
                "actual": "object|array|string|null",
                "boundary_decision": {
                    "within_evaluable_scope": "boolean|null",
                    "uncontrollable_limits": [],
                    "evaluable_errors": [],
                    "reasoning": "string",
                },
                "evaluation_boundary": {
                    "primary_boundary_id": "string",
                    "primary_boundary_name": "string",
                    "judge_question": "string",
                    "verdict_basis": "string",
                    "boundary_sources": "string",
                    "conflict_policy": "string",
                },
                "primary_assessment": {
                    "boundary_id": "string",
                    "score": "number|null",
                    "covered": [],
                    "missing": [],
                    "wrong": [],
                    "reasoning": "string",
                },
                "contrast_assessments": [],
                "missing": [],
                "wrong": [],
                "extra": [],
                "evidence": [],
                "reasoning_summary": "string",
                "score_details": [
                    {"name": "string", "score": "number", "weight": "number|null", "reason": "string"}
                ],
                "needs_human_review": "boolean|null",
                "scenario": "string",
                "quality_flags": [],
            },
        },
        ensure_ascii=False,
    )
    data = (llm or LlmClient()).complete_json(system, user)
    if data.get("error"):
        boundary = _fallback_evaluation_boundary(judge_boundary)
        error_text = data.get("raw_text") or data.get("error")
        return JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="uncertain",
            evaluation_boundary=boundary,
            primary_assessment=_fallback_primary_assessment(boundary, {"reasoning_summary": error_text}),
            judge_basis="llm_call_failed",
            boundary_decision={"within_evaluable_scope": None, "reasoning": error_text},
            evidence=[error_text],
            quality_flags=["llm_call_failed"],
            raw_model_output=data,
        )
    evidence = list(data.get("evidence") or [])
    if not evidence and data.get("reasoning_summary"):
        evidence = [str(data.get("reasoning_summary"))]
    boundary = dict(data.get("evaluation_boundary") or {})
    if not boundary:
        boundary = _fallback_evaluation_boundary(judge_boundary)
    primary_assessment = dict(data.get("primary_assessment") or {})
    if not primary_assessment:
        primary_assessment = _fallback_primary_assessment(boundary, data)
    actual = data.get("actual")
    expected = _generated_expected(trace, data, actual)
    return JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        verdict=str(data.get("verdict") or "uncertain"),
        score=data.get("score"),
        confidence=data.get("confidence"),
        probability=data.get("probability"),
        expected=expected,
        actual=actual,
        reconstructed_intent=str(data.get("reconstructed_intent") or ""),
        judge_basis=str(data.get("judge_basis") or ""),
        boundary_decision=dict(data.get("boundary_decision") or {}),
        evaluation_boundary=boundary,
        primary_assessment=primary_assessment,
        contrast_assessments=list(data.get("contrast_assessments") or []),
        missing=list(data.get("missing") or []),
        wrong=list(data.get("wrong") or []),
        extra=list(data.get("extra") or []),
        evidence=evidence,
        reasoning_summary=str(data.get("reasoning_summary") or ""),
        score_details=list(data.get("score_details") or []),
        needs_human_review=data.get("needs_human_review"),
        scenario=str(data.get("scenario") or trace.project_fields.get("scenario") or ""),
        quality_flags=list(data.get("quality_flags") or []),
        raw_model_output=data,
    )
