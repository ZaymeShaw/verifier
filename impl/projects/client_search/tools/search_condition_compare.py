from __future__ import annotations

import json
from typing import Any, Dict

from impl.tools import ToolContext, ToolResult


class ClientSearchConditionCompareTool:
    tool_id = "client_search.condition_compare"
    tool_type = "comparison"

    def run(self, context: ToolContext) -> ToolResult:
        trace = context.trace
        if trace is None:
            return ToolResult(tool_id=self.tool_id, tool_type=self.tool_type, status="failed", error="trace missing")
        reference = trace.input.get("reference") if isinstance(trace.input.get("reference"), dict) else {}
        intent_expected = context.inputs.get("expected") if isinstance(context.inputs.get("expected"), dict) else {}
        reference_conditions = reference.get("expected_conditions") or []
        reference_is_oracle = bool(reference.get("is_current_oracle") or reference.get("oracle") == "current")
        if intent_expected.get("conditions"):
            expected_conditions = intent_expected.get("conditions") or []
            expected_source = intent_expected.get("expected_source") or "intent_model"
            query_logic = intent_expected.get("query_logic") or "AND"
        elif reference_is_oracle:
            expected_conditions = reference_conditions
            expected_source = "reference_oracle"
            query_logic = reference.get("expected_logic") or reference.get("logic") or "AND"
        elif reference_conditions:
            # Fallback: use reference conditions even when not oracle, so condition comparison
            # can perform semantic matching rather than returning evaluable=false.
            expected_conditions = reference_conditions
            expected_source = "reference_fallback"
            query_logic = reference.get("expected_logic") or reference.get("logic") or "AND"
        else:
            expected_conditions = []
            expected_source = "reference_evidence" if reference_conditions else "not_available"
            query_logic = reference.get("expected_logic") or reference.get("logic") or "AND"
        expected = {
            "query_logic": query_logic,
            "conditions": expected_conditions,
            "expected_source": expected_source,
            "reference_conditions": reference_conditions,
            "reference_is_oracle": reference_is_oracle,
        }
        actual = {
            "query_logic": (trace.extracted_output or {}).get("logic") or "AND",
            "conditions": (trace.extracted_output or {}).get("structured_output") or [],
        }
        equivalence_rules = (context.spec.frontend_extensions or {}).get("semantic_equivalence_rules") if context.spec else {}
        # Include operator_compatibility from project.yaml via semantic_equivalence_rules
        wrong, missing, extra = self._compare(expected, actual, equivalence_rules) if expected_conditions else ([], [], [])
        boundary_limits = []
        if reference.get("allow_empty_conditions") and not expected["conditions"]:
            boundary_limits.append({"reason": reference.get("expected_reason") or "empty conditions allowed by project boundary"})
        status = "succeeded"
        evaluable = bool(expected_conditions)
        # Also evaluable when using reference_fallback (even if conditions differ, we can compare)
        if expected_source == "reference_fallback":
            evaluable = True
        outputs = {
            "target_population": self._query_text(trace.input, trace.normalized_request, trace.extracted_output),
            "expected": expected,
            "actual": actual,
            "wrong": wrong,
            "missing": missing,
            "extra": extra,
            "extra_or_overbroad": extra,
            "boundary_limits": boundary_limits,
            "comparison_basis": "client_search wrong/missing/extra customer-search coverage",
            "expected_source": expected.get("expected_source"),
            "evaluable": evaluable,
            "expected_source_label": expected_source,
        }
        missing_evidence = [] if evaluable else [{"reason": "current intent/config expected conditions unavailable; reference expected_conditions kept as evidence only", "expected_source": expected_source}]
        if evaluable and expected_source == "reference_fallback":
            missing_evidence = [{"reason": "no intent/config expected conditions; using reference conditions as fallback for semantic comparison", "expected_source": expected_source}]
        evidence = [
            {"query": outputs["target_population"]},
            {"expected": expected},
            {"actual": actual},
            {"wrong": wrong, "missing": missing, "extra": extra, "boundary_limits": boundary_limits},
        ]
        return ToolResult(tool_id=self.tool_id, tool_type=self.tool_type, status=status, outputs=outputs, evidence=evidence, missing_evidence=missing_evidence, boundary_limits=boundary_limits)

    def _query_text(self, input_data: Dict[str, Any], normalized_request: Dict[str, Any], extracted_output: Dict[str, Any]) -> str:
        nested = input_data.get("input") if isinstance(input_data.get("input"), dict) else {}
        return str(input_data.get("query") or nested.get("query") or normalized_request.get("user_text") or extracted_output.get("source_query") or "")

    def _compare(self, expected: Dict[str, Any], actual: Dict[str, Any], equivalence_rules: dict | None = None) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]]]:
        expected_conditions = [self._canonical_condition(item) for item in expected.get("conditions") or []]
        actual_conditions = [self._canonical_condition(item) for item in actual.get("conditions") or []]
        missing = []
        wrong = []
        extra = []
        matched_actual = set()
        for expected_index, expected_condition in enumerate(expected_conditions):
            exact_index = self._find_exact(expected_condition, actual_conditions, matched_actual)
            if exact_index is not None:
                matched_actual.add(exact_index)
                continue
            field_index = self._find_same_field(expected_condition, actual_conditions, matched_actual, equivalence_rules)
            if field_index is not None:
                matched_actual.add(field_index)
                actual_condition = actual_conditions[field_index]
                wrong.append(
                    {
                        "type": "wrong_condition",
                        "expected_fragment": expected_condition,
                        "actual_fragment": actual_condition,
                        "reason": self._wrong_reason(expected_condition, actual_condition, equivalence_rules),
                    }
                )
                continue
            missing.append({"type": "missing_condition", "expected_fragment": expected_condition, "reason": "用户目标客户集合需要该筛选条件，但 actual 未输出对应字段条件。"})
        for actual_index, actual_condition in enumerate(actual_conditions):
            if actual_index not in matched_actual:
                extra.append({"type": "extra_or_overbroad_condition", "actual_fragment": actual_condition, "reason": "actual 输出包含未被目标客户意图要求的条件，可能导致筛选范围过窄、过宽或偏离目标客户。"})
        expected_logic = expected.get("query_logic") or "AND"
        actual_logic = actual.get("query_logic") or "AND"
        if expected_conditions and actual_conditions and expected_logic != actual_logic:
            wrong.append({"type": "wrong_query_logic", "expected_fragment": expected_logic, "actual_fragment": actual_logic, "reason": "AND/OR 逻辑不一致会改变目标客户集合覆盖范围。"})
        return wrong, missing, extra

    def _find_exact(self, expected_condition: Dict[str, Any], actual_conditions: list[Dict[str, Any]], matched_actual: set[int]) -> int | None:
        for index, actual_condition in enumerate(actual_conditions):
            if index not in matched_actual and actual_condition == expected_condition:
                return index
        return None

    def _find_same_field(self, expected_condition: Dict[str, Any], actual_conditions: list[Dict[str, Any]], matched_actual: set[int], equivalence_rules: dict | None = None) -> int | None:
        for index, actual_condition in enumerate(actual_conditions):
            if index not in matched_actual and actual_condition.get("field") == expected_condition.get("field"):
                return index
        # Check equivalent_fields rules
        if equivalence_rules:
            eq_fields = equivalence_rules.get("equivalent_fields") or []
            for rule in eq_fields:
                if expected_condition.get("field") == rule.get("field"):
                    for index, actual_condition in enumerate(actual_conditions):
                        if index not in matched_actual and actual_condition.get("field") == rule.get("equivalent_field"):
                            return index
                elif expected_condition.get("field") == rule.get("equivalent_field"):
                    for index, actual_condition in enumerate(actual_conditions):
                        if index not in matched_actual and actual_condition.get("field") == rule.get("field"):
                            return index
        return None

    def _canonical_condition(self, condition: Any) -> Dict[str, Any]:
        if not isinstance(condition, dict):
            return {"value": condition}
        value = condition.get("value")
        return {
            "field": condition.get("field"),
            "operator": condition.get("operator"),
            "value": json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True)),
        }

    def _wrong_reason(self, expected_condition: Dict[str, Any], actual_condition: Dict[str, Any], equivalence_rules: dict | None = None) -> str:
        if expected_condition.get("operator") != actual_condition.get("operator"):
            # Check operator_compatibility before calling it wrong
            if equivalence_rules:
                compat_rules = equivalence_rules.get("operator_compatibility") or []
                for rule in compat_rules:
                    rule_field = rule.get("field", "")
                    if rule_field not in ("*", "", expected_condition.get("field", "")):
                        continue
                    if (expected_condition.get("operator") == rule.get("operator") and actual_condition.get("operator") == rule.get("equivalent_operator")) or                        (actual_condition.get("operator") == rule.get("operator") and expected_condition.get("operator") == rule.get("equivalent_operator")):
                        return ""  # Empty string means no wrong reason - operators are compatible
            return "字段相同但操作符错误，会改变目标客户集合。"
        if expected_condition.get("value") != actual_condition.get("value"):
            return "字段相同但值或枚举值错误，筛选出来的客户不是目标客户或覆盖范围不正确。"
        return "字段条件语义不一致。"
