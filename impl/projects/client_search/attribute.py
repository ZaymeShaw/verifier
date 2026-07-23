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
        "required_outputs": ["verified findings grouped by real defect", "ContextUnit-backed evidence", "one unresolved_reason when proof is insufficient"],
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
        "attribute_instruction": "application_boundary 由 application adapter 在归因前判定；当 judge_scope=parser_condition_semantics_only 时，下游结果集验证不属于本次归因链路。无法形成经 Finalization 重载与 Reviewer 审查的 finding 时，不给猜测，统一写入 unresolved_reason。",
    }


def _build_project_attribute_context(spec: ProjectSpec, tools: list[Any], trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    application_boundary = boundary_from_trace(trace)
    comparison = condition_comparison(spec, trace)
    return {
        "tools": _project_tools(tools),
        "system_prompt_override": """你是 client_search 项目的 attribute agent。
只围绕当前 query 到下游客户搜索条件的链路做归因：request_normalization、client_search_parse、routing_pattern_match、downstream_result_set（仅当 application_boundary.judge_scope 允许）。
根因必须落在当前 RunTrace/JudgeResult/project docs/config/runtime tool 证据能支撑的位置；不能复用历史 case 字段，不能输出 AttributeResult JSON 之外的项目私有字段。
当结论涉及“规则覆盖缺口”“Prompt 引导不足”或“模型未泛化”时，必须优先调用 search_api 做最小对照重放：原 query、去掉复合修饰的基础表达、只替换待验证语义变量的相邻表达。只有对照结果能区分竞争解释时才能输出因果 finding；API 不可用或对照不能区分时，只能收缩到已证实的故障发生层级并写 unresolved_reason。
只调查 not_fulfilled expectation，按真实缺陷合并 findings。证据不足时不输出 hypothesis，只写一个 unresolved_reason。最终输出字段仅为 findings、unresolved_reason；finding evidence 仅引用 Finalization 重新加载的 ContextUnit。
禁止输出 attributed_to、root_cause_summary、evidence_refs、causal_category、earliest_divergence、verification_steps 等旧字段或项目私有字段。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": ["request_normalization", "client_search_parse", "routing_pattern_match", "downstream_result_set"],
                "judge_scope": application_boundary.get("judge_scope"),
                "root_cause_policy": "优先用 condition_comparison 的 missing/wrong/extra 和 runtime_checks 定位字段、操作符、值归一化、布尔逻辑或边界问题。",
                "tool_selection_policy": "先用 search_api 复现 actual；若拟归因为规则、Prompt 或模型行为，再用最小对照 query 重放区分竞争解释；最后用 field_capability/rule_verify 或源码解释已观察到的差异。静态配置存在或缺失本身不能证明本次失败的原因。",
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
    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        from impl.core.project_loader import load_project_role_tools

        self._adapter = adapter
        self._tools = load_project_role_tools(spec, "attribute")

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
