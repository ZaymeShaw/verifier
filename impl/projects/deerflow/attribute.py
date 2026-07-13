"""deerflow 项目的 Attribute 实现

实现 ProjectAttribute 协议：基于 deer-flow Gateway 多轮对话的归因基础设施。
接入阶段只搭基础设施：构建 context、runtime_checks；质量优化走 attribute skill draft。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    return project_fields.get("planning_summary") if isinstance(project_fields, dict) else {}


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
只基于当前 deerflow 样本的 query、turns、reply_text、tool_calls、nbev scripts、local evidence probe 和 semantic judge 结果归因。
该项目通过 HTTP 调 deer-flow Gateway 完成多轮营销规划对话，thread_id + checkpointer 续上下文。
归因链：request_normalization → thread_creation → turn_delivery → message_history_read → reply_extraction → tool_call_extraction → stage_inference → multi_turn_accumulation。
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
                ],
                "root_cause_policy": "先用 deerflow_local_evidence_probe 判断当前样本是否缺 reply/tool_calls/semantic judge 证据，再区分 stage 路由错误、维度缺失、NBEV 脚本未调用、多轮累积失败或服务不可用。",
                "evidence_contract": [
                    "query",
                    "turns",
                    "reference_contract",
                    "reply_text",
                    "tool_calls",
                    "nbev_scripts",
                    "deerflow_local_evidence_probe",
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


def _blocked_attribute_result(trace: RunTrace, judge_result: JudgeResult, reason: str) -> AttributeResult:
    evidence = list(judge_result.evidence or [judge_result.reasoning_summary or reason])
    result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or ""),
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

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        result = normalize_attribute_result(result) or result
        overall = judge_result.overall_fulfillment or {}
        status = overall.get("status") or "not_evaluable"
        if status == "not_evaluable":
            reason = "deerflow judge 处于 not_evaluable 状态，缺少可用语义判定，不能产出正式失败归因。"
            return _blocked_attribute_result(trace, judge_result, reason)
        return result
