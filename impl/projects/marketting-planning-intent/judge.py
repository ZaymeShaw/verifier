from __future__ import annotations

from typing import Any, Dict, Optional

from impl.core.schema import (
    FulfillmentAssessment,
    JudgeResult,
    ProjectSpec,
    RunTrace,
    to_dict,
)
from impl.core.judge import ensure_business_expectation


_INTENT_CONTRACT_EXPECTATION_ID = "intent_contract"
_INTENT_CONTRACT_GAP_SOURCE = "marketting_planning_intent_contract"


def application_boundary_from_trace(trace: RunTrace) -> dict[str, Any]:
    from impl.core.schema import trace_application_boundary
    boundary = trace_application_boundary(trace)
    if boundary:
        return boundary
    empty_boundary: dict[str, Any] = {}
    return empty_boundary


def build_judge_context(trace: RunTrace) -> Dict[str, Any]:
    reference_contract = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    user_intent = reference_contract.get("intent") or (trace.normalized_request or {}).get("user_intent")
    return {
        "project_type": "single_turn_marketing_intent_recognition",
        "current_case_only": True,
        "reference_contract": reference_contract,
        "user_intent": user_intent,
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
        "user_intent": context.get("user_intent"),
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
        "intent": str(reference.get("intent") or (trace.normalized_request or {}).get("user_intent") or "unknown"),
        "confidence": float(confidence) if isinstance(confidence, (int, float)) else 1.0,
        "target_value": reference.get("target_value") if reference.get("target_value") is not None else output.get("target_value"),
        "path_types": path_types if isinstance(path_types, list) else output.get("path_types"),
        "subIntent": reference.get("subIntent") if reference.get("subIntent") is not None else output.get("subIntent"),
    }


def _contract_gap(
    *,
    kind: str,
    requirement: str,
    expected: Any,
    actual: Any,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "error_type": kind,
        "expected": expected,
        "actual": actual,
        "raw": {
            "source": _INTENT_CONTRACT_GAP_SOURCE,
            "requirement": requirement,
        },
    }


def _is_project_contract_gap(item: Any) -> bool:
    raw = item.get("raw") if isinstance(item, dict) else getattr(item, "raw", None)
    return isinstance(raw, dict) and raw.get("source") == _INTENT_CONTRACT_GAP_SOURCE


def _contract_gap_requirement(item: Any) -> str:
    raw = item.get("raw") if isinstance(item, dict) else getattr(item, "raw", None)
    return str(raw.get("requirement") or "") if isinstance(raw, dict) else ""


def _upsert_intent_contract_assessment(
    judge_result: JudgeResult,
    assessment: FulfillmentAssessment,
) -> None:
    retained = [
        item
        for item in (judge_result.fulfillment_assessments or [])
        if str(item.get("expectation_id") if isinstance(item, dict) else getattr(item, "expectation_id", ""))
        != _INTENT_CONTRACT_EXPECTATION_ID
    ]
    judge_result.fulfillment_assessments = [*retained, assessment]


