from __future__ import annotations

from typing import Any

from impl.core.attribute_protocol import run_project_attribute_protocol
from impl.core.schema import AttributeResult, ExecutionTraceEvent, JudgeResult, ProjectSpec, RunTrace


_STAGE_ORDER = [
    "request_normalization",
    "intent_recognition",
    "field_clarification",
    "session_merge",
    "path_dispatch",
    "planning_function",
    "result_assembly",
    "sse_generation",
    "adapter_extraction",
]


def _event_payload(event: Any) -> dict[str, Any]:
    if isinstance(event, ExecutionTraceEvent):
        return {
            "stage": event.stage,
            "status": event.status,
            "evidence": event.evidence,
            "error": event.error,
            "inputs": event.inputs,
            "outputs": event.outputs,
            "metadata": event.metadata,
        }
    return event if isinstance(event, dict) else {}


def _execution_stage_probe(trace: RunTrace) -> dict[str, Any]:
    events = [_event_payload(event) for event in (trace.execution_trace or [])]
    observed = []
    failed = []
    for event in events:
        stage = str(event.get("stage") or event.get("name") or "")
        status = str(event.get("status") or "")
        if stage:
            observed.append({"stage": stage, "status": status, "evidence": event.get("evidence"), "error": event.get("error") or ""})
        if status in {"failed", "error", "blocked"}:
            failed.append({"stage": stage, "status": status, "evidence": event.get("evidence"), "error": event.get("error") or ""})
    observed_stages = [item["stage"] for item in observed if item["stage"]]
    earliest_missing = next((stage for stage in _STAGE_ORDER if stage not in observed_stages), None)
    return {
        "observed_stages": observed,
        "failed_stages": failed,
        "earliest_missing_expected_stage": earliest_missing,
        "stage_order": _STAGE_ORDER,
    }


def _planning_output_probe(trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual = judge_result.actual or trace.extracted_output or {}
    if not isinstance(actual, dict):
        actual = {}
    expected_stage = reference.get("stage") or reference.get("expected_stage")
    actual_stage = actual.get("stage") or actual.get("current_stage")
    expected_paths = reference.get("path_types") or reference.get("expected_path_types") or []
    actual_paths = actual.get("path_types") or actual.get("paths") or []
    expected_cards = reference.get("cards") or reference.get("expected_cards") or []
    actual_cards = actual.get("cards") or actual.get("card_summary") or []
    expected_path_set = set(expected_paths) if isinstance(expected_paths, list) else set()
    actual_path_set = set(actual_paths) if isinstance(actual_paths, list) else set()
    return {
        "expected_stage": expected_stage,
        "actual_stage": actual_stage,
        "stage_match": bool(expected_stage) and expected_stage == actual_stage,
        "missing_path_types": sorted(expected_path_set - actual_path_set),
        "unexpected_path_types": sorted(actual_path_set - expected_path_set),
        "expected_cards_count": len(expected_cards) if isinstance(expected_cards, list) else None,
        "actual_cards_count": len(actual_cards) if isinstance(actual_cards, list) else None,
        "fallback": actual.get("fallback"),
        "errors": actual.get("errors") or [],
        "evidence_gap": [
            name
            for name, missing in (
                ("reference_contract", not bool(reference)),
                ("actual_output", not bool(actual)),
                ("expected_stage", expected_stage is None),
                ("actual_stage", actual_stage is None),
            )
            if missing
        ],
    }


def _build_project_attribute_context(spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    application_boundary = {}
    boundary = getattr(adapter, "_application_boundary_from_trace", None)
    if callable(boundary):
        application_boundary = boundary(trace) or {}
    target_probe = {}
    probe = getattr(adapter, "_target_value_unit_probe", None)
    if callable(probe):
        target_probe = probe(trace, judge_result) or {}
    execution_probe = _execution_stage_probe(trace)
    planning_probe = _planning_output_probe(trace, judge_result)
    return {
        "tool_call_limit": 4,
        "system_prompt_override": """你是 marketting-planning 项目的 attribute agent。
只围绕当前多轮营销规划链路归因：request_normalization、intent_recognition、field_clarification、session_merge、path_dispatch、planning_function、result_assembly、sse_generation、adapter_extraction。
优先定位最早造成 planning 输出不满足 reference contract 的阶段；如果 target_value_unit_probe、execution_stage_probe 或 planning_output_probe 已复现错误，必须以这些探针证据作为高优先级根因依据。
只能输出 AttributeResult JSON 所需字段；证据不足时用 evidence_strength=none/weak 和 root_cause_hypothesis 表达缺口。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": _STAGE_ORDER,
                "root_cause_policy": "按 stage_order 读取 execution_stage_probe 和 planning_output_probe，查找当前 trace 中最早的失败、缺失阶段或 reference/actual 差异；不能把多轮上下文、shared_session 或外部仓库边界外问题混入当前可控链路。",
                "probe_priority": "target_value_unit_probe、execution_stage_probe、planning_output_probe 优先于 LLM 猜测；探针证据为空时再用 judge gaps 和 execution_trace 定位。",
                "evidence_contract": ["normalized_request.turns", "reference_contract", "planning_summary", "execution_trace", "runtime_checks", "target_value_unit_probe", "execution_stage_probe", "planning_output_probe"],
            },
            "application_boundary": application_boundary,
            "target_value_unit_probe": target_probe,
            "execution_stage_probe": execution_probe,
            "planning_output_probe": planning_probe,
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
