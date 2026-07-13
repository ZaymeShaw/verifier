from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from impl.core.judge_protocol import ProjectJudge, run_project_judge_protocol
from impl.core.project_loader import load_field_provider
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace, normalize_judge_result, to_dict, trace_extracted_output
from impl.projects.client_search.live import FIELD_PATTERNS, application_boundary as live_application_boundary, boundary_from_trace, capability_manifest, enhanced_rules, external_boundary_sources, state_executors as live_state_executors, trace_state_graph as live_trace_state_graph, value_mappings
from impl.projects.client_search.tools import ClientSearchConditionCompareTool
from impl.tools import ToolContext, ToolRegistry
from impl.tools import build_agno_tools
from impl.tools.field_retrieval import create_field_search_verifiable_tool

logger = logging.getLogger(__name__)

_FIELD_LIST_KEYS = frozenset(["conditions", "structured_output"])


def _extract_fields_from_trace(trace: RunTrace) -> Set[str]:
    fields = set()
    output = trace_extracted_output(trace) if trace_extracted_output(trace) else {}
    if isinstance(output, dict):
        for key in _FIELD_LIST_KEYS:
            if key in output and isinstance(output[key], list):
                for entry in output[key]:
                    if isinstance(entry, dict) and "field" in entry:
                        fields.add(entry["field"])
    reference = trace.reference_contract or (trace.input.get("reference") if isinstance(trace.input, dict) else None)
    if isinstance(reference, dict):
        for value in reference.values():
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, dict) and "field" in entry:
                        fields.add(entry["field"])
    return fields


def _compact_capability_manifest(context: Dict[str, Any], trace_fields: Set[str]) -> Dict[str, Any]:
    full_manifest = context.get("capability_manifest")
    if not isinstance(full_manifest, dict):
        return {}
    if not trace_fields:
        return dict(full_manifest)
    return {field: full_manifest[field] for field in trace_fields if field in full_manifest}


def _compact_semantic_rules(context: Dict[str, Any], trace_fields: Set[str]) -> Dict[str, Any]:
    full_rules = context.get("semantic_equivalence_rules")
    if not isinstance(full_rules, dict):
        return {}
    if not trace_fields:
        return dict(full_rules)
    compact: Dict[str, Any] = {}
    if "equivalent_condition_forms" in full_rules:
        compact["equivalent_condition_forms"] = [r for r in full_rules["equivalent_condition_forms"] if isinstance(r, dict) and r.get("field") in trace_fields]
    if "operator_compatibility" in full_rules:
        compact["operator_compatibility"] = [r for r in full_rules["operator_compatibility"] if isinstance(r, dict) and r.get("field") in trace_fields]
    if "equivalent_fields" in full_rules:
        compact["equivalent_fields"] = [r for r in full_rules["equivalent_fields"] if isinstance(r, dict) and (r.get("field") in trace_fields or r.get("equivalent_field") in trace_fields)]
    return compact


def _compact_value_mappings(context: Dict[str, Any], trace_fields: Set[str]) -> Dict[str, Any]:
    full_mappings = context.get("value_mappings")
    if not isinstance(full_mappings, dict):
        return {}
    if not trace_fields:
        return dict(full_mappings)
    return {field: full_mappings[field] for field in trace_fields if field in full_mappings}


def _compact_enhanced_rules(context: Dict[str, Any], trace_fields: Set[str]) -> Dict[str, Any]:
    full_rules = context.get("enhanced_rules")
    if not isinstance(full_rules, dict):
        return {}
    compact: Dict[str, Any] = {}
    for rule_key in ("rules", "composite_rules", "bare_value_weak_match"):
        raw = full_rules.get(rule_key)
        if not isinstance(raw, list):
            continue
        if rule_key == "composite_rules":
            compact[rule_key] = raw[:20]
        elif not trace_fields:
            compact[rule_key] = raw[:20] if len(raw) > 20 else raw
        else:
            filtered = [r for r in raw if isinstance(r, dict) and r.get("field") in trace_fields]
            if filtered:
                compact[rule_key] = filtered[:20] if len(filtered) > 20 else filtered
    negation = full_rules.get("negation_words")
    if isinstance(negation, list):
        compact["negation_words"] = negation
    return compact


