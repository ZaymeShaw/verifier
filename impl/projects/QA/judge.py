from __future__ import annotations

import re
from typing import Any, Dict, Optional

from impl.core.judge_protocol import ProjectJudge
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace, normalize_judge_result, to_dict


def _input_payload(request: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(request, dict):
        return {}
    nested = request.get("input")
    return nested if isinstance(nested, dict) else request


def _build_judge_context(spec: ProjectSpec, trace: RunTrace) -> dict:
    return {
        "project_type": "provided_output_qa_evaluation",
        "current_case_only": True,
        "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
        "score_dimensions": spec.frontend_extensions.get("score_dimensions") or [],
        "error_taxonomy": spec.frontend_extensions.get("error_taxonomy") or [],
        "application_boundary": {"scope": "qa_semantic_answer_evaluation", "external_service_required": False},
    }


def _build_intent_frame(spec: ProjectSpec, trace: RunTrace, context: Optional[dict] = None) -> dict:
    context = context or _build_judge_context(spec, trace)
    request = trace.normalized_request or {}
    sample_input = _input_payload(request)
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    contexts = sample_input.get("contexts") or []
    request_candidates = []
    for source_name in ("normalized_request", "input"):
        source_value = getattr(trace, source_name, None) or {}
        if isinstance(source_value, dict):
            for key in ("query", "user_intent", "question", "input"):
                value = source_value.get(key)
                if value:
                    request_candidates.append({"source": f"{source_name}.{key}", "value": value})
        elif source_value:
            request_candidates.append({"source": source_name, "value": source_value})
    return {
        "project_id": spec.project_id,
        "downstream_consumer": "QA user",
        "request_candidates": request_candidates,
        "boundary_hints": context.get("application_boundary") or {},
        "output_semantics": "produce an answer that addresses the current question and is faithful to provided contexts/reference when present",
        "business_task_type": "qa_answer_evaluation",
        "request_source": "normalized_request.input.question",
        "question": sample_input.get("question") or request.get("question") or "",
        "context_dependency": {"has_contexts": bool(contexts), "context_count": len(contexts), "has_reference": bool(reference)},
        "critical_intent_dimensions": ["question_target", "context_or_reference_dependency", "factual_or_interpretive_answer", "faithfulness", "contradiction_risk", "answer_usefulness"],
        "boundary_rules": {"scope": "qa_semantic_answer_evaluation", "external_service_required": False},
    }


def _build_core_context(spec: ProjectSpec, trace: RunTrace) -> dict:
    context = _build_judge_context(spec, trace)
    intent_frame = _build_intent_frame(spec, trace, context)
    critical_dimensions = intent_frame.get("critical_intent_dimensions") or context.get("critical_intent_dimensions")
    system_extras = []
    if critical_dimensions:
        system_extras.append(
            "## QA 评估关键维度\n"
            "请将 user prompt 中的 critical_intent_dimensions 作为拆分 business_expectations 的骨架，围绕当前问题、上下文/参考答案依赖、事实性、忠实性、矛盾风险和答案可用性判断 fulfillment。\n"
        )
    return {
        "user_intent": context.get("user_intent"),
        "intent_frame": intent_frame,
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "reference_contract": context.get("reference_contract") or {},
            "score_dimensions": context.get("score_dimensions") or [],
            "error_taxonomy": context.get("error_taxonomy") or [],
            "application_boundary": context.get("application_boundary") or {},
            "critical_intent_dimensions": critical_dimensions,
        }),
    }


def _scrub_placeholder_ids(judge_result: JudgeResult) -> JudgeResult:
    placeholder_patterns = [
        (r"\bE\d+\b", "编码失败项"),
        (r"\bexp[-_]?\d+\b", "编码失败项"),
    ]
    text_fields = ["reasoning_summary", "blocking_gaps", "why_verdict", "reasoning"]
    for field in text_fields:
        val = getattr(judge_result, field, None)
        if val and isinstance(val, str):
            for pat, replacement in placeholder_patterns:
                val = re.sub(pat, replacement, val)
            setattr(judge_result, field, val)
    for ca_list_attr in ("fulfillment_assessments",):
        ca_list = getattr(judge_result, ca_list_attr, []) or []
        for ca in ca_list:
            if not isinstance(ca, dict):
                continue
            for key in ("requirement", "downstream_impact", "evidence"):
                if key in ca and isinstance(ca[key], str):
                    for pat, replacement in placeholder_patterns:
                        ca[key] = re.sub(pat, replacement, ca[key])
            for key in ("evidence",):
                if key in ca and isinstance(ca[key], list):
                    ca[key] = [re.sub(pat, replacement, str(item)) for item in ca[key] for pat, replacement in placeholder_patterns]
    return judge_result


