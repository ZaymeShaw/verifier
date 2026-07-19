"""deerflow 项目的 Attribute 实现

实现 ProjectAttribute 协议：基于 deer-flow Gateway 多轮对话的归因基础设施。
接入阶段只搭基础设施：构建 context、runtime_checks；质量优化走 attribute skill draft。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from impl.projects.deerflow.live import _extract_reply_and_tool_calls, _stage_inference

from impl.core.attribute_protocol import ProjectAttribute
from impl.core.runtime_query_tools import extract_runtime_values
from impl.core.schema import (
    AttributeResult,
    JudgeResult,
    ProjectSpec,
    RunTrace,
    normalize_attribute_result,
    trace_execution_trace,
    trace_extracted_output,
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _planning_summary(trace: RunTrace) -> Dict[str, Any]:
    project_fields = trace.project_fields or {} if isinstance(trace.project_fields, dict) else {}
    return project_fields.get("planning_summary") or {}


def _message_lists(raw: Any) -> List[List[Dict[str, Any]]]:
    found: List[List[Dict[str, Any]]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            if any(
                isinstance(item, dict)
                and isinstance(item.get("content"), dict)
                and item.get("content", {}).get("type") == "ai"
                for item in value
            ):
                found.append(value)
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(raw)
    return found


def _has_business_ai_message(messages: List[Dict[str, Any]]) -> bool:
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        caller = str((message.get("metadata") or {}).get("caller") or "")
        content = message.get("content")
        if not caller.startswith("middleware:") and isinstance(content, dict) and content.get("type") == "ai":
            return True
    return False


def _tool_names(tool_calls: Any) -> List[str]:
    return [str(item.get("name") or "") for item in tool_calls or [] if isinstance(item, dict)]


def _confirmed_code_locations(probes: List[Dict[str, Any]]) -> set[str]:
    """Map deterministic probe mismatches to the code stage they actually verify."""
    locations: set[str] = set()
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        if probe.get("raw_business_ai_message_present"):
            if probe.get("raw_vs_extracted_reply_match") is False:
                locations.add("reply_extraction")
            if probe.get("raw_vs_extracted_tool_calls_match") is False:
                locations.add("tool_call_extraction")
        if probe.get("stage_inference_match") is False:
            locations.add("stage_inference")
        if probe.get("controller_error"):
            locations.add("interaction_controller")
    return locations


def _location_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if not isinstance(value, dict):
        return set()
    names: set[str] = set()
    for key in ("location", "stage", "path", "node"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            names.add(item.strip())
    return names


def _result_location_names(result: AttributeResult) -> set[str]:
    names: set[str] = set()
    for item in result.suspected_locations or []:
        names.update(_location_names(item))
    for attribution in result.expectation_attributions or []:
        locations = (
            attribution.get("suspected_locations")
            if isinstance(attribution, dict)
            else getattr(attribution, "suspected_locations", [])
        )
        for item in locations or []:
            names.update(_location_names(item))
    return names


def _location_is_supported(location: str, confirmed: set[str]) -> bool:
    normalized = location.lower().replace("-", "_")
    return any(name == normalized or name in normalized for name in confirmed)


def _has_expected_and_actual(trace: RunTrace, judge_result: JudgeResult) -> bool:
    expected = judge_result.expected or judge_result.business_expectations or trace.reference_contract
    actual = judge_result.actual or trace_extracted_output(trace)
    return bool(expected) and bool(actual)


def _deerflow_integrity_probes(trace: RunTrace, judge_result: JudgeResult) -> List[Dict[str, Any]]:
    probes: List[Dict[str, Any]] = []
    for index, turn in enumerate(trace.turn_records or [], start=1):
        if not isinstance(turn, dict):
            continue
        message_lists = _message_lists(turn.get("raw_response"))
        messages = message_lists[-1] if message_lists else []
        raw_reply, raw_tool_calls = _extract_reply_and_tool_calls(messages)
        extracted = turn.get("extracted_output") if isinstance(turn.get("extracted_output"), dict) else {}
        extracted_reply = _as_text(extracted.get("reply_text"))
        extracted_tools = extracted.get("tool_calls") if isinstance(extracted.get("tool_calls"), list) else []
        scripts = extracted.get("scripts_called") if isinstance(extracted.get("scripts_called"), list) else []
        inferred_stage, stage_rule = _stage_inference(extracted_reply, extracted_tools, scripts)
        raw_names = _tool_names(raw_tool_calls)
        extracted_names = _tool_names(extracted_tools)
        probes.append({
            "probe_id": f"deerflow_turn_{index}_message_integrity",
            "turn_index": index,
            "raw_business_ai_message_present": _has_business_ai_message(messages),
            "raw_reply_text": raw_reply,
            "raw_tool_names": raw_names,
            "extracted_reply_text": extracted_reply,
            "extracted_tool_names": extracted_names,
            # Live output may normalize surrounding whitespace. That is not an
            # extraction defect and must not become deterministic code evidence.
            "raw_vs_extracted_reply_match": _as_text(raw_reply) == extracted_reply,
            "raw_vs_extracted_tool_calls_match": raw_names == extracted_names,
            "extracted_stage": str(extracted.get("stage") or "unknown"),
            "inferred_stage": inferred_stage,
            "stage_inference_rule": stage_rule,
            "stage_inference_match": str(extracted.get("stage") or "unknown") == inferred_stage,
            "call_status": str(turn.get("call_status") or ""),
        })
    if trace.interaction_controller_status != "not_run" or trace.interaction_controller_error:
        probes.append({
            "probe_id": "deerflow_interaction_controller",
            "controller_status": str(trace.interaction_controller_status or "not_run"),
            "controller_error": str(trace.interaction_controller_error or ""),
            "stop_reason": str(trace.stop_reason or ""),
            "completion_status": str(trace.completion_status or ""),
        })
    return probes


def _deerflow_local_evidence_probe(trace: RunTrace, judge_result: JudgeResult, request: Dict[str, Any], reference: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
    planning_summary = _planning_summary(trace)
    stage = str(planning_summary.get("stage") or "unknown")
    reply_text = _as_text(planning_summary.get("reply_text"))
    tool_calls = planning_summary.get("tool_calls") or []
    scripts_called = planning_summary.get("scripts_called") or []
    expected_stage = reference.get("expected_stage") or request.get("expected_stage")
    expected_dimensions = reference.get("required_dimensions") or request.get("expected_dimensions") or []
    overall = judge_result.overall_fulfillment or {}
    status = overall.get("status") or ""
    return {
        "reply_text_present": bool(reply_text),
        "tool_call_count": len(tool_calls) if isinstance(tool_calls, list) else 0,
        "nbev_script_count": len(scripts_called) if isinstance(scripts_called, list) else 0,
        "scripts_called": list(scripts_called) if isinstance(scripts_called, list) else [],
        "actual_stage": stage,
        "expected_stage": expected_stage,
        "expected_dimensions": list(expected_dimensions) if isinstance(expected_dimensions, list) else [],
        "judge_status": status,
        "evidence_gap": [
            name
            for name, missing in (
                ("reply_text", not reply_text),
                ("tool_calls", not tool_calls),
                ("nbev_scripts", not scripts_called),
                ("semantic_judge", status == "not_evaluable" and not (judge_result.fulfillment_assessments or [])),
            )
            if missing
        ],
    }


def _build_attribute_context(trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
    return {
        "chain_nodes_to_check": list(trace.execution_trace or []),
        "reference_contract": trace.reference_contract if isinstance(trace.reference_contract, dict) else {},
        "attribute_standard": "Only attribute deerflow failures when judge has current-case expected/actual evidence; live service is in scope; thread/turn delivery failures may be boundary metadata.",
    }


def _build_project_attribute_context(spec: ProjectSpec, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
    reference = trace.reference_contract if isinstance(trace.reference_contract, dict) else {}
    actual = judge_result.actual or trace.extracted_output or {}
    local_probe = _deerflow_local_evidence_probe(trace, judge_result, request, reference, actual if isinstance(actual, dict) else {})
    return {
        "tool_call_limit": 3,
        "system_prompt_override": """你是 deerflow 项目的 attribute agent。
