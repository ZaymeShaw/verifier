from __future__ import annotations

from typing import Any

from impl.core.attribute_protocol import run_project_attribute_protocol
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _intent_contract_probe(reference: dict[str, Any], actual: dict[str, Any], intent_evidence: dict[str, Any]) -> dict[str, Any]:
    expected_intent = _first_present(reference, ("intent", "expected_intent", "label"))
    actual_intent = _first_present(actual, ("intent", "recognized_intent", "label", "raw_intent"))
    evidence_intent = _first_present(intent_evidence, ("intent", "recognized_intent", "label", "raw_intent"))
    expected_slots = reference.get("required_slots") or reference.get("slots") or []
    actual_slots = actual.get("slots") or actual.get("entities") or intent_evidence.get("slots") or intent_evidence.get("entities") or []
    expected_slot_set = set(expected_slots) if isinstance(expected_slots, list) else set()
    actual_slot_set = set(actual_slots) if isinstance(actual_slots, list) else set()
    expected_min_confidence = reference.get("min_confidence") or reference.get("confidence_threshold")
    actual_confidence = actual.get("confidence") if actual.get("confidence") is not None else intent_evidence.get("confidence")
    confidence_gap = None
    if isinstance(expected_min_confidence, (int, float)) and isinstance(actual_confidence, (int, float)):
        confidence_gap = round(float(actual_confidence) - float(expected_min_confidence), 4)
    return {
        "expected_intent": expected_intent,
        "actual_intent": actual_intent,
        "evidence_intent": evidence_intent,
        "intent_match": expected_intent is not None and expected_intent in (actual_intent, evidence_intent),
        "missing_required_slots": sorted(expected_slot_set - actual_slot_set),
        "actual_confidence": actual_confidence,
        "expected_min_confidence": expected_min_confidence,
        "confidence_gap": confidence_gap,
        "fallback_expected": bool(reference.get("fallback") or reference.get("allow_fallback")),
        "fallback_observed": bool(actual.get("fallback") or intent_evidence.get("fallback")),
        "evidence_gap": [
            name
            for name, missing in (
                ("expected_intent", expected_intent is None),
                ("actual_intent", actual_intent is None and evidence_intent is None),
                ("intent_evidence", not bool(intent_evidence)),
            )
            if missing
        ],
    }


def _build_project_attribute_context(spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    intent_evidence = (trace.project_fields or {}).get("intent_evidence", {}) if isinstance(trace.project_fields, dict) else {}
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual = judge_result.actual or trace.extracted_output or {}
    actual_payload = actual if isinstance(actual, dict) else {}
    intent_probe = _intent_contract_probe(reference, actual_payload, intent_evidence if isinstance(intent_evidence, dict) else {})
    return {
        "tool_call_limit": 4,
        "system_prompt_override": """你是 marketting-planning-intent 项目的 attribute agent。
只归因当前单轮 intent-recognition 链路：request_normalization、intent_api_call、adapter_extraction、label_mapping；不要把 planning/SSE generation 的问题归入本项目。
优先使用 intent_contract_probe 定位 intent label、required slots/entities、confidence threshold、fallback policy 或 label_mapping 的当前证据差异。
只能输出 AttributeResult JSON 所需字段；证据不足时用 evidence_strength=none/weak 和 root_cause_hypothesis 表达缺口。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": ["request_normalization", "intent_api_call", "adapter_extraction", "label_mapping"],
                "root_cause_policy": "先读取 intent_contract_probe 的 intent_match、missing_required_slots、confidence_gap、fallback 差异，再结合 runtime_checks 判断是否为映射或证据缺失。",
                "scope_boundary": "single-turn intent-recognition only; planning path output is out of scope",
                "evidence_contract": ["normalized_request.query", "reference_contract", "trace.project_fields.intent_evidence", "intent_contract_probe", "judge_result.fulfillment_assessments", "runtime_checks"],
            },
            "reference_contract": reference,
            "actual_intent_output": actual,
            "intent_evidence": intent_evidence,
            "intent_contract_probe": intent_probe,
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


from impl.core.attribute_protocol import ProjectAttribute
from impl.core.runtime_query_tools import extract_runtime_values
from impl.core.schema import normalize_attribute_result, trace_execution_trace, trace_extracted_output


class MarketingIntentAttribute(ProjectAttribute):
    """marketting-planning-intent 项目 Attribute 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        base_context = self._adapter.build_attribute_context(trace, judge_result)
        extra_context = _build_project_attribute_context(self.spec, self._adapter, trace, judge_result)
        context = dict(base_context or {})
        context.update(extra_context)
        actual = judge_result.actual or trace_extracted_output(trace) or {}
        expected = judge_result.expected or trace.reference_contract or {}
        runtime_context = {
            "expected": expected,
            "actual": actual,
            "reference": trace.reference_contract or {},
            "trace_id": trace.trace_id,
            "project_id": trace.project_id,
        }
        runtime_values = extract_runtime_values(trace_execution_trace(trace), actual)
        context["runtime_checks"] = self._adapter.get_runtime_checks(runtime_values, runtime_context)
        return context

    def probes(self):
        return None

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        result = self._adapter.apply_attribution_probes(trace, judge_result, result)
        return normalize_attribute_result(self._adapter.normalize_attribute_result(trace, judge_result, result)) or result
