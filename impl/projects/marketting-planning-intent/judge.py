from __future__ import annotations

from typing import Any, Dict, Optional

from impl.core.judge_protocol import run_project_judge_protocol
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace, to_dict


def application_boundary_from_trace(trace: RunTrace) -> dict[str, Any]:
    live_result = getattr(trace, "live_result", None)
    if live_result and isinstance(getattr(live_result, "application_boundary", None), dict) and live_result.application_boundary:
        return live_result.application_boundary
    empty_boundary: dict[str, Any] = {}
    return empty_boundary


def build_judge_context(trace: RunTrace) -> Dict[str, Any]:
    reference_contract = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    expected_intent = reference_contract.get("intent") or (trace.normalized_request or {}).get("expected_intent")
    return {
        "project_type": "single_turn_marketing_intent_recognition",
        "current_case_only": True,
        "reference_contract": reference_contract,
        "expected_intent": expected_intent,
        "application_boundary": application_boundary_from_trace(trace),
        "critical_intent_dimensions": ["intent_label", "required_slots_or_entities", "confidence_threshold", "fallback_policy", "dispatch_boundary"],
    }


def build_intent_frame(trace: RunTrace) -> Dict[str, Any]:
    context = build_judge_context(trace)
    return {
        "project_id": trace.project_id,
        "downstream_consumer": "marketing intent router",
        "request_candidates": [
            {"source": f"{source_name}.{key}", "value": value}
            for source_name in ("normalized_request", "input")
            for source_value in [getattr(trace, source_name, None) or {}]
            if isinstance(source_value, dict)
            for key in ("query", "user_intent", "question", "input")
            for value in [source_value.get(key)]
            if value
        ],
        "boundary_hints": context.get("application_boundary") or {},
        "output_semantics": "resolve the current user query to a safe marketing-planning intent label and required slots before planning dispatch",
        "business_task_type": "single_turn_marketing_intent_recognition",
        "critical_intent_dimensions": ["intent_label", "required_slots_or_entities", "confidence_threshold", "fallback_policy", "dispatch_boundary"],
        "expected_intent": context.get("expected_intent"),
        "reference_contract": context.get("reference_contract") or {},
        "boundary_rules": context.get("application_boundary") or {},
    }


def reference_output(reference: Dict[str, Any], trace: RunTrace) -> Dict[str, Any]:
    output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
    confidence = reference.get("confidence") if reference.get("confidence") is not None else reference.get("min_confidence")
    if confidence is None:
        confidence = output.get("confidence") if output.get("confidence") is not None else 1.0
    path_types = reference.get("path_types") if reference.get("path_types") is not None else reference.get("required_path_types")
    return {
        "intent": str(reference.get("intent") or (trace.normalized_request or {}).get("expected_intent") or "unknown"),
        "confidence": float(confidence) if isinstance(confidence, (int, float)) else 1.0,
        "target_value": reference.get("target_value") if reference.get("target_value") is not None else output.get("target_value"),
        "path_types": path_types if isinstance(path_types, list) else output.get("path_types"),
        "subIntent": reference.get("subIntent") if reference.get("subIntent") is not None else output.get("subIntent"),
    }


def intent_contract_reasoning_summary(trace: RunTrace, reference: Dict[str, Any], output: Dict[str, Any], missing: list[Any], wrong: list[Any], verdict: str) -> str:
    query = trace.input.get("query") or (trace.input.get("input") or {}).get("query") if isinstance(trace.input, dict) else ""
    expected_intent = reference.get("intent")
    actual_intent = output.get("intent")
    confidence = output.get("confidence")
    min_confidence = reference.get("min_confidence")
    if verdict == "correct":
        return f"当前单轮意图识别满足 reference contract：intent={actual_intent}，confidence={confidence} 达到最低要求 {min_confidence}。"
    failed = []
    for item in list(missing or []) + list(wrong or []):
        if isinstance(item, dict):
            failed.append(str(item.get("requirement") or item.get("status") or item))
    return f"当前单轮意图识别未满足 reference contract：query={query}，expected_intent={expected_intent}，actual_intent={actual_intent}，confidence={confidence}，min_confidence={min_confidence}，失败项={failed}，整体判定为 incorrect。"


