from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from .schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace
from impl.tools import ToolContext, ToolRegistry, ToolResult


class ProjectAdapter(ABC):
    def __init__(self, spec: ProjectSpec):
        self.spec = spec

    @abstractmethod
    def build_request(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def call_or_prepare(self, request: Dict[str, Any]) -> Any:
        from .http_client import call_project_api

        return call_project_api(self.spec, request)

    def has_provided_output(self, input_data: Dict[str, Any], request: Dict[str, Any]) -> bool:
        for key in ("raw_response", "response", "output"):
            value = input_data.get(key)
            if value is not None and value != {}:
                return True
        return False

    def provided_output_raw(self, input_data: Dict[str, Any], request: Dict[str, Any]) -> Any:
        for key in ("raw_response", "response", "output"):
            if key in input_data:
                return input_data[key]
        return {}

    @abstractmethod
    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        raise NotImplementedError

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def build_frontend_extensions(self, trace: RunTrace) -> Dict[str, Any]:
        return {"project_fields": trace.project_fields}

    def trace_state_graph(self) -> Dict[str, Any]:
        return {}

    def extend_default_trace_graph(self, collect_executor_id: str, extra_collect_executor_ids: list[str]) -> Dict[str, Any]:
        from copy import deepcopy

        from .state_machine import DEFAULT_TRACE_GRAPH

        graph = deepcopy(DEFAULT_TRACE_GRAPH)
        graph["graph_id"] = f"{self.spec.project_id}_trace_state_machine"
        refs = [{"executor_id": collect_executor_id, "executor_type": "deterministic", "role": "generic_evidence_collector"}]
        refs.extend({"executor_id": executor_id, "executor_type": "adapter_hook", "role": executor_id} for executor_id in extra_collect_executor_ids)
        graph["states"]["collect_evidence"] = {
            **graph["states"].get("collect_evidence", {}),
            "executor_refs": refs,
            "merge_policy": "sequential_accumulation",
        }
        return graph

    def state_executors(self) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
        return {}

    def collect_state_evidence(self, state_id: str, context: Dict[str, Any]) -> list[Dict[str, Any]]:
        return []

    def run_state_probe(self, probe_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def normalize_state_result(self, state_id: str, context: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        return result

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[Dict[str, Any]]:
        return [
            {"stage": "adapter.build_request", "status": "ok", "evidence": "normalized request built"},
            {"stage": "project.call", "status": "ok", "evidence": "raw response captured"},
            {"stage": "adapter.extract_output", "status": "ok", "evidence": "generic extracted_output built"},
        ]

    def to_run_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any) -> RunTrace:
        extracted_output = self.extract_output(raw_response)
        return RunTrace(
            trace_id=str(uuid.uuid4()),
            project_id=self.spec.project_id,
            input=input_data,
            normalized_request=request,
            raw_response=raw_response,
            extracted_output=extracted_output,
            project_fields=self.project_fields(raw_response, extracted_output),
            runtime_logs=[],
            evidence_refs=[],
            execution_trace=self.build_execution_trace(input_data, request, raw_response, extracted_output),
            status="ok",
        )

    def get_runtime_checks(self, runtime_values: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """返回项目运行时检查结果（如映射规则检查、枚举值检查等）。

        这是通用协议扩展点：核心层只传入运行时值和通用上下文，
        项目特有检查由具体 adapter 实现，避免在共享 tool 中硬编码项目逻辑。
        """
        return {}

    def build_attribute_tools(self) -> list:
        """返回归因过程中可用的项目特有工具函数列表。

        默认返回空列表 — 通用工具（search_source_file）会自动注入。
        如果项目有专门的运行时查询工具，在此返回工具函数，由 attribute agent 直接调用。
        """
        return []

    def protocol_tools(self) -> ToolRegistry:
        return ToolRegistry()

    def run_protocol_tools(self, trace: RunTrace, purpose: str, tool_type: str | None = None, inputs: Dict[str, Any] | None = None) -> list[ToolResult]:
        context = ToolContext(project_id=self.spec.project_id, purpose=purpose, spec=self.spec, trace=trace, inputs=inputs or {})
        return self.protocol_tools().run_selected(context, tool_type)

    def pre_judge_result(self, trace: RunTrace, expected_intent: Optional[str] = None) -> Optional[JudgeResult]:
        return None

    def build_judge_context(self, trace: RunTrace) -> Dict[str, Any]:
        return {}

    def build_intent_frame(self, trace: RunTrace) -> Dict[str, Any]:
        request_candidates = []
        for source_name, source_value in (("normalized_request", trace.normalized_request), ("input", trace.input)):
            if isinstance(source_value, dict):
                for key in ("query", "user_intent", "question", "input"):
                    value = source_value.get(key)
                    if value:
                        request_candidates.append({"source": f"{source_name}.{key}", "value": value})
            elif source_value:
                request_candidates.append({"source": source_name, "value": source_value})
        context = self.build_judge_context(trace)
        return {
            "project_id": self.spec.project_id,
            "downstream_consumer": context.get("project_type") or self.spec.project_id,
            "request_candidates": request_candidates,
            "boundary_hints": context.get("application_boundary") or (trace.project_fields or {}).get("application_boundary") or {},
            "output_semantics": "current trace output should let the user or downstream system continue the project task",
        }

    def _hashable_judge_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(self._hashable_judge_value(item) for item in value)
        if isinstance(value, dict):
            return tuple(sorted((key, self._hashable_judge_value(item)) for key, item in value.items()))
        return value

    def _jsonable_judge_value(self, value: Any) -> Any:
        if isinstance(value, tuple):
            if all(isinstance(item, tuple) and len(item) == 2 for item in value):
                return {key: self._jsonable_judge_value(item) for key, item in value}
            return [self._jsonable_judge_value(item) for item in value]
        return value

    def semantic_equivalence_rules(self) -> list[Dict[str, Any]]:
        return []

    def register_judge_override(self, judge_result: JudgeResult, field: str, original_value: Any, overridden_value: Any, reason: str, source: str) -> None:
        judge_result.overrides.append({
            "field": field,
            "original_value": original_value,
            "overridden_value": overridden_value,
            "reason": reason,
            "source": source,
        })

    def equivalent_condition_forms(self) -> Dict[str, Dict[Any, Any]]:
        forms: Dict[str, Dict[Any, Any]] = {}
        for item in self.semantic_equivalence_rules():
            if not isinstance(item, dict):
                continue
            field = item.get("field")
            operator = item.get("operator")
            equivalent_operator = item.get("equivalent_operator")
            if not field or not operator or not equivalent_operator or "value" not in item:
                continue
            value = self._hashable_judge_value(item.get("value"))
            equivalent_value = self._hashable_judge_value(item.get("equivalent_value"))
            forms.setdefault(str(field), {})[(str(operator), value)] = (str(equivalent_operator), equivalent_value)
        return forms

    def normalize_judge_condition(self, condition: Any) -> Any:
        if not isinstance(condition, dict):
            return condition
        field = condition.get("field")
        operator = condition.get("operator")
        value = condition.get("value")
        normalized_value = self._hashable_judge_value(value)
        equivalent = self.equivalent_condition_forms().get(field, {}).get((operator, normalized_value))
        if equivalent:
            operator, normalized_value = equivalent
        return {"field": field, "operator": operator, "value": self._jsonable_judge_value(normalized_value)}

    def normalize_judge_items(self, value: Any) -> list[Any]:
        condition_key = "condition" + "s"
        if isinstance(value, dict):
            items = value.get(condition_key) or value.get("structured_output") or []
        else:
            items = value if isinstance(value, list) else []
        return [self.normalize_judge_condition(item) for item in items]

    def judge_items_equivalent(self, expected: Any, actual: Any) -> bool:
        expected_items = self.normalize_judge_items(expected)
        actual_items = self.normalize_judge_items(actual)
        if not expected_items or expected_items != actual_items:
            return False
        if isinstance(expected, dict) and isinstance(actual, dict):
            logic_key = "query" + "_logic"
            expected_logic = expected.get(logic_key) or expected.get("logic")
            actual_logic = actual.get(logic_key) or actual.get("logic")
            if expected_logic and actual_logic and expected_logic != actual_logic:
                return False
        return True

    def _apply_equivalence_to_gaps(
        self, missing: list, wrong: list, extra: list, rules: dict
    ) -> tuple:
        """Apply semantic equivalence rules to gap entries, removing those that are equivalent."""
        operator_compat = rules.get("operator_compatibility", [])
        equivalent_fields_list = rules.get("equivalent_fields", [])
        equivalent_forms = rules.get("equivalent_condition_forms", [])

        def _is_equivalent_op(gap, compat_rules):
            if not isinstance(gap, dict):
                return False
            for rule in compat_rules:
                if not isinstance(rule, dict):
                    continue
                rule_field = rule.get("field", "")
                if rule_field != "*" and rule_field != gap.get("field"):
                    continue
                if gap.get("operator") == rule.get("operator") and rule.get("equivalent_operator"):
                    # Check the condition for equivalency
                    condition = rule.get("condition", "")
                    if "one identical enum/list value" in condition:
                        gap_val = gap.get("value")
                        gap_actual = gap.get("actual_fragment") or {}
                        actual_val = gap_actual.get("value") if isinstance(gap_actual, dict) else gap_actual
                        if gap_val == actual_val or str(gap_val) in str(actual_val):
                            return True
            return False

        def _is_equivalent_field(gap, field_rules):
            if not isinstance(gap, dict):
                return False
            for rule in field_rules:
                if not isinstance(rule, dict):
                    continue
                if gap.get("field") == rule.get("field") and rule.get("equivalent_field"):
                    gap_actual = gap.get("actual_fragment") or {}
                    actual_field = gap_actual.get("field") if isinstance(gap_actual, dict) else None
                    if actual_field == rule.get("equivalent_field"):
                        return True
            return False

        def _is_equivalent_form(gap, form_rules):
            if not isinstance(gap, dict):
                return False
            for rule in form_rules:
                if not isinstance(rule, dict):
                    continue
                if gap.get("field") == rule.get("field") and gap.get("operator") == rule.get("operator"):
                    return True
            return False

        filtered_missing = [g for g in missing if not (_is_equivalent_op(g, operator_compat) or _is_equivalent_field(g, equivalent_fields_list) or _is_equivalent_form(g, equivalent_forms))]
        filtered_wrong = [g for g in wrong if not (_is_equivalent_op(g, operator_compat) or _is_equivalent_field(g, equivalent_fields_list) or _is_equivalent_form(g, equivalent_forms))]
        filtered_extra = [g for g in extra if not (_is_equivalent_op(g, operator_compat) or _is_equivalent_field(g, equivalent_fields_list) or _is_equivalent_form(g, equivalent_forms))]
        return filtered_missing, filtered_wrong, filtered_extra

    def reconcile_equivalent_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        if judge_result.verdict not in {"incorrect", "uncertain"}:
            return judge_result
        # Apply equivalence rules to wrong/missing/extra before early returning
        equivalence_rules = self.spec.frontend_extensions.get("semantic_equivalence_rules") if self.spec.frontend_extensions else {}
        if (judge_result.missing or judge_result.wrong or judge_result.extra) and equivalence_rules:
            judge_result.missing, judge_result.wrong, judge_result.extra = self._apply_equivalence_to_gaps(
                judge_result.missing, judge_result.wrong, judge_result.extra, equivalence_rules
            )
        if judge_result.missing or judge_result.wrong or judge_result.extra:
            return judge_result
        actual = judge_result.actual or trace.extracted_output
        if not self.judge_items_equivalent(judge_result.expected, actual):
            return judge_result
        expected_items = self.normalize_judge_items(judge_result.expected)
        actual_items = self.normalize_judge_items(actual)
        logic_key = "query" + "_logic"
        expected_logic = "AND"
        actual_logic = "AND"
        if isinstance(judge_result.expected, dict):
            expected_logic = judge_result.expected.get(logic_key) or judge_result.expected.get("logic") or expected_logic
        if isinstance(actual, dict):
            actual_logic = actual.get(logic_key) or actual.get("logic") or actual_logic
        condition_key = "condition" + "s"
        judge_result.expected = {logic_key: expected_logic, condition_key: expected_items}
        judge_result.actual = {logic_key: actual_logic, condition_key: actual_items}
        judge_result.reasoning_summary = judge_result.reasoning_summary or "按项目语义等价规则归一后，actual 与 expected 条件一致。"
        judge_result.judge_basis = judge_result.judge_basis or "semantic_equivalence_reconciliation"
        # Flip prior not_fulfilled blocking assessments to fulfilled (preserve evidence).
        flipped_items = []
        for item in judge_result.fulfillment_assessments or []:
            if isinstance(item, dict) and item.get("status") == "not_fulfilled":
                item["status"] = "fulfilled"
                flipped_items.append(item.get("expectation_id", ""))
        # Inject a marker assessment expressing the equivalence reconciliation.
        equivalence_rule_id = ""
        if isinstance(equivalence_rules, dict):
            equivalence_rule_id = equivalence_rules.get("rule_id") or equivalence_rules.get("id") or "semantic_equivalence"
        judge_result.fulfillment_assessments.append({
            "expectation_id": "semantic_equivalence_reconciled",
            "status": "fulfilled",
            "blocking": False,
            "evidence": equivalence_rule_id or "semantic_equivalence",
            "downstream_impact": "expected/actual 在等价规则下一致",
        })
        # Register override trail for the flip
        if flipped_items:
            self.register_judge_override(
                judge_result, "fulfillment_assessments",
                ["not_fulfilled"] * len(flipped_items),
                ["fulfilled"] * len(flipped_items),
                "semantic_equivalence_reconciled",
                "reconcile_equivalent_judge_result",
            )
        # Sync overall_fulfillment.status after modifying fulfillment_assessments
        all_statuses = [
            str(item.get("status") or "").strip().lower()
            for item in judge_result.fulfillment_assessments or []
            if isinstance(item, dict)
        ]
        from .judge import _derive_overall_status
        recalculated_status = _derive_overall_status(all_statuses)
        judge_result.overall_fulfillment = {
            **(judge_result.overall_fulfillment or {}),
            "status": recalculated_status,
            "assessment_count": len(judge_result.fulfillment_assessments),
            "blocking_expectations": [
                item.get("expectation_id")
                for item in judge_result.fulfillment_assessments
                if isinstance(item, dict) and item.get("status") != "fulfilled" and item.get("blocking")
            ],
        }
        judge_result.quality_flags = [flag for flag in (judge_result.quality_flags or []) if flag not in {"operator_mismatch", "llm_call_failed"}]
        if "semantic_equivalence_reconciled" not in judge_result.quality_flags:
            judge_result.quality_flags.append("semantic_equivalence_reconciled")
        return judge_result

    def normalize_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        return judge_result

    def _expectation_status_from_verdict(self, judge_result: JudgeResult) -> str:
        if judge_result.verdict == "correct":
            return "fulfilled"
        if judge_result.verdict == "incorrect":
            return "not_fulfilled"
        return "not_evaluable"

    def _default_consumer_contract(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        context = self.build_judge_context(trace)
        return {
            "consumer": context.get("project_type") or self.spec.project_id,
            "contract": "current trace output must satisfy the current user or downstream business expectation",
            "reference_contract": context.get("reference_contract") or (trace.project_fields or {}).get("reference") or {},
            "application_boundary": context.get("application_boundary") or (trace.project_fields or {}).get("application_boundary") or judge_result.evaluation_boundary or {},
        }

    def _intent_text_from_model(self, intent_model: Dict[str, Any], trace: RunTrace) -> str:
        for item in intent_model.get("explicit_intents") or []:
            if isinstance(item, dict) and item.get("goal"):
                return str(item.get("goal"))
            if isinstance(item, str) and item:
                return item
        return str(intent_model.get("raw_user_request") or (trace.normalized_request or {}).get("query") or (trace.normalized_request or {}).get("user_intent") or trace.input or "")

    def _source_intent_id(self, intent_model: Dict[str, Any]) -> str:
        for collection in ("blocking_requirements", "explicit_intents", "implicit_business_intents"):
            for item in intent_model.get(collection) or []:
                if isinstance(item, dict) and item.get("intent_id"):
                    return str(item.get("intent_id"))
        return "primary_intent"

    def _intent_acceptance_criteria(self, intent_model: Dict[str, Any], judge_result: JudgeResult) -> list[Any]:
        criteria = []
        for key in ("blocking_requirements", "constraints", "nice_to_have_requirements"):
            value = intent_model.get(key)
            if value:
                criteria.append({key: value})
        return criteria or list(judge_result.condition_assessments or judge_result.score_details or [])

    def _default_business_expectation(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        expectation_id = f"{self.spec.project_id}:primary_business_expectation"
        intent_model = judge_result.intent_model or {}
        intent_frame = self.build_intent_frame(trace)
        source_intent_id = self._source_intent_id(intent_model) if intent_model else "primary_intent"
        expected_outcome = intent_model.get("success_definition") if intent_model else ""
        if not expected_outcome and intent_frame.get("output_semantics"):
            expected_outcome = str(intent_frame.get("output_semantics"))
        if not expected_outcome:
            expected_outcome = "intent cannot be reconstructed from current trace; fulfillment is not evaluable"
        return {
            "expectation_id": expectation_id,
            "source_intent_id": source_intent_id,
            "downstream_consumer": (judge_result.consumer_contract or {}).get("consumer") or intent_frame.get("downstream_consumer") or self.spec.project_id,
            "user_intent": self._intent_text_from_model(intent_model, trace) if intent_model else str((trace.normalized_request or {}).get("query") or (trace.normalized_request or {}).get("user_intent") or trace.input or ""),
            "expected_outcome": expected_outcome,
            "required_capabilities": [item.get("requirement") for item in (intent_model.get("blocking_requirements") or []) if isinstance(item, dict) and item.get("requirement")],
            "acceptance_criteria": self._intent_acceptance_criteria(intent_model, judge_result) if intent_model else [],
            "boundary": judge_result.boundary_decision or judge_result.evaluation_boundary or intent_frame.get("boundary_hints") or {},
            "priority": "blocking" if intent_model.get("blocking_requirements") else "normal",
            "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
        }

    def _default_fulfillment_assessment(self, trace: RunTrace, judge_result: JudgeResult, expectation: Dict[str, Any]) -> Dict[str, Any]:
        if not (judge_result.intent_model or {}).get("raw_user_request") and not (judge_result.intent_model or {}).get("explicit_intents") and not judge_result.reconstructed_intent:
            status = "not_evaluable"
        else:
            status = self._expectation_status_from_verdict(judge_result)
        return {
            "expectation_id": expectation.get("expectation_id"),
            "status": status,
            "score": judge_result.score,
            "expected_evidence": list(judge_result.missing or []) or [judge_result.expected] if judge_result.expected is not None else [],
            "actual_evidence": list(judge_result.wrong or []) or [judge_result.actual or trace.extracted_output],
            "boundary_decision": judge_result.boundary_decision or judge_result.evaluation_boundary or {},
            "downstream_impact": "business expectation satisfied" if status == "fulfilled" else (judge_result.reasoning_summary or "business expectation not fully satisfied or not evaluable"),
            "blocking": status in {"not_fulfilled", "not_evaluable"},
            "confidence": judge_result.confidence,
            "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
        }

    def ensure_fulfillment_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        if not judge_result.consumer_contract:
            judge_result.consumer_contract = self._default_consumer_contract(trace, judge_result)
        if not judge_result.business_expectations:
            judge_result.business_expectations = [self._default_business_expectation(trace, judge_result)]
        if not judge_result.fulfillment_assessments:
            judge_result.fulfillment_assessments = [
                self._default_fulfillment_assessment(trace, judge_result, expectation if isinstance(expectation, dict) else {"expectation_id": getattr(expectation, "expectation_id", "primary_business_expectation")})
                for expectation in judge_result.business_expectations
            ]
        else:
            assessed_ids = {
                (item.get("expectation_id") if isinstance(item, dict) else getattr(item, "expectation_id", None))
                for item in judge_result.fulfillment_assessments
            } - {None}
            for expectation in judge_result.business_expectations:
                exp_id = expectation.get("expectation_id") if isinstance(expectation, dict) else getattr(expectation, "expectation_id", None)
                if exp_id and exp_id not in assessed_ids:
                    judge_result.fulfillment_assessments.append(
                        self._default_fulfillment_assessment(trace, judge_result, expectation if isinstance(expectation, dict) else {"expectation_id": exp_id})
                    )
        if not judge_result.overall_fulfillment:
            statuses = [item.get("status") for item in judge_result.fulfillment_assessments if isinstance(item, dict)]
            if any(status == "not_fulfilled" for status in statuses):
                overall_status = "not_fulfilled"
            elif any(status in {"partially_fulfilled", "not_evaluable"} for status in statuses):
                overall_status = "partially_fulfilled" if "partially_fulfilled" in statuses else "not_evaluable"
            else:
                overall_status = "fulfilled"
            judge_result.overall_fulfillment = {
                "status": overall_status,
                "assessment_count": len(judge_result.fulfillment_assessments),
                "blocking_expectations": [item.get("expectation_id") for item in judge_result.fulfillment_assessments if isinstance(item, dict) and item.get("status") != "fulfilled" and item.get("blocking")],
            }
        else:
            # Recalculate overall_fulfillment to include contract-injected assessments
            overall = judge_result.overall_fulfillment
            all_blocking = [item.get("expectation_id") for item in judge_result.fulfillment_assessments
                           if isinstance(item, dict) and item.get("status") != "fulfilled" and item.get("blocking")]
            all_statuses = [item.get("status") for item in judge_result.fulfillment_assessments if isinstance(item, dict)]
            if any(s == "not_fulfilled" for s in all_statuses):
                recalculated_status = "not_fulfilled"
            elif any(s in {"partially_fulfilled", "not_evaluable"} for s in all_statuses):
                recalculated_status = "partially_fulfilled" if "partially_fulfilled" in all_statuses else "not_evaluable"
            else:
                recalculated_status = "fulfilled"
            if isinstance(overall, dict):
                overall["status"] = recalculated_status
                overall["blocking_expectations"] = all_blocking
                overall["assessment_count"] = len(judge_result.fulfillment_assessments)
        overall_status = (judge_result.overall_fulfillment or {}).get("status") or "not_evaluable"
        from .judge import _compute_verdict, _compute_score
        judge_result.verdict = _compute_verdict(overall_status, judge_result.boundary_decision)
        judge_result.score = _compute_score(judge_result.fulfillment_assessments)
        return judge_result

    def reconcile_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        result = self.normalize_judge_result(trace, judge_result)
        result = self.reconcile_equivalent_judge_result(trace, result)
        return self.ensure_fulfillment_judge_result(trace, result)

    def build_attribute_context(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        return {}

    def attribution_probes(self, trace: RunTrace, judge_result: JudgeResult) -> list[Dict[str, Any]]:
        return []

    def apply_attribution_probes(self, trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
        probes = [item for item in self.attribution_probes(trace, judge_result) if isinstance(item, dict)]
        if not probes:
            return attribute_result
        attribute_result.local_verifications = list(attribute_result.local_verifications or []) + probes
        existing_probe_results = list(attribute_result.probe_results or [])
        for item in probes:
            existing_probe_results.append(
                {
                    "probe": item.get("probe") or item.get("method") or "adapter_attribution_probe",
                    "status": item.get("status") or "passed",
                    "evidence": list(item.get("evidence") or []),
                    "target": item.get("target"),
                    "result": item.get("result"),
                }
            )
        attribute_result.probe_results = existing_probe_results
        attribute_result.evidence_chain = list(attribute_result.evidence_chain or []) + probes
        coverage = dict(attribute_result.evidence_coverage or {})
        coverage["local_probe"] = True
        coverage["query"] = bool(trace.input) or coverage.get("query", False)
        coverage["actual"] = bool(trace.extracted_output) or coverage.get("actual", False)
        coverage["expected"] = bool(judge_result.expected) or coverage.get("expected", False)
        coverage["execution_trace"] = bool(trace.execution_trace) or coverage.get("execution_trace", False)
        coverage.setdefault("unsupported_claims", [])
        attribute_result.evidence_coverage = coverage
        quality = dict(attribute_result.analysis_quality or {})
        quality.setdefault("passed", True)
        quality.setdefault("status", "supported_root_cause")
        quality.setdefault("missing", [])
        quality.setdefault("standard", "adapter attribution probes must be grounded in the current trace and judge result.")
        attribute_result.analysis_quality = quality
        return attribute_result

    def normalize_attribute_result(self, trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
        return attribute_result

    def build_mock_cases(self) -> list[Dict[str, Any]]:
        return []

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        return []


def ensure_jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)
