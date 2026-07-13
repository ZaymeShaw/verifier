from __future__ import annotations

from typing import Any

from impl.core.attribute_protocol import ProjectAttribute
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace
from impl.projects.client_search.draft.tools.extra_params_condition_probe import compare_extra_params_to_conditions


def _actual_payload(trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    actual = judge_result.actual or trace.extracted_output or {}
    return actual if isinstance(actual, dict) else {}


def _extra_input_params(trace: RunTrace) -> dict[str, Any]:
    request = trace.normalized_request if isinstance(trace.normalized_request, dict) else {}
    params = request.get("extra_input_params") or {}
    if not params and isinstance(trace.input, dict):
        params = trace.input.get("extra_input_params") or {}
    return params if isinstance(params, dict) else {}


def _adapter_condition_comparison(adapter, trace: RunTrace) -> dict[str, Any]:
    condition_comparison = getattr(adapter, "_condition_comparison", None)
    if callable(condition_comparison):
        return condition_comparison(trace) or {}
    return {}


def _application_boundary(adapter, trace: RunTrace) -> dict[str, Any]:
    boundary_from_trace = getattr(adapter, "_boundary_from_trace", None)
    if callable(boundary_from_trace):
        return boundary_from_trace(trace) or {}
    return {}


def _source_config_paths(adapter) -> dict[str, Any]:
    source_paths = getattr(adapter, "_source_config_paths", None)
    if callable(source_paths):
        return source_paths() or {}
    return {}


def _capability_manifest(adapter) -> dict[str, Any]:
    capability = getattr(adapter, "_capability_manifest", None)
    if callable(capability):
        return capability() or {}
    return {}


def _client_search_draft_probe(adapter, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    extra_params = _extra_input_params(trace)
    actual = _actual_payload(trace, judge_result)
    value_mappings = getattr(adapter, "_value_mappings", lambda: {})()
    semantic_config = getattr(adapter, "_semantic_equivalence_config", lambda: {})()
    comparison = _adapter_condition_comparison(adapter, trace)
    param_probe = compare_extra_params_to_conditions(
        extra_params,
        actual,
        value_mappings=value_mappings,
        semantic_equivalence_config=semantic_config,
        adapter_condition_comparison=comparison,
    )
    outputs = comparison.get("outputs") or {}
    return {
        "extra_params_condition_probe": {
            "status": param_probe.status,
            "actual": param_probe.actual,
            "evidence": param_probe.evidence,
            "missing_evidence": param_probe.missing_evidence,
            "boundary_limits": param_probe.boundary_limits,
        },
        "adapter_condition_comparison": {
            "status": comparison.get("status"),
            "wrong": outputs.get("wrong") or [],
            "missing": outputs.get("missing") or [],
            "extra": outputs.get("extra") or [],
            "expected_source": outputs.get("expected_source"),
            "evaluable": outputs.get("evaluable"),
        },
        "judge_status": (judge_result.overall_fulfillment or {}).get("status"),
        "fulfillment_assessment_count": len(judge_result.fulfillment_assessments or []),
    }


def _build_project_attribute_context(spec: ProjectSpec, adapter, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
    from impl.core.project_loader import load_project_tools

    tools = load_project_tools(spec).verifiable_tools()
    return {
        "tools": list(tools or []),
        "tool_call_limit": 6,
        "system_prompt_override": """你是 client_search 项目的 draft attribute agent。
只基于当前 RunTrace、JudgeResult、adapter condition_comparison、extra_params_condition_probe 和项目配置/工具证据归因。
重点定位自然语言/extra_input_params 到 parser actual conditions 的链路：字段别名、操作符、值归一化、AND/OR/NOT 逻辑、下游边界。
如果 actual conditions、expected/reference 或 adapter comparison 缺失，evidence_strength 必须为 none 或 weak；只有当前 case probe 明确显示 missing/wrong/extra 或 exclusion 语义丢失时才允许 strong/medium。
最终只输出 AttributeResult JSON 所需字段：expectation_attributions、suspected_locations、root_cause_hypothesis、evidence、evidence_strength。
expectation_attributions 每项只能包含 expectation_id、fulfillment_status、suspected_locations、root_cause_hypothesis、evidence。
禁止输出 attributed_to、root_cause_summary、evidence_refs、causal_category、earliest_divergence、verification_steps 等旧字段或项目私有字段。""",
        "user_prompt_extras": {
            "project_attribute_strategy": {
                "project": spec.project_id,
                "business_chain": ["request_normalization", "extra_input_params_mapping", "client_search_parse", "routing_pattern_match", "downstream_result_set"],
                "root_cause_policy": "Use extra_params_condition_probe and adapter condition_comparison before LLM inference; do not reuse historical client_search fields unless they appear in current input or actual output.",
                "evidence_contract": ["current query", "extra_input_params", "actual parser conditions", "judge_result", "adapter condition_comparison", "project config/tool evidence"],
            },
            "application_boundary": _application_boundary(adapter, trace),
            "source_config_paths": _source_config_paths(adapter),
            "capability_manifest": _capability_manifest(adapter),
            "client_search_draft_probe": _client_search_draft_probe(adapter, trace, judge_result),
        },
    }
class ClientSearchAttribute(ProjectAttribute):
    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict[str, Any]:
        return _build_project_attribute_context(self.spec, self._adapter, trace, judge_result)