def _build_judge_tools(spec: ProjectSpec) -> list[Any]:
    try:
        field_provider = load_field_provider(spec)
    except Exception as exc:
        logger.warning(f"[client_search.judge] Failed to load field provider for {spec.project_id}: {exc}")
        field_provider = None
    field_search_tool = create_field_search_verifiable_tool(field_provider) if field_provider else None
    return build_agno_tools([field_search_tool]) if field_search_tool else []


def _hashable_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_hashable_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _hashable_value(item)) for key, item in value.items()))
    return value


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, tuple):
        if all(isinstance(item, tuple) and len(item) == 2 for item in value):
            return {key: _jsonable_value(item) for key, item in value}
        return [_jsonable_value(item) for item in value]
    return value


def _semantic_equivalence_config(spec: ProjectSpec) -> Dict[str, Any]:
    extensions = spec.frontend_extensions or {}
    config = extensions.get("semantic_equivalence_rules")
    return config if isinstance(config, dict) else {}


def semantic_equivalence_rules(spec: ProjectSpec) -> list[Dict[str, Any]]:
    config = _semantic_equivalence_config(spec)
    rules = []
    rules.extend(list(config.get("equivalent_condition_forms") or []))
    rules.extend(list(config.get("operator_compatibility") or []))
    rules.extend(list(config.get("equivalent_fields") or []))
    return rules


def _equivalent_condition_forms(spec: ProjectSpec) -> Dict[str, Dict[Any, Any]]:
    forms: Dict[str, Dict[Any, Any]] = {}
    for item in _semantic_equivalence_config(spec).get("equivalent_condition_forms") or []:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        operator = item.get("operator")
        equivalent_operator = item.get("equivalent_operator")
        if not field or not operator or not equivalent_operator:
            continue
        value = _hashable_value(item.get("value"))
        equivalent_value = _hashable_value(item.get("equivalent_value"))
        forms.setdefault(str(field), {})[(str(operator), value)] = (str(equivalent_operator), equivalent_value)
    return forms


def canonical_condition(spec: ProjectSpec, condition: Any) -> Any:
    if not isinstance(condition, dict):
        return condition
    field = condition.get("field")
    operator = condition.get("operator")
    value = condition.get("value")
    normalized_value = _hashable_value(value)
    equivalent = _equivalent_condition_forms(spec).get(field, {}).get((operator, normalized_value))
    if equivalent:
        operator, normalized_value = equivalent
    normalized_value = _jsonable_value(normalized_value)
    return {"field": field, "operator": operator, "value": normalized_value}


def canonical_conditions(spec: ProjectSpec, value: Any) -> list[Any]:
    if isinstance(value, dict):
        conditions = value.get("conditions") or value.get("structured_output") or []
    else:
        conditions = value if isinstance(value, list) else []
    return [canonical_condition(spec, condition) for condition in conditions]


def intent_expected_conditions(trace: RunTrace) -> Dict[str, Any]:
    source = trace.normalized_request.get("intent_expected") if trace.normalized_request else None
    if isinstance(source, dict) and source.get("conditions"):
        return source
    return {}


def protocol_tools(spec: ProjectSpec) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ClientSearchConditionCompareTool())
    return registry


def condition_comparison(spec: ProjectSpec, trace: RunTrace) -> Dict[str, Any]:
    inputs = {"expected": intent_expected_conditions(trace)}
    result = protocol_tools(spec).run(
        "client_search.condition_compare",
        ToolContext(project_id=spec.project_id, purpose="judge", spec=spec, trace=trace, inputs=inputs),
    )
    return {
        "tool_id": result.tool_id,
        "tool_type": result.tool_type,
        "status": result.status,
        "outputs": result.outputs,
        "evidence": result.evidence,
        "boundary_limits": result.boundary_limits,
        "error": result.error,
    }


