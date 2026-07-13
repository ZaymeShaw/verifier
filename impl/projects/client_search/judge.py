from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from impl.core.judge_protocol import run_project_judge_protocol
from impl.core.project_loader import load_field_provider
from impl.core.schema import JudgeResult, ProjectSpec, RunTrace, to_dict, trace_extracted_output
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


def _build_core_context(adapter, trace: RunTrace) -> Dict[str, Any]:
    context = adapter.build_judge_context(trace) or {}
    intent_frame = adapter.build_intent_frame(trace)
    trace_fields = _extract_fields_from_trace(trace)
    capability_manifest = _compact_capability_manifest(context, trace_fields)
    semantic_rules = _compact_semantic_rules(context, trace_fields)
    value_mappings = _compact_value_mappings(context, trace_fields)
    enhanced_rules = _compact_enhanced_rules(context, trace_fields)
    critical_dimensions = intent_frame.get("critical_intent_dimensions") or context.get("critical_intent_dimensions")

    system_extras = []
    if capability_manifest or semantic_rules or value_mappings or enhanced_rules:
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
            "capability_manifest": capability_manifest,
            "semantic_equivalence_rules": semantic_rules,
            "value_mappings": value_mappings,
            "enhanced_rules": enhanced_rules,
            "critical_intent_dimensions": critical_dimensions,
        }),
        "tools": _build_judge_tools(adapter.spec),
    }


# spec/info-volume.md：client_search 的 judge 形态属于项目层。
# 这里承载项目化编排：adapter 提供 client_search 的 context/reconcile，core.judge
# 只作为最小通用 fulfillment 协议入口，不再内置字段能力/语义规则等项目策略。
def judge_trace(spec: ProjectSpec, adapter, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    return run_project_judge_protocol(
        spec,
        adapter,
        trace,
        expected_intent=expected_intent,
        project_judge_context=_build_core_context(adapter, trace),
    )


from impl.core.judge_protocol import ProjectJudge


class ClientSearchJudge(ProjectJudge):
    """client_search 项目 Judge 实现（新协议）。

    迁移过渡期：扩展点委托 adapter 现有方法，保持功能不变。
    """

    def __init__(self, spec: ProjectSpec, adapter):
        super().__init__(spec)
        self._adapter = adapter

    def build_context(self, trace: RunTrace) -> dict:
        return _build_core_context(self._adapter, trace)

    def build_intent_frame(self, trace: RunTrace, context: Optional[dict] = None) -> dict:
        return self._adapter.build_intent_frame(trace)

    def pre_judge(self, trace: RunTrace, expected_intent: Optional[str] = None) -> Optional[JudgeResult]:
        return self._adapter.pre_judge_result(trace, expected_intent=expected_intent)

    def normalize_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        from impl.core.schema import normalize_judge_result
        return normalize_judge_result(self._adapter.normalize_judge_result(trace, result)) or result

    def reconcile_result(self, trace: RunTrace, result: JudgeResult) -> JudgeResult:
        return self._adapter.reconcile_judge_result(trace, result)
