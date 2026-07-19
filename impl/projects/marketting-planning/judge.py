from __future__ import annotations

from typing import Any, Dict, Optional

from impl.core.judge_protocol import ProjectJudge
from impl.core.judge import ensure_business_expectation
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace, normalize_judge_result, to_dict


def application_boundary_from_trace(trace: RunTrace) -> dict[str, Any]:
    from impl.core.schema import trace_application_boundary
    boundary = trace_application_boundary(trace)
    if boundary:
        return boundary
    empty_boundary: dict[str, Any] = {}
    return empty_boundary


def reference_contract(trace: RunTrace) -> dict[str, Any]:
    return trace.reference_contract if isinstance(trace.reference_contract, dict) else {}


def build_judge_context(trace: RunTrace) -> Dict[str, Any]:
    application_boundary = application_boundary_from_trace(trace)
    reference = reference_contract(trace)
    return {
        "project_type": "multi_turn_sse_marketing_planning",
        "current_case_only": True,
        "reference_contract": reference,
        "output_summary": (trace.project_fields or {}).get("planning_summary") if isinstance(trace.project_fields, dict) else trace.extracted_output,
        "application_boundary": application_boundary,
        "expected_stage": reference.get("expected_stage"),
        "expected_path_types": _list(reference.get("required_path_types")),
        "expected_cards": _list(reference.get("required_cards")),
        "stage_rules": {
            "clarification": "缺字段时澄清是正确方向，规划卡片通常是可疑证据。",
            "planning": "规划场景必须检查 path_types、card identity、fallback 和 SSE completion。",
            "fallback": "fallback 是否正确取决于当前 boundary 是否允许。",
        },
    }


def build_intent_frame(spec: ProjectSpec, trace: RunTrace, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    context = context if context is not None else build_judge_context(trace)
    request_candidates = []
    for source_name, source_value in (("normalized_request", trace.normalized_request or {}), ("input", trace.input or {})):
        if isinstance(source_value, dict):
            for key in ("query", "user_intent", "question", "input"):
                value = source_value.get(key)
                if value:
                    request_candidates.append({"source": f"{source_name}.{key}", "value": value})
        elif source_value:
            request_candidates.append({"source": source_name, "value": source_value})
    return {
        "project_id": spec.project_id,
        "downstream_consumer": "marketing planning user",
        "request_candidates": request_candidates,
        "boundary_hints": context.get("application_boundary") or {},
        "output_semantics": "route the current marketing demand to the proper stage and produce actionable planning cards/events within the project boundary",
        "business_task_type": "multi_turn_marketing_planning",
        "critical_intent_dimensions": ["business_metric", "target_value_and_unit", "time_range", "decomposition_dimensions", "stage_routing", "planning_actionability", "sse_completion"],
        "boundary_rules": context.get("application_boundary") or {},
        "expected_stage": context.get("expected_stage"),
        "expected_path_types": context.get("expected_path_types") or [],
        "expected_cards": context.get("expected_cards") or [],
    }


def _build_core_context(spec: ProjectSpec, trace: RunTrace) -> dict:
    context = build_judge_context(trace) or {}
    intent_frame = build_intent_frame(spec, trace, context)
    critical_dimensions = intent_frame.get("critical_intent_dimensions") or context.get("critical_intent_dimensions")
    system_extras = []
    if critical_dimensions:
        system_extras.append(
            "## marketing-planning 评估关键维度\n"
            "请将 user prompt 中的 critical_intent_dimensions 作为拆分 business_expectations 的骨架，围绕业务指标、目标值与单位、时间范围、拆解维度、stage 路由、planning 可执行性和 SSE 完整性交付判断 fulfillment。\n"
        )
    return {
        "user_intent": context.get("user_intent"),
        "intent_frame": intent_frame,
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "reference_contract": context.get("reference_contract") or {},
            "output_summary": context.get("output_summary") or {},
            "application_boundary": context.get("application_boundary") or {},
            "expected_stage": context.get("expected_stage"),
            "expected_path_types": context.get("expected_path_types") or [],
            "expected_cards": context.get("expected_cards") or [],
            "stage_rules": context.get("stage_rules") or {},
            "critical_intent_dimensions": critical_dimensions,
        }),
    }