def judge_governance() -> Dict[str, Any]:
    return {
        "canonical_method": "current_case_llm_judge",
        "judge_role": "只判断当前 API actual output 是否语义覆盖当前 query，不做根因归因。",
        "must_ignore_as_verdict_basis": ["HTTP 200", "review_verdict", "source", "run_status", "root_cause_cluster", "attribute_result", "cluster", "history"],
        "binary_when_evidence_sufficient": True,
        "uncertain_only_when": ["LLM/API judge 调用不可用", "当前配置/枚举/字段证据不足以判断 expected-vs-actual", "application_boundary 明确排除了该需求且无法判断范围内输出"],
        "actual_output_priority": "以 API 最终 actual conditions 的下游可执行语义为准；prompt/config/后处理存在表述冲突时，先判断 actual 是否能搜出用户核心意图，再把冲突写入 evidence/check。",
        "required_comparison": ["query core intent", "field semantic carrier", "operator for field type", "value normalization", "query_logic", "missing/wrong/extra conditions"],
    }


def apply_condition_comparison(trace: RunTrace, judge_result: JudgeResult, comparison: Dict[str, Any]) -> None:
    outputs = comparison.get("outputs") or {}
    if not outputs:
        return
    wrong = list(outputs.get("wrong") or [])
    missing = list(outputs.get("missing") or [])
    extra = list(outputs.get("extra") or [])
    if wrong or missing or extra:
        judge_result.wrong = wrong
        judge_result.missing = missing
        judge_result.extra = extra
    if wrong or missing or extra:
        assessment = {
            "expectation_id": "client_search:search_condition_contract",
            "status": "not_fulfilled",
            "expected_evidence": [outputs.get("expected")],
            "actual_evidence": [outputs.get("actual"), {"wrong": wrong, "missing": missing, "extra": extra}],
            "downstream_impact": "wrong/missing/extra conditions change the target customer population",
            "blocking": True,
        }
        judge_result.fulfillment_assessments = [assessment]
    elif outputs and not judge_result.fulfillment_assessments:
        judge_result.fulfillment_assessments = [{
            "expectation_id": "client_search:search_condition_contract",
            "status": "fulfilled",
            "expected_evidence": [outputs.get("expected")],
            "actual_evidence": [outputs.get("actual")],
            "downstream_impact": "search conditions cover the target customer population",
            "blocking": True,
        }]
    if trace.extracted_output:
        judge_result.actual = trace.extracted_output
    if not judge_result.expected and trace.extracted_output:
        judge_result.expected = trace.extracted_output


def build_judge_context(spec: ProjectSpec, trace: RunTrace) -> Dict[str, Any]:
    application_boundary = boundary_from_trace(trace)
    comparison = condition_comparison(spec, trace)
    return {
        "semantic_equivalence_rules": semantic_equivalence_rules(spec),
        "field_patterns": FIELD_PATTERNS,
        "application_boundary": application_boundary,
        "judge_governance": judge_governance(),
        "condition_comparison": comparison,
        "protocol_tool_results": [comparison],
        "client_search_judge_basis": "wrong/missing/extra customer-search condition coverage within current field/config boundary",
        "boundary_usage": "application adapter has already decided whether result-set verification is in scope; judge should evaluate only within application_boundary.judge_scope.",
        "external_boundary_sources": external_boundary_sources(spec),
        "capability_manifest": capability_manifest(spec),
        "value_mappings": value_mappings(spec),
        "enhanced_rules": enhanced_rules(spec),
    }