只基于当前 deerflow 样本的 query、turns、reply_text、tool_calls、nbev scripts、local evidence probe、逐轮 integrity probe 和 semantic judge 结果归因。
该项目通过 HTTP 调 deer-flow Gateway 完成多轮营销规划对话，thread_id + checkpointer 续上下文。
归因链：request_normalization → thread_creation → turn_delivery → message_history_read → reply_extraction → tool_call_extraction → stage_inference → multi_turn_accumulation → interaction_controller。
必须区分“业务输出不符合预期”和“代码链路已定位”：raw 与 extracted reply/tool_calls 一致时，说明提取忠实，不得把原始业务内容错误归因给 reply_extraction/tool_call_extraction；stage_inference_match=true 时，不得把业务阶段问题归因给 stage_inference。只有 probe 明确复现差异且 suspected location 与该差异对应时才可 strong；否则只能作为未验证上游假设并设为 weak。
当 judge 为 not_evaluable 或本地 probe 显示缺少 reply/tool_calls/semantic judge 证据时，不要编造根因，evidence_strength 设为 none 或 weak，并在 root_cause_hypothesis 说明缺失证据。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": [
                    "request_normalization",
                    "thread_creation",
                    "turn_delivery",
                    "message_history_read",
                    "reply_extraction",
                    "tool_call_extraction",
                    "stage_inference",
                    "multi_turn_accumulation",
                    "interaction_controller",
                ],
                "root_cause_policy": "先用逐轮 integrity probe 判断 raw 与 extracted reply/tool_calls、stage inference、interaction controller 是否出现可复现差异。业务输出 gap 只能说明 actual 未达成，不能单独证明代码节点根因；提取一致时不得归因 extraction，stage 一致时不得归因 stage_inference。",
                "evidence_contract": [
                    "query",
                    "turns",
                    "reference_contract",
                    "reply_text",
                    "tool_calls",
                    "nbev_scripts",
                    "deerflow_local_evidence_probe",
                    "probe_results",
                    "runtime_checks.confirmed_code_locations",
                    "judge_result.fulfillment_assessments",
                ],
                "service_boundary": "deer-flow Gateway HTTP service is in scope; thread/turn delivery failures may be boundary metadata when service unavailable",
            },
            "query": str(request.get("query") or ""),
            "reference_contract": reference,
            "actual_output": actual,
            "deerflow_local_evidence_probe": local_probe,
        },
    }


