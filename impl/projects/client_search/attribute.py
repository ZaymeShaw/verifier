from __future__ import annotations

from typing import Any

from impl.core.attribute_protocol import ProjectAttribute
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace, normalize_attribute_result
from impl.projects.client_search.judge import condition_comparison
from impl.projects.client_search.live import boundary_from_trace, capability_manifest, external_boundary_sources, source_config_paths


def _project_tools(tools: list[Any] | None) -> list[Any]:
    return list(tools or [])


def _attribute_quality_gate() -> dict[str, Any]:
    return {
        "run_only_for": ["incorrect", "uncertain with inspectable expected-vs-actual gap"],
        "block_when_judge_unavailable": True,
        "minimum_evidence": ["current query", "actual conditions/matched_level", "judge expected-vs-actual diff", "execution_trace or project chain nodes", "project docs/config evidence"],
        "required_outputs": ["clear root_cause_hypothesis", "evidence-backed suspected_locations", "evidence_strength", "current-case evidence", "business impact"],
        "quality_standard": "必须围绕当前 query 产出明确根因、可核验证据链、疑似文件/配置位置、具体修改建议、明确修改方案和业务影响；期望条件和修改方案必须来自当前 query 或同 query 链路证据，不能引用无关历史 case 字段。",
    }


def build_attribute_context(spec: ProjectSpec, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    project_output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
    application_boundary = boundary_from_trace(trace)
    chain_nodes = [
        {"name": "request_normalization", "evidence_ref": "run_trace.normalized_request"},
        {"name": "client_search_parse", "evidence_ref": "run_trace.extracted_output"},
        {"name": "routing_pattern_match", "evidence_ref": "run_trace.extracted_output.matched_patterns"},
        {"name": "judge_boundary", "evidence": application_boundary},
    ]
    if application_boundary.get("judge_scope") == "parser_and_result_set":
        chain_nodes.insert(3, {"name": "downstream_result_set", "evidence_ref": "run_trace.project_fields.downstream_search"})
    return {
        "chain_nodes_to_check": chain_nodes,
        "conditions": project_output.get("conditions"),
        "query_logic": project_output.get("query_logic"),
        "matched_level": project_output.get("matched_level"),
        "application_boundary": application_boundary,
        "attribute_quality_gate": _attribute_quality_gate(),
        "external_boundary_sources": (trace.project_fields or {}).get("external_boundary_sources") if isinstance(trace.project_fields, dict) else {},
        "source_config_paths": source_config_paths(spec),
        "attribute_instruction": "application_boundary 由 application adapter 在归因前判定；当 judge_scope=parser_condition_semantics_only 时，下游结果集验证不属于本次归因链路，归因只分析 query、parse 条件、matched_patterns、execution_trace 和项目文档中的可控解析问题；无法定位代码/配置时应将 evidence_strength 设为 none 或 weak，并在 root_cause_hypothesis 中说明缺失的当前证据。chain_nodes_to_check 中带 evidence_ref 的节点，其 evidence 已在 run_trace 对应字段中提供，直接引用即可，无需重复读取。",
    }


def _build_project_attribute_context(spec: ProjectSpec, tools: list[Any], trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    application_boundary = boundary_from_trace(trace)
    comparison = condition_comparison(spec, trace)
    return {
        "tools": _project_tools(tools),
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
            "condition_comparison": comparison,
            "application_boundary": application_boundary,
            "source_config_paths": source_config_paths(spec),
            "capability_manifest": capability_manifest(spec),
        },
    }
class ClientSearchAttribute(ProjectAttribute):
    def __init__(self, spec: ProjectSpec, tools: list[Any] | None = None):
        super().__init__(spec)
        self._tools = list(tools or [])

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        base_context = build_attribute_context(self.spec, trace, judge_result)
        extra_context = _build_project_attribute_context(self.spec, self._tools, trace, judge_result)
        context = dict(base_context or {})
        context.update(extra_context)
        context["runtime_checks"] = {}
        return context

    def probes(self):
        return None

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        return normalize_attribute_result(result) or result