def normalize_judge_result(trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    if not isinstance(reference, dict):
        reference = {"intent": reference}
    output = trace.extracted_output or {}
    if not judge_result.expected:
        if reference:
            judge_result.expected = reference_output(reference, trace)
        elif output:
            judge_result.expected = output
    missing = list(judge_result.missing or [])
    wrong = list(judge_result.wrong or [])
    expected_intent = reference.get("intent") or (trace.normalized_request or {}).get("expected_intent")
    actual_intent = output.get("intent")
    if expected_intent and actual_intent != expected_intent:
        wrong.append({"requirement": "intent", "expected_fragment": expected_intent, "actual_fragment": actual_intent, "status": "wrong", "evidence": ["normalized intent differs from reference intent"]})
    slots = (trace.project_fields or {}).get("intent_evidence", {}).get("slots") if isinstance(trace.project_fields, dict) else {}
    if not isinstance(slots, dict):
        slots = {}
    entities = (trace.project_fields or {}).get("intent_evidence", {}).get("entities") if isinstance(trace.project_fields, dict) else []
    if not isinstance(entities, list):
        entities = []
    required_slots = list(reference.get("required_slots") or reference.get("required_entities") or [])
    absent_slots = [slot for slot in required_slots if slot not in slots and slot not in {entity.get("type") for entity in entities if isinstance(entity, dict)}]
    if absent_slots:
        missing.append({"requirement": "required_slots", "expected_fragment": absent_slots, "actual_fragment": slots, "status": "missing", "evidence": ["required slot/entity absent from normalized intent evidence"]})
    evidence = (trace.project_fields or {}).get("intent_evidence", {}) if isinstance(trace.project_fields, dict) else {}
    allow_fallback = bool(reference.get("allow_fallback"))
    if not allow_fallback and (evidence.get("fallback") or evidence.get("ambiguous") or str(actual_intent or "").lower() in {"unknown", "fallback"}):
        wrong.append({"requirement": "allow_fallback", "expected_fragment": False, "actual_fragment": {"fallback": evidence.get("fallback"), "ambiguous": evidence.get("ambiguous"), "intent": actual_intent}, "status": "wrong", "evidence": ["fallback/unknown/ambiguous intent is not allowed by reference"]})
    min_confidence = reference.get("min_confidence")
    confidence = output.get("confidence")
    if min_confidence is not None and confidence is not None and float(confidence) < float(min_confidence):
        wrong.append({"requirement": "min_confidence", "expected_fragment": min_confidence, "actual_fragment": confidence, "status": "wrong", "evidence": ["intent confidence is below reference threshold"]})
    judge_result.missing = missing
    judge_result.wrong = wrong
    judge_result.actual = output
    judge_result.expected = reference_output(reference, trace) if reference else judge_result.expected
    blocking_wrong = [item for item in wrong if isinstance(item, dict) and item.get("requirement") in {"intent", "allow_fallback", "min_confidence"}]
    gate_failed = bool(missing or blocking_wrong)
    if gate_failed:
        evidence_summary = {
            "missing": [item.get("requirement") for item in missing if isinstance(item, dict)],
            "blocking_wrong": [item.get("requirement") for item in blocking_wrong if isinstance(item, dict)],
        }
        evidence_str = f"missing={evidence_summary.get('missing')}; blocking_wrong={evidence_summary.get('blocking_wrong')}"
        judge_result.fulfillment_assessments.append({
            "expectation_id": "intent_contract",
            "status": "not_fulfilled",
            "blocking": True,
            "evidence": evidence_str,
            "downstream_impact": intent_contract_reasoning_summary(trace, reference, output, missing, wrong, "incorrect"),
        })
        judge_result.overall_fulfillment = {"status": "not_fulfilled", "blocking_expectations": ["intent_contract"]}
        judge_result.reasoning_summary = intent_contract_reasoning_summary(trace, reference, output, missing, wrong, "incorrect")
        return judge_result
    judge_result.fulfillment_assessments.append({
        "expectation_id": "intent_contract",
        "status": "fulfilled",
        "blocking": True,
        "evidence": f"intent={actual_intent}; confidence={confidence}; min_confidence={min_confidence}",
        "downstream_impact": intent_contract_reasoning_summary(trace, reference, output, [], [], "correct"),
    })
    judge_result.reasoning_summary = judge_result.reasoning_summary or intent_contract_reasoning_summary(trace, reference, output, [], [], "correct")
    judge_result.overall_fulfillment = judge_result.overall_fulfillment or {"status": "fulfilled", "blocking_expectations": []}
    return judge_result


def reconcile_judge_result(trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    return judge_result


def pre_judge_result(trace: RunTrace, expected_intent: Optional[str] = None) -> Optional[JudgeResult]:
    return None


def _build_core_context(trace: RunTrace) -> dict:
    context = build_judge_context(trace) or {}
    intent_frame = build_intent_frame(trace)
    critical_dimensions = intent_frame.get("critical_intent_dimensions") or context.get("critical_intent_dimensions")
    system_extras = []
    if critical_dimensions:
        system_extras.append(
            "## marketing-planning-intent 评估关键维度\n"
            "请将 user prompt 中的 critical_intent_dimensions 作为拆分 business_expectations 的骨架，围绕 intent label、必需 slots/entities、置信度阈值、fallback 策略和 dispatch 边界判断 fulfillment。\n"
        )
    return {
        "expected_intent": context.get("expected_intent"),
        "intent_frame": intent_frame,
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "reference_contract": context.get("reference_contract") or {},
            "application_boundary": context.get("application_boundary") or {},
            "critical_intent_dimensions": critical_dimensions,
        }),
    }


# spec/info-volume.md：marketing-planning-intent 的 judge 策略属于项目层；core.judge 只保留通用 fulfillment 协议。
def judge_trace(spec: ProjectSpec, adapter, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    return run_project_judge_protocol(
        spec,
        adapter,
        trace,
        expected_intent=expected_intent,
        project_judge_context=_build_core_context(trace),
    )


from impl.core.judge_protocol import ProjectJudge


class MarketingIntentJudge(ProjectJudge):
    """marketting-planning-intent 项目 Judge 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_context(self, trace: RunTrace) -> dict:
        return _build_core_context(trace)

    def build_intent_frame(self, trace: RunTrace, context: Optional[dict] = None) -> dict:
        return build_intent_frame(trace)

    def pre_judge(self, trace: RunTrace, expected_intent: Optional[str] = None) -> Optional[JudgeResult]:
        return pre_judge_result(trace, expected_intent=expected_intent)

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        from impl.core.schema import normalize_judge_result as normalize_core_judge_result
        return normalize_core_judge_result(normalize_judge_result(trace, result)) or result

    def reconcile_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        return reconcile_judge_result(trace, result)