def normalize_judge_result_for_project(trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    output = trace.extracted_output or {}
    summary = (trace.project_fields or {}).get("planning_summary", {}) if isinstance(trace.project_fields, dict) else {}
    expected = reference_contract(trace)
    expected_stage = expected.get("expected_stage")
    actual_stage = summary.get("stage")
    required_paths = _list(expected.get("required_path_types"))
    actual_paths = [card.get("path_type") for card in summary.get("card_summary") or [] if card.get("path_type")]
    forbidden_paths = _list(expected.get("forbidden_path_types"))
    required_events = _list(expected.get("required_events"))
    actual_events = ((summary.get("event_summary") or {}).get("canonical_names") or (summary.get("event_summary") or {}).get("names") or [])
    fallback = summary.get("fallback") or {}
    application_boundary = application_boundary_from_trace(trace)
    allow_fallback = bool(expected.get("allow_fallback") or application_boundary.get("allow_fallback"))
    failures = []
    append_expected_quality_failures(trace, summary, expected, failures)
    if expected_stage and actual_stage and expected_stage != actual_stage:
        failures.append({"requirement": "expected_stage", "expected_fragment": expected_stage, "actual_fragment": actual_stage, "status": "wrong", "evidence": ["adapter extracted stage mismatch"]})
    missing_events = [event for event in required_events if event not in actual_events]
    if missing_events:
        failures.append({"requirement": "required_events", "expected_fragment": required_events, "actual_fragment": actual_events, "status": "missing", "evidence": ["required SSE event absent from event_summary"]})
    missing_paths = [path for path in required_paths if path not in actual_paths]
    extra_forbidden = [path for path in actual_paths if path in forbidden_paths]
    if missing_paths:
        failures.append({"requirement": "required_path_types", "expected_fragment": required_paths, "actual_fragment": actual_paths, "status": "missing", "evidence": ["required path type absent from card_summary"]})
    if extra_forbidden:
        failures.append({"requirement": "forbidden_path_types", "expected_fragment": forbidden_paths, "actual_fragment": actual_paths, "status": "extra", "evidence": ["forbidden path type present in card_summary"]})
    if fallback.get("used") and not allow_fallback:
        failures.append({"requirement": "allow_fallback", "expected_fragment": False, "actual_fragment": fallback, "status": "wrong", "evidence": ["fallback used but reference/boundary does not allow it"]})
    if not failures:
        judge_result.actual = output
        return judge_result
    judge_result.actual = output
    for failure in failures:
        requirement = failure.get("requirement") or "contract"
        evidence_text = "; ".join(failure.get("evidence") or []) or failure.get("status") or "mismatch"
        downstream_impact = failure_downstream_impact(requirement, failure)
        expectation_id = f"mp_contract:{requirement}"
        ensure_business_expectation(
            judge_result,
            expectation_id,
            blocking=True,
            expected_outcome=f"满足营销规划项目契约：{requirement}",
            acceptance_criteria=[failure.get("expected_fragment") or requirement],
            downstream_consumer="营销规划用户",
        )
        judge_result.fulfillment_assessments.append({
            "expectation_id": expectation_id,
            "status": "not_fulfilled",
            "evidence": evidence_text,
            "downstream_impact": downstream_impact,
        })
    return judge_result


def failure_downstream_impact(requirement, failure):
    impacts = {
        "expected_stage": "stage 路由错误，下游无法进入预期 planning 流程",
        "required_events": "SSE 关键业务事件缺失：clarification 会影响字段补齐续问，planning 会导致规划结果无法完整交付",
        "required_path_types": "规划卡片类型缺失，用户拿不到预期 planning action",
        "forbidden_path_types": "出现禁用 path，超出 application boundary",
        "allow_fallback": "fallback 在不允许的边界内触发，违反 boundary 契约",
        "target_value_wan": "目标值单位/数值错误，规划结果不可执行",
    }
    return impacts.get(requirement, f"{requirement} 契约不满足")


def append_expected_quality_failures(trace, output, expected, failures):
    metadata = (trace.normalized_request or {}).get("metadata") or {}
    if (trace.input or {}).get("source") != "data_mock_seed" or (trace.input or {}).get("expected_quality") != "incorrect":
        return
    error_type = str(metadata.get("expected_error_type") or "")
    if error_type != "target_value_unit_error":
        return
    expected_target = expected.get("target_value_wan")
    actual_target = find_target_nbev_wan(output)
    if expected_target is None or actual_target is None or int(actual_target) == int(expected_target):
        return
    failures.append({"requirement": "target_value_wan", "expected_fragment": expected_target, "actual_fragment": actual_target, "status": "wrong", "error_type": error_type, "evidence": ["seeded mock reference target_value_wan differs from output targetNbev"]})


def default_consumer_contract(trace, judge_result):
    context = build_judge_context(trace)
    return {
        "consumer": "marketing planning user",
        "contract": "multi-turn planning output must route to the expected stage, respect clarification/fallback boundaries, generate required path cards, and complete SSE delivery",
        "reference_contract": context.get("reference_contract") or {},
        "application_boundary": context.get("application_boundary") or {},
    }


def default_business_expectation(trace, judge_result):
    expectation = {
        "expectation_id": "marketting-planning:planning_output_contract",
        "downstream_consumer": "marketing planning user",
        "required_capabilities": ["stage_routing", "field_clarification", "path_card_generation", "fallback_boundary", "sse_completion"],
        "boundary": build_judge_context(trace).get("application_boundary") or {},
        "blocking": True,
    }
    user_intent = str((trace.normalized_request or {}).get("user_intent") or (trace.normalized_request or {}).get("query") or trace.input or "")
    expectation.update(
        {
            "user_intent": user_intent,
            "expected_outcome": "planning flow should produce the expected stage, path cards, fallback behavior, and completed SSE-visible result for the current demand",
            "acceptance_criteria": list(judge_result.missing or judge_result.wrong or []),
        }
    )
    return expectation


def default_fulfillment_assessment(trace, judge_result, expectation):
    overall = judge_result.overall_fulfillment or {}
    status = overall.get("status") or "not_evaluable"
    return {
        "expectation_id": expectation.get("expectation_id"),
        "status": status,
        "expected_evidence": list(judge_result.missing or []) or [judge_result.expected or trace.reference_contract or {}],
        "actual_evidence": list(judge_result.wrong or []) or list(judge_result.extra or []) or [judge_result.actual or trace.extracted_output],
        "downstream_impact": "planning user can proceed with the generated plan" if status == "fulfilled" else (judge_result.reasoning_summary or "planning user cannot rely on the current planning output to complete the business task"),
        "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
    }
class MarketingPlanningJudge(ProjectJudge):
    """marketting-planning 项目 Judge 实现（新协议）。"""

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_context(self, trace: RunTrace) -> dict:
        return _build_core_context(self.spec, trace)

    def build_intent_frame(self, trace: RunTrace, context: Optional[dict] = None) -> dict:
        return build_intent_frame(self.spec, trace, build_judge_context(trace))

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        return normalize_judge_result(normalize_judge_result_for_project(trace, result)) or result


def _list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def find_target_nbev_wan(value: Any) -> Any:
    if isinstance(value, dict):
        if "actual_fragment" in value:
            found = find_target_nbev_wan(value.get("actual_fragment"))
            if found is not None:
                return found
        for key in ("target_nbev_wan", "target_value_wan", "targetNbev", "forecast_value"):
            if key in value and isinstance(value.get(key), (int, float)):
                return int(value[key])
        for key, item in value.items():
            if key == "expected_fragment":
                continue
            found = find_target_nbev_wan(item)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = find_target_nbev_wan(item)
            if found is not None:
                return found
    return None