def build_intent_frame(spec: ProjectSpec, trace: RunTrace) -> Dict[str, Any]:
    context = build_judge_context(spec, trace)
    return {
        "project_id": spec.project_id,
        "downstream_consumer": spec.project_id,
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
        "output_semantics": "produce complete, semantically correct, downstream-executable search conditions and query logic for the current user request",
        "business_task_type": "natural_language_to_downstream_client_search_conditions",
        "downstream_consumer": "downstream client search",
        "critical_intent_dimensions": ["target_population", "field_semantics", "operator", "value_or_unit", "boolean_logic", "unsupported_or_out_of_boundary_request"],
        "boundary_rules": context.get("application_boundary") or {},
        "semantic_equivalence_rules": context.get("semantic_equivalence_rules") or [],
        "field_patterns": context.get("field_patterns") or {},
        "condition_comparison": context.get("condition_comparison") or {},
        "capability_manifest": context.get("capability_manifest") or {},
        "critical_intent_dimensions_detail": {
            "target_population": "目标客户群体描述，驱动 population-sensitive field/operator/value 组合",
            "field_semantics": "请求中提到的字段及其语义定义，优先匹配 capability_manifest 中的 field/description",
            "operator": "每个字段允许的操作符，必须匹配 capability_manifest 中对应字段的 operators 列表",
            "value_or_unit": "值的单位换算与格式规范，如万=10000、岁以上用GTE+1等",
            "boolean_logic": "条件间的 AND/OR/NOT 逻辑关系",
            "unsupported_or_out_of_boundary_request": "系统不支持或超出评估边界的请求，应标记为 not_evaluable",
        },
    }


def _build_core_context(spec: ProjectSpec, trace: RunTrace) -> Dict[str, Any]:
    context = build_judge_context(spec, trace) or {}
    intent_frame = build_intent_frame(spec, trace)
    trace_fields = _extract_fields_from_trace(trace)
    compact_manifest = _compact_capability_manifest(context, trace_fields)
    semantic_rules = _compact_semantic_rules(context, trace_fields)
    mapping_values = _compact_value_mappings(context, trace_fields)
    enhanced = _compact_enhanced_rules(context, trace_fields)
    critical_dimensions = intent_frame.get("critical_intent_dimensions") or context.get("critical_intent_dimensions")

    system_extras = []
    if compact_manifest or semantic_rules or mapping_values or enhanced:
        system_extras.append(
            "## client_search 结构化字段判断范式\n"
            "user prompt 中的 capability_manifest 包含当前 case 涉及字段的完整能力清单。判断 actual output 时，必须逐字段核对字段、操作符和值类型。\n"
            "semantic_equivalence_rules 定义下游可执行的语义等价关系；满足等价规则时不应判定为 wrong/missing。\n"
            "value_mappings 提供用户口语别名到系统标准枚举值的映射；enhanced_rules 提供当前字段的 L2 正则匹配规则。\n"
        )
    if critical_dimensions:
        system_extras.append(
            "## client_search 意图关键维度\n"
            "请将 user prompt 中的 critical_intent_dimensions 作为拆分 business_expectations 的骨架。\n"
        )

    return {
        "expected_intent": context.get("expected_intent"),
        "intent_frame": intent_frame,
        "system_prompt_extras": system_extras,
        "user_prompt_extras": to_dict({
            "capability_manifest": compact_manifest,
            "semantic_equivalence_rules": semantic_rules,
            "value_mappings": mapping_values,
            "enhanced_rules": enhanced,
            "critical_intent_dimensions": critical_dimensions,
        }),
        "tools": _build_judge_tools(spec),
    }


def judge_trace(spec: ProjectSpec, adapter, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    return run_project_judge_protocol(
        spec,
        adapter,
        trace,
        expected_intent=expected_intent,
        project_judge_context=_build_core_context(spec, trace),
    )


class ClientSearchJudge(ProjectJudge):
    def __init__(self, spec: ProjectSpec):
        super().__init__(spec)

    def build_context(self, trace: RunTrace) -> dict:
        return _build_core_context(self.spec, trace)

    def build_intent_frame(self, trace: RunTrace, context: Optional[dict] = None) -> dict:
        return build_intent_frame(self.spec, trace)

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        return normalize_judge_result(result) or result

    def reconcile_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        apply_condition_comparison(trace, result, condition_comparison(self.spec, trace))
        return result
