from __future__ import annotations

from typing import Any

from impl.core.attribute_protocol import run_project_attribute_protocol
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


def _project_tools(adapter) -> list[Any]:
    get_tools = getattr(adapter, "get_verifiable_tools", None)
    return list(get_tools() or []) if callable(get_tools) else []


def _build_project_attribute_context(spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    application_boundary = {}
    boundary_from_trace = getattr(adapter, "_boundary_from_trace", None)
    if callable(boundary_from_trace):
        application_boundary = boundary_from_trace(trace) or {}
    condition_comparison = {}
    condition_compare = getattr(adapter, "_condition_comparison", None)
    if callable(condition_compare):
        condition_comparison = condition_compare(trace) or {}
    source_config_paths = {}
    source_paths = getattr(adapter, "_source_config_paths", None)
    if callable(source_paths):
        source_config_paths = source_paths() or {}
    capability_manifest = {}
    capability = getattr(adapter, "_capability_manifest", None)
    if callable(capability):
        capability_manifest = capability() or {}
    return {
        "tools": _project_tools(adapter),
        "tool_call_limit": 6,
        "system_prompt_override": """你是 client_search 项目的 attribute agent。
只围绕当前 query 到下游客户搜索条件的链路做归因：request_normalization、client_search_parse、routing_pattern_match、downstream_result_set（仅当 application_boundary.judge_scope 允许）。
根因必须落在当前 RunTrace/JudgeResult/project docs/config/runtime tool 证据能支撑的位置；不能复用历史 case 字段，不能输出 AttributeResult JSON 之外的项目私有字段。
如果字段能力、配置或运行证据不足以定位，evidence_strength 设为 none 或 weak，并在 root_cause_hypothesis 说明缺少哪些当前证据。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。
expectation_attributions 每项只能包含 expectation_id、fulfillment_status、suspected_locations、root_cause_hypothesis、evidence。
禁止输出 attributed_to、root_cause_summary、evidence_refs、causal_category、earliest_divergence、verification_steps 等旧字段或项目私有字段。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": ["request_normalization", "client_search_parse", "routing_pattern_match", "downstream_result_set"],
                "judge_scope": application_boundary.get("judge_scope"),
                "root_cause_policy": "优先用 condition_comparison 的 missing/wrong/extra 和 runtime_checks 定位字段、操作符、值归一化、布尔逻辑或边界问题。",
                "tool_selection_policy": "先用 search_api 复现 actual，再用 field_capability/rule_verify 判断字段能力、值映射和增强规则是否支持当前 query。",
                "evidence_contract": [
                    "run_trace.normalized_request",
                    "run_trace.extracted_output.conditions",
                    "run_trace.extracted_output.matched_patterns",
                    "judge_result.fulfillment_assessments",
                    "runtime_checks",
                    "project_config_or_tool_evidence",
                ],
            },
            "condition_comparison": condition_comparison,
            "application_boundary": application_boundary,
            "source_config_paths": source_config_paths,
            "capability_manifest": capability_manifest,
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
