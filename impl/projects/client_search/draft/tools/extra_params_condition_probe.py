from __future__ import annotations

from typing import Any

from impl.tools import ToolResult, VerifiableTool


_DEFAULT_FIELD_ALIASES = {
    "sex": "clientSex",
    "client_sex": "clientSex",
    "gender": "clientSex",
    "annual_premium_min": "annPremSegNum",
    "ann_premium_min": "annPremSegNum",
    "insurance_category": "pCategorys",
    "must_include_category": "pCategorys",
    "must_exclude_category": "pCategorys",
}

_DEFAULT_OPERATOR_BY_PARAM = {
    "annual_premium_min": "GT",
    "ann_premium_min": "GT",
    "must_include_category": "INCLUDE",
    "must_exclude_category": "NOT_INCLUDE",
}


def _actual_conditions(actual: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = actual.get("conditions") or actual.get("structured_output") or []
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _condition_key(condition: dict[str, Any]) -> tuple[Any, Any]:
    return condition.get("field"), condition.get("operator") or condition.get("op")


def _expected_params(extra_input_params: dict[str, Any], field_aliases: dict[str, str], operator_by_param: dict[str, str]) -> list[dict[str, Any]]:
    expected = []
    for key, value in extra_input_params.items():
        expected.append(
            {
                "source_param": key,
                "field": field_aliases.get(key, key),
                "operator_hint": operator_by_param.get(key, "EQ"),
                "raw_value": value,
            }
        )
    return expected


def _summarize_adapter_comparison(adapter_condition_comparison: dict[str, Any] | None) -> dict[str, Any]:
    comparison = adapter_condition_comparison if isinstance(adapter_condition_comparison, dict) else {}
    outputs = comparison.get("outputs") if isinstance(comparison.get("outputs"), dict) else {}
    return {
        "status": comparison.get("status"),
        "expected_source": outputs.get("expected_source"),
        "evaluable": outputs.get("evaluable"),
        "wrong": outputs.get("wrong") or [],
        "missing": outputs.get("missing") or [],
        "extra": outputs.get("extra") or [],
    }


def compare_extra_params_to_conditions(
    extra_input_params: dict[str, Any],
    actual: dict[str, Any],
    value_mappings: dict[str, Any] | None = None,
    semantic_equivalence_config: dict[str, Any] | None = None,
    field_aliases: dict[str, str] | None = None,
    operator_by_param: dict[str, str] | None = None,
    adapter_condition_comparison: dict[str, Any] | None = None,
) -> ToolResult:
    aliases = field_aliases if isinstance(field_aliases, dict) else _DEFAULT_FIELD_ALIASES
    operators = operator_by_param if isinstance(operator_by_param, dict) else _DEFAULT_OPERATOR_BY_PARAM
    params = extra_input_params if isinstance(extra_input_params, dict) else {}
    expected_params = _expected_params(params, aliases, operators)
    actual_conditions = _actual_conditions(actual if isinstance(actual, dict) else {})
    actual_fields = {condition.get("field") for condition in actual_conditions}
    param_fields_without_actual_condition = [item for item in expected_params if item.get("field") not in actual_fields]
    exclusion_params = [item for item in expected_params if item.get("operator_hint") == "NOT_INCLUDE"]
    actual_exclusion_conditions = [condition for condition in actual_conditions if str(condition.get("operator") or condition.get("op") or "").startswith(("NOT", "EXCLUDE", "NIN"))]
    adapter_summary = _summarize_adapter_comparison(adapter_condition_comparison)
    adapter_gaps = list(adapter_summary.get("wrong") or []) + list(adapter_summary.get("missing") or []) + list(adapter_summary.get("extra") or [])
    if not actual_conditions:
        status = "failed"
    elif adapter_summary.get("evaluable") is False:
        status = "not_evaluable"
    elif adapter_gaps:
        status = "diverged"
    else:
        status = "passed"
    missing_evidence = [] if actual_conditions else ["actual_conditions"]
    if not adapter_condition_comparison:
        missing_evidence.append("adapter_condition_comparison")
    return ToolResult(
        tool_id="client_search.extra_params_condition_probe",
        status=status,
        actual={
            "expected_params_from_extra_input_params": expected_params,
            "actual_condition_keys": [_condition_key(condition) for condition in actual_conditions],
            "param_fields_without_actual_condition": param_fields_without_actual_condition,
            "exclusion_params": exclusion_params,
            "actual_exclusion_conditions": actual_exclusion_conditions,
            "adapter_condition_comparison": adapter_summary,
            "mapped_fields": {key: aliases.get(key, key) for key in params},
        },
        evidence=(
            "adapter condition comparison reports wrong/missing/extra condition gaps; extra_input_params field summary is supporting context only"
            if adapter_gaps
            else "adapter condition comparison reports no wrong/missing/extra gaps; extra_input_params field summary is supporting context only"
        ),
        missing_evidence=missing_evidence,
        boundary_limits=[
            "This draft probe does not define an independent pass/fail standard for client_search semantics; adapter condition_comparison remains the canonical comparison.",
            "extra_input_params field coverage is supporting context and must not override project semantic_equivalence_rules or adapter comparison.",
        ],
    )


def build_extra_params_condition_tool(
    extra_input_params: dict[str, Any],
    actual: dict[str, Any],
    value_mappings: dict[str, Any] | None = None,
    semantic_equivalence_config: dict[str, Any] | None = None,
    adapter_condition_comparison: dict[str, Any] | None = None,
) -> VerifiableTool:
    return VerifiableTool(
        tool_id="client_search.extra_params_condition_probe",
        description="Summarizes current client_search extra_input_params field coverage while deferring semantic pass/fail to adapter condition_comparison.",
        applicable_scenario="client_search attribution",
        parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        execute_fn=lambda: compare_extra_params_to_conditions(
            extra_input_params=extra_input_params,
            actual=actual,
            value_mappings=value_mappings,
            semantic_equivalence_config=semantic_equivalence_config,
            adapter_condition_comparison=adapter_condition_comparison,
        ),
    )


TOOL_EVIDENCE_CONTRACT: dict[str, Any] = {
    "name": "client_search.extra_params_condition_probe",
    "purpose": "Provide current-case extra_input_params field-coverage context while using project adapter condition_comparison as the canonical semantic comparison.",
    "input_schema": {
        "extra_input_params": "current trace.normalized_request.extra_input_params",
        "actual": "current trace.extracted_output or judge_result.actual",
        "value_mappings": "project adapter value_mappings for field enum normalization context only",
        "semantic_equivalence_config": "project semantic_equivalence_rules; canonical use remains inside adapter condition_comparison",
        "adapter_condition_comparison": "current adapter._condition_comparison(trace) output",
    },
    "output_schema": {
        "expected_params_from_extra_input_params": "list[dict]",
        "actual_condition_keys": "list[tuple]",
        "param_fields_without_actual_condition": "list[dict]",
        "exclusion_params": "list[dict]",
        "actual_exclusion_conditions": "list[dict]",
        "adapter_condition_comparison": "dict",
        "missing_evidence": "list[str]",
    },
    "evidence_type": "Can add current request-param field coverage context to attribution; cannot independently override adapter semantic comparison or prove downstream result-set correctness.",
    "boundary": "Returns failed with missing_evidence when actual conditions are absent; semantic divergence follows adapter condition_comparison, not a draft-local comparator.",
    "validation": "Run on representative client_search cases with aliases, numeric thresholds, inclusion, and exclusion semantics; draft status must align with adapter condition_comparison and must not introduce a second semantic standard.",
}
