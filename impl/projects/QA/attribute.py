from __future__ import annotations

from typing import Any

from impl.core.attribute_protocol import ProjectAttribute
from impl.core.runtime_query_tools import extract_runtime_values
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace, normalize_attribute_result, trace_execution_trace, trace_extracted_output
from impl.core.summary import summary_from_attribution


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _input_payload(request: dict[str, Any]) -> dict[str, Any]:
    payload = request.get("input") if isinstance(request.get("input"), dict) else request
    return payload if isinstance(payload, dict) else {}


def _answer_from(payload: dict[str, Any]) -> str:
    for key in ("actual_answer", "answer", "output", "text"):
        text = _as_text(payload.get(key))
        if text:
            return text
    return ""


def _qa_local_evidence_probe(trace: RunTrace, judge_result: JudgeResult, request: dict[str, Any], reference: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    input_payload = _input_payload(request)
    question = _as_text(input_payload.get("question"))
    contexts = input_payload.get("contexts") or request.get("contexts") or []
    if not isinstance(contexts, list):
        contexts = [contexts]
    reference_answer = _answer_from(reference)
    actual_answer = _answer_from(actual)
    reference_chars = {char for char in reference_answer if char.strip()}
    actual_chars = {char for char in actual_answer if char.strip()}
    overlap = len(reference_chars & actual_chars)
    coverage = round(overlap / len(reference_chars), 3) if reference_chars else None
    status = (judge_result.overall_fulfillment or {}).get("status") or ""
    return {
        "question_present": bool(question),
        "contexts_count": len([item for item in contexts if _as_text(item)]),
        "reference_answer_present": bool(reference_answer),
        "actual_answer_present": bool(actual_answer),
        "reference_actual_char_coverage": coverage,
        "judge_status": status,
        "fulfillment_assessment_count": len(judge_result.fulfillment_assessments or []),
        "evidence_gap": [
            name
            for name, missing in (
                ("question", not question),
                ("reference_answer", not reference_answer),
                ("actual_answer", not actual_answer),
                ("semantic_judge", status == "not_evaluable" and not (judge_result.fulfillment_assessments or [])),
            )
            if missing
        ],
    }


def _build_project_attribute_context(spec: ProjectSpec, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual = judge_result.actual or trace.extracted_output or {}
    local_probe = _qa_local_evidence_probe(trace, judge_result, request, reference, actual if isinstance(actual, dict) else {})
    return {
        "tool_call_limit": 3,
        "system_prompt_override": """你是 QA 项目的 attribute agent。
只基于当前 QA 样本的 question、provided contexts、reference answer、actual answer、qa_local_evidence_probe 和 semantic judge 结果归因；该项目没有外部 QA 服务调用，不能把失败归因到不存在的远端服务。
当 judge 为 not_evaluable 或本地 probe 显示缺少 reference/actual 语义证据时，不要编造根因，evidence_strength 设为 none 或 weak，并在 root_cause_hypothesis 说明缺失证据。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": ["input_normalization", "provided_context_selection", "answer_generation_or_provided_output", "semantic_judge"],
                "root_cause_policy": "先使用 qa_local_evidence_probe 判断当前样本是否缺 question/reference/actual/semantic judge 证据，再区分答案不相关、未覆盖 reference、事实不忠实或证据不足。",
                "evidence_contract": ["question", "provided_contexts", "reference_contract", "actual_answer", "qa_local_evidence_probe", "judge_result.fulfillment_assessments"],
                "service_boundary": "provided output only; no external QA service call is executed by this verifier project",
            },
            "question": str(((_input_payload(request)).get("question")) or ""),
            "reference_contract": reference,
            "actual_answer": actual,
            "qa_local_evidence_probe": local_probe,
        },
    }


def _build_attribute_context(trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    return {
        "chain_nodes_to_check": list(trace.execution_trace or []),
        "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
        "attribute_standard": "Only attribute QA failures when judge has current-case expected/actual evidence; provided output never calls an external QA service.",
    }


def _runtime_checks(trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    actual = judge_result.actual or trace_extracted_output(trace) or {}
    expected = judge_result.expected or trace.reference_contract or {}
    runtime_context = {
        "expected": expected,
        "actual": actual,
        "reference": trace.reference_contract or {},
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
    }
    extract_runtime_values(trace_execution_trace(trace), actual)
    _ = runtime_context
    return {}


def _patch_chinese_text_fields(attribute_result: AttributeResult) -> AttributeResult:
    en_to_zh = {
        "unsupported root-cause evidence": "根因证据不充分",
        "current case evidence does not support suspected locations or patch direction": "当前 case 证据不足以支撑疑似位置或补丁方向",
        "unsupported root-cause evidence:": "根因证据不充分：",
        "current case evidence does not support": "当前 case 证据不足以支撑",
        "suspected locations or patch direction": "疑似位置或补丁方向",
        "no_issue": "无问题",
        "needs_human_review": "需人工复核",
        "implementation_bug": "实现缺陷",
        "model_capability_gap": "模型能力缺陷",
        "boundary_limitation": "边界限制",
    }
    val = attribute_result.root_cause_hypothesis
    if val and isinstance(val, str):
        for en, zh in en_to_zh.items():
            val = val.replace(en, zh)
        attribute_result.root_cause_hypothesis = val
    for ea in (attribute_result.expectation_attributions or []):
        if not isinstance(ea, dict):
            continue
        for field in ("root_cause_hypothesis",):
            val = ea.get(field)
            if val and isinstance(val, str):
                for en, zh in en_to_zh.items():
                    val = val.replace(en, zh)
                ea[field] = val
    return attribute_result


def _blocked_attribute_result(trace: RunTrace, judge_result: JudgeResult, reason: str) -> AttributeResult:
    evidence = list(judge_result.evidence or [judge_result.reasoning_summary or reason])
    result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or ""),
        suspected_locations=[],
        evidence=evidence,
        evidence_strength="none",
        root_cause_hypothesis="当前证据不足以定位 QA 业务根因，需要语义 judge 或人工复核补足证据。",
    )
    result.summary = summary_from_attribution({
        "expectation_attributions": result.expectation_attributions,
        "root_cause_hypothesis": result.root_cause_hypothesis,
        "evidence_strength": result.evidence_strength,
    })
    return result


class QAAttribute(ProjectAttribute):
    """QA 项目 Attribute 实现（新协议）。"""

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        context = _build_attribute_context(trace, judge_result)
        context.update(_build_project_attribute_context(self.spec, trace, judge_result))
        context["runtime_checks"] = _runtime_checks(trace, judge_result)
        return context

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        result = normalize_attribute_result(result) or result
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status") or "not_evaluable"
        if status == "not_evaluable":
            reason = "QA judge 处于 not_evaluable 状态，缺少可用语义判定，不能产出正式失败归因。"
            return _blocked_attribute_result(trace, judge_result, reason)
        return _patch_chinese_text_fields(result)