def _runtime_checks(trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
    actual = judge_result.actual or trace_extracted_output(trace) or {}
    runtime_values = extract_runtime_values(trace_execution_trace(trace), actual)
    probes = _deerflow_integrity_probes(trace, judge_result)
    turn_probes = [item for item in probes if str(item.get("probe_id") or "").startswith("deerflow_turn_")]
    has_controller_evidence = bool(trace.interaction_controller_error)
    if not turn_probes and not has_controller_evidence and not runtime_values:
        return {}
    return {
        "turn_count": len(trace.turn_records or []),
        "successful_turn_count": sum(
            1 for item in trace.turn_records or []
            if isinstance(item, dict) and item.get("call_status") == "succeeded"
        ),
        "raw_business_ai_message_turn_count": sum(bool(item.get("raw_business_ai_message_present")) for item in turn_probes),
        "reply_extraction_mismatch_turns": [
            item.get("turn_index") for item in turn_probes if not item.get("raw_vs_extracted_reply_match")
        ],
        "tool_call_extraction_mismatch_turns": [
            item.get("turn_index") for item in turn_probes if not item.get("raw_vs_extracted_tool_calls_match")
        ],
        "stage_inference_mismatch_turns": [
            item.get("turn_index") for item in turn_probes if not item.get("stage_inference_match")
        ],
        "confirmed_code_locations": sorted(_confirmed_code_locations(probes)),
        "interaction_controller_status": str(trace.interaction_controller_status or "not_run"),
        "interaction_controller_error": str(trace.interaction_controller_error or ""),
    }


def _blocked_attribute_result(trace: RunTrace, judge_result: JudgeResult, reason: str) -> AttributeResult:
    evidence = list(judge_result.evidence or [judge_result.reasoning_summary or reason])
    result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.case_id or ""),
        suspected_locations=[],
        evidence=evidence,
        evidence_strength="none",
        root_cause_hypothesis="当前证据不足以定位 deerflow 业务根因，需要语义 judge 或人工复核补足证据。",
    )
    return result


class DeerflowAttribute(ProjectAttribute):
    """deerflow 项目 Attribute 实现（新协议）。"""

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        context = _build_attribute_context(trace, judge_result)
        context.update(_build_project_attribute_context(self.spec, trace, judge_result))
        context["runtime_checks"] = _runtime_checks(trace, judge_result)
        return context

    def probes(self):
        return _deerflow_integrity_probes

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        result = normalize_attribute_result(result) or result
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status") or "not_evaluable"
        if status == "not_evaluable":
            reason = "deerflow judge 处于 not_evaluable 状态，缺少可用语义判定，不能产出正式失败归因。"
            return _blocked_attribute_result(trace, judge_result, reason)
        if result.evidence_strength == "strong":
            probes = _deerflow_integrity_probes(trace, judge_result)
            confirmed_locations = _confirmed_code_locations(probes)
            claimed_locations = _result_location_names(result)
            location_supported = bool(claimed_locations) and all(
                _location_is_supported(location, confirmed_locations)
                for location in claimed_locations
            )
            if (
                not _has_expected_and_actual(trace, judge_result)
                or not confirmed_locations
                or not location_supported
            ):
                result.evidence_strength = "weak"
        return result