def intent_contract_reasoning_summary(trace: RunTrace, reference: Dict[str, Any], output: Dict[str, Any], missing: list[Any], wrong: list[Any], verdict: str) -> str:
    query = trace.input.get("query") or (trace.input.get("input") or {}).get("query") if isinstance(trace.input, dict) else ""
    expected_intent = reference.get("intent")
    actual_intent = output.get("intent")
    confidence = output.get("confidence")
    min_confidence = reference.get("min_confidence")
    if verdict == "correct":
        return f"当前单轮意图识别满足 reference contract：intent={actual_intent}，confidence={confidence} 达到最低要求 {min_confidence}。"
    failed = [
        requirement
        for item in list(missing or []) + list(wrong or [])
        for requirement in [_contract_gap_requirement(item)]
        if requirement
    ]
    return f"当前单轮意图识别未满足 reference contract：query={query}，user_intent={expected_intent}，actual_intent={actual_intent}，confidence={confidence}，min_confidence={min_confidence}，失败项={failed}，整体判定为 incorrect。"


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
    # LLM gaps 只用于展示和归因。项目硬门仅由下面重新计算的确定性
    # contract gaps 驱动；先移除旧的项目 gaps，保证重复 normalize 幂等。
    llm_missing = [item for item in (judge_result.missing or []) if not _is_project_contract_gap(item)]
    llm_wrong = [item for item in (judge_result.wrong or []) if not _is_project_contract_gap(item)]
    contract_missing: list[dict[str, Any]] = []
    contract_wrong: list[dict[str, Any]] = []
    expected_intent = reference.get("intent") or (trace.normalized_request or {}).get("user_intent")
    actual_intent = output.get("intent")
    if expected_intent and actual_intent != expected_intent:
        contract_wrong.append(_contract_gap(
            kind="wrong",
            requirement="intent",
            expected=expected_intent,
            actual=actual_intent,
        ))
    slots = (trace.project_fields or {}).get("intent_evidence", {}).get("slots") if isinstance(trace.project_fields, dict) else {}
    if not isinstance(slots, dict):
        slots = {}
    entities = (trace.project_fields or {}).get("intent_evidence", {}).get("entities") if isinstance(trace.project_fields, dict) else []
    if not isinstance(entities, list):
        entities = []
    required_slots = list(reference.get("required_slots") or reference.get("required_entities") or [])
    absent_slots = [slot for slot in required_slots if slot not in slots and slot not in {entity.get("type") for entity in entities if isinstance(entity, dict)}]
    if absent_slots:
        contract_missing.append(_contract_gap(
            kind="missing",
            requirement="required_slots",
            expected=absent_slots,
            actual={
                "slots": slots,
                "entity_types": [
                    entity.get("type")
                    for entity in entities
                    if isinstance(entity, dict) and entity.get("type")
                ],
            },
        ))
    evidence = (trace.project_fields or {}).get("intent_evidence", {}) if isinstance(trace.project_fields, dict) else {}
    allow_fallback = bool(reference.get("allow_fallback"))
    if not allow_fallback and (evidence.get("fallback") or evidence.get("ambiguous") or str(actual_intent or "").lower() in {"unknown", "fallback"}):
        contract_wrong.append(_contract_gap(
            kind="wrong",
            requirement="allow_fallback",
            expected=False,
            actual={
                "fallback": evidence.get("fallback"),
                "ambiguous": evidence.get("ambiguous"),
                "intent": actual_intent,
            },
        ))
    min_confidence = reference.get("min_confidence")
    confidence = output.get("confidence")
    if min_confidence is not None:
        if confidence is None:
            contract_missing.append(_contract_gap(
                kind="missing",
                requirement="confidence",
                expected=min_confidence,
                actual=None,
            ))
        elif float(confidence) < float(min_confidence):
            contract_wrong.append(_contract_gap(
                kind="wrong",
                requirement="min_confidence",
                expected=min_confidence,
                actual=confidence,
            ))
    judge_result.missing = [*llm_missing, *contract_missing]
    judge_result.wrong = [*llm_wrong, *contract_wrong]
    judge_result.actual = output
    judge_result.expected = reference_output(reference, trace) if reference else judge_result.expected
    gate_failed = bool(contract_missing or contract_wrong)
    ensure_business_expectation(
        judge_result,
        _INTENT_CONTRACT_EXPECTATION_ID,
        blocking=True,
        expected_outcome="识别符合项目契约的意图、必需槽位、fallback 边界和最低置信度",
        acceptance_criteria=["intent 匹配", "必需槽位齐全", "fallback 合法", "confidence 达标"],
        downstream_consumer="营销规划意图路由",
    )
    if gate_failed:
        reasoning = intent_contract_reasoning_summary(
            trace,
            reference,
            output,
            contract_missing,
            contract_wrong,
            "incorrect",
        )
        _upsert_intent_contract_assessment(
            judge_result,
            FulfillmentAssessment(
                expectation_id=_INTENT_CONTRACT_EXPECTATION_ID,
                status="not_fulfilled",
                expected_evidence=[
                    {
                        "intent": expected_intent,
                        "required_slots": required_slots,
                        "allow_fallback": allow_fallback,
                        "min_confidence": min_confidence,
                    }
                ],
                actual_evidence=[
                    {
                        "intent": actual_intent,
                        "slots": slots,
                        "entities": entities,
                        "fallback": evidence.get("fallback"),
                        "ambiguous": evidence.get("ambiguous"),
                        "confidence": confidence,
                        "contract_missing": [
                            _contract_gap_requirement(item) for item in contract_missing
                        ],
                        "contract_wrong": [
                            _contract_gap_requirement(item) for item in contract_wrong
                        ],
                    }
                ],
                downstream_impact=reasoning,
            ),
        )
        judge_result.reasoning_summary = reasoning
        return judge_result
    reasoning = intent_contract_reasoning_summary(trace, reference, output, [], [], "correct")
    _upsert_intent_contract_assessment(
        judge_result,
        FulfillmentAssessment(
            expectation_id=_INTENT_CONTRACT_EXPECTATION_ID,
            status="fulfilled",
            expected_evidence=[
                {
                    "intent": expected_intent,
                    "required_slots": required_slots,
                    "allow_fallback": allow_fallback,
                    "min_confidence": min_confidence,
                }
            ],
            actual_evidence=[
                {
                    "intent": actual_intent,
                    "slots": slots,
                    "entities": entities,
                    "fallback": evidence.get("fallback"),
                    "ambiguous": evidence.get("ambiguous"),
                    "confidence": confidence,
                }
            ],
            downstream_impact=reasoning,
        ),
    )
    judge_result.reasoning_summary = judge_result.reasoning_summary or reasoning
    return judge_result


def reconcile_judge_result(trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    return judge_result


def pre_judge_result(trace: RunTrace, user_intent: Optional[str] = None) -> Optional[JudgeResult]:
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
        "user_intent": context.get("user_intent"),
        "intent_frame": intent_frame,
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "reference_contract": context.get("reference_contract") or {},
            "application_boundary": context.get("application_boundary") or {},
            "critical_intent_dimensions": critical_dimensions,
        }),
    }


# spec/info-volume.md：marketing-planning-intent 的 judge 策略属于项目层；core.judge 只保留通用 fulfillment 协议。
from impl.core.judge_protocol import ProjectJudge


class MarketingIntentJudge(ProjectJudge):
    """marketting-planning-intent 项目 Judge 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def build_context(self, trace: RunTrace) -> dict:
        return _build_core_context(trace)

    def build_intent_frame(self, trace: RunTrace, context: Optional[dict] = None) -> dict:
        return build_intent_frame(trace)

    def pre_judge(self, trace: RunTrace, user_intent: Optional[str] = None) -> Optional[JudgeResult]:
        return pre_judge_result(trace, user_intent=user_intent)

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        from impl.core.schema import normalize_judge_result as normalize_core_judge_result
        return normalize_core_judge_result(normalize_judge_result(trace, result)) or result

    def reconcile_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        return reconcile_judge_result(trace, result)