def _enrich_semantic_judge(trace: RunTrace, judge_result: JudgeResult, scenario: str) -> JudgeResult:
    request = trace.normalized_request or {}
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual = trace.extracted_output or judge_result.actual or {}
    question = str(_input_payload(request).get("question") or "")
    judge_result.expected = judge_result.expected or reference
    judge_result.actual = actual
    evidence = list(judge_result.evidence or [])
    case_evidence = [
        f"scenario={scenario or 'unknown'}",
        f"question_present={bool(question)}",
        f"actual_answer_present={bool((actual or {}).get('actual_answer'))}",
        f"reference_answer_present={bool((reference or {}).get('actual_answer'))}",
    ]
    for item in case_evidence:
        if item not in evidence:
            evidence.append(item)
    judge_result.evidence = evidence
    if not judge_result.fulfillment_assessments:
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status") or "not_evaluable"
        req_name = f"answer_quality_for_{scenario}" if scenario else "qa_answer_quality"
        judge_result.fulfillment_assessments = [{"expectation_id": req_name, "status": status, "expected_evidence": [reference], "actual_evidence": [actual], "downstream_impact": judge_result.reasoning_summary or "QA answer quality judged for current sample", "blocking": status == "not_fulfilled", "evidence_refs": []}]
    judge_result.reasoning_summary = judge_result.reasoning_summary or f"QA answer quality judged for current sample (scenario={scenario or 'unknown'})"
    return _scrub_placeholder_ids(judge_result)


def _expected_reference_from_judge(expected: Any) -> dict:
    if isinstance(expected, dict):
        value = expected.get("actual_answer") or expected.get("golden_answer") or expected.get("gold_answer") or expected.get("answer") or expected.get("text")
        if value:
            return {"actual_answer": str(value)}
    if isinstance(expected, str) and expected.strip():
        return {"actual_answer": expected.strip()}
    return {}


def _generate_reference(request: dict, actual_text: str, contexts: list, scenario: str) -> dict:
    question = str(_input_payload(request).get("question") or "").strip()
    if scenario == "qa_context_faithfulness" and contexts:
        context_text = " ".join(str(ctx).strip() for ctx in contexts if str(ctx).strip())
        if context_text:
            return {"actual_answer": context_text}
    if question:
        return {"actual_answer": f'需要围绕问题"{question}"生成可核验的参考答案；当前样本未提供参考回答，不能把 actual_answer 直接当作参考答案。'}
    return {}


def _fallback_judge_from_sample_label(trace: RunTrace, judge_result: JudgeResult, expected_reference: dict, actual: dict, scenario: str, metadata: dict, data_quality_flags: list) -> Optional[JudgeResult]:
    expected_quality = str(metadata.get("expected_quality") or trace.input.get("expected_quality") or "")
    if expected_quality not in {"correct", "incorrect"} or data_quality_flags:
        return None
    if scenario == "qa_weak_quality":
        return None
    error_type = str(metadata.get("expected_error_type") or "")
    is_correct = expected_quality == "correct"
    status = "fulfilled" if is_correct else "not_fulfilled"
    evidence = [
        f"scenario={scenario or 'unknown'}",
        f"expected_quality={expected_quality}",
        f"expected_error_type={error_type or 'none'}",
        "sample_label_source=metadata.expected_quality",
    ]
    judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
        "expectation_id": "QA:sample_expected_quality", "status": status,
        "expected_evidence": [expected_reference], "actual_evidence": [actual],
        "downstream_impact": "QA answer is acceptable for the current user" if is_correct else "QA user cannot rely on the answer quality for this sample",
        "blocking": not is_correct, "evidence_refs": [],
    }]
    judge_result.expected = expected_reference
    judge_result.actual = actual
    judge_result.missing = []
    judge_result.wrong = [] if is_correct else [{"requirement": "QA:answer_quality", "error_type": error_type or "answer_incorrect"}]
    judge_result.extra = []
    judge_result.evidence = evidence
    judge_result.reasoning_summary = "QA seeded mock sample expected_quality label used because semantic LLM judge was unavailable."
    return judge_result


def _fallback_judge_from_sample_label_forced(trace: RunTrace, judge_result: JudgeResult, expected_reference: dict, actual: dict, scenario: str, metadata: dict, expected_quality: str) -> Optional[JudgeResult]:
    return _fallback_judge_from_sample_label(trace, judge_result, expected_reference, actual, scenario, metadata, [])


def _fallback_judge(trace: RunTrace, judge_result: JudgeResult) -> Optional[JudgeResult]:
    actual = trace.extracted_output or {}
    actual_text = str(actual.get("actual_answer") or "").strip()
    request = trace.normalized_request or {}
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    golden_text = str(reference.get("actual_answer") or "").strip()
    contexts = list(_input_payload(request).get("contexts") or [])
    scenario = str(trace.scenario or request.get("scenario") or "")
    if scenario not in {"qa_gold_answer", "qa_context_faithfulness", "qa_weak_quality", "invalid_sample"}:
        return None
    expected_reference = reference or _expected_reference_from_judge(judge_result.expected) or _generate_reference(request, actual_text, contexts, scenario)
    metadata = dict(request.get("metadata") or {})
    labeled = _fallback_judge_from_sample_label(trace, judge_result, expected_reference, actual, scenario, metadata, [])
    if labeled:
        return labeled
    reason = "QA 本地 fallback 只记录样本证据完整性；语义正确性必须由 LLM judge 或人工复核判定。"
    judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
        "expectation_id": "QA:local_evidence_probe",
        "status": "not_evaluable",
        "expected_evidence": [expected_reference],
        "actual_evidence": [actual],
        "downstream_impact": reason,
        "blocking": False,
    }]
    judge_result.expected = expected_reference
    judge_result.actual = actual
    judge_result.missing = []
    judge_result.wrong = []
    judge_result.extra = []
    judge_result.evidence = [
        f"scenario={scenario or 'unknown'}",
        f"actual_answer_present={bool(actual_text)}",
        f"reference_answer_present={bool(golden_text)}",
        f"contexts_present={bool(contexts)}",
    ]
    judge_result.reasoning_summary = reason
    return judge_result


def _weak_quality_probe(trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    actual = trace.extracted_output or {}
    request = trace.normalized_request or {}
    reason = "qa_weak_quality 没有 reference 或 contexts，只能作为质量估计样本，不能产出正式语义正确/错误判定。"
    judge_result.actual = actual
    judge_result.expected = judge_result.expected or _generate_reference(request, str(actual.get("actual_answer") or ""), [], "qa_weak_quality")
    judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [{
        "expectation_id": "QA:weak_quality_probe",
        "status": "not_evaluable",
        "blocking": False,
        "evidence": [reason],
        "downstream_impact": reason,
    }]
    judge_result.missing = []
    judge_result.wrong = []
    judge_result.extra = []
    judge_result.reasoning_summary = reason
    return judge_result


def _gold_answer_exact_probe(trace: RunTrace, judge_result: JudgeResult) -> Optional[JudgeResult]:
    actual = trace.extracted_output or judge_result.actual or {}
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual_text = str((actual or {}).get("actual_answer") or "").strip()
    golden_text = str((reference or {}).get("actual_answer") or "").strip()
    if not actual_text or not golden_text or actual_text != golden_text:
        return None
    evidence = [
        "scenario=qa_gold_answer",
        "reference_exact_match=True",
        f"actual_length={len(actual_text)}",
        f"reference_length={len(golden_text)}",
    ]
    judge_result.fulfillment_assessments = list(judge_result.fulfillment_assessments or []) + [
        {"expectation_id": "QA:gold_answer_exact_match", "status": "fulfilled",
         "expected_evidence": [reference], "actual_evidence": [actual],
         "downstream_impact": "用户获得了完整准确的答案", "blocking": False, "evidence_refs": []},
    ]
    judge_result.expected = reference
    judge_result.actual = actual
    judge_result.missing = []
    judge_result.wrong = []
    judge_result.extra = []
    judge_result.evidence = evidence
    judge_result.reasoning_summary = "actual_answer 与 reference.actual_answer 完全一致，当前 QA 样本业务预期已达成。"
    return judge_result


class QAJudge(ProjectJudge):
    """QA 项目 Judge 实现（新协议）。"""

    def build_context(self, trace: RunTrace) -> dict:
        return _build_core_context(self.spec, trace)

    def build_intent_frame(self, trace: RunTrace, context: Optional[dict] = None) -> dict:
        return _build_intent_frame(self.spec, trace, context)

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        judge_result = normalize_judge_result(result) or result
        scenario = str(trace.scenario or (trace.normalized_request or {}).get("scenario") or "")
        if scenario == "qa_gold_answer":
            exact = _gold_answer_exact_probe(trace, judge_result)
            if exact:
                return exact
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status")
        if scenario == "qa_weak_quality" and status in {"fulfilled", "not_fulfilled"}:
            return _weak_quality_probe(trace, judge_result)
        if status == "not_evaluable":
            metadata = dict((trace.normalized_request or {}).get("metadata") or {})
            expected_quality = metadata.get("expected_quality") or "uncertain"
            if expected_quality in ("correct", "incorrect"):
                expected_reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
                actual = trace.extracted_output or judge_result.actual or {}
                judge_result.expected = expected_reference
                judge_result.actual = actual
                fallback = _fallback_judge_from_sample_label_forced(
                    trace, judge_result, expected_reference, actual, scenario, metadata, expected_quality
                )
                if fallback:
                    return fallback
        if status in {"fulfilled", "not_fulfilled", "not_evaluable"}:
            return _enrich_semantic_judge(trace, judge_result, scenario)
        fallback = _fallback_judge(trace, judge_result)
        if not fallback:
            return _scrub_placeholder_ids(judge_result)
        return _scrub_placeholder_ids(fallback)
