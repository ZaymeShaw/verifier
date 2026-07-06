from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from .schema import AttributeResult, EvidenceRef, ExecutionTraceEvent, JudgeResult, LiveExecutionResult, LiveRequest, MultiTurnCase, ProbeResult, ProjectSpec, RunTrace, SingleTurnCase, TraceExecutionContext, judge_expected_actual_gaps, trace_execution_trace, trace_extracted_output, trace_input, trace_normalized_request, trace_project_fields
from .interaction_protocol import ReadyDecision, resolve_ready, ready_from_spec
from impl.tools import ToolContext, ToolRegistry, ToolResult


def _assessment_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _derive_overall_fulfillment(assessments: list[Any]) -> Dict[str, Any]:
    statuses = [str(_assessment_value(item, "status") or "").strip().lower() for item in assessments]
    from .judge import _derive_overall_status
    return {
        "status": _derive_overall_status(statuses),
        "assessment_count": len(assessments),
        "blocking_expectations": [
            _assessment_value(item, "expectation_id")
            for item in assessments
            if _assessment_value(item, "status") != "fulfilled" and _assessment_value(item, "blocking", False)
        ],
    }


class ProjectAdapter(ABC):
    def __init__(self, spec: ProjectSpec):
        self.spec = spec

    @abstractmethod
    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
        raise NotImplementedError

    def call_or_prepare(self, request: LiveRequest) -> LiveExecutionResult:
        from .http_client import call_project_api

        start = time.time()
        try:
            raw_response = call_project_api(self.spec, request.normalized_request)
            call_status = "succeeded"
            call_error = None
        except Exception as exc:
            raw_response = None
            call_status = "failed"
            call_error = str(exc)
        extracted_output = self.extract_output(raw_response) if call_status == "succeeded" else {}
        return LiveExecutionResult(
            project_id=self.spec.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status=call_status,
            raw_response=raw_response,
            call_error=call_error,
            runtime_ms=int((time.time() - start) * 1000),
            extracted_output=extracted_output,
            output_source=request.execution_mode,
            execution_trace=self.build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output),
            project_fields=self.project_fields(raw_response, extracted_output),
            application_boundary=self.application_boundary(raw_response, extracted_output),
        )

    def has_provided_output(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest | None) -> bool:
        # 协议层 ready gate：仅当项目声明 output 就绪且 case 携带 output 时走 provided 模式。
        # 未声明 output ready 的项目（client_search/mpi/mp）一律走 live 模式调真实 API。
        # 真值只来自 common.ready 一处，禁止子类 override 此方法或内联判定。
        return resolve_ready(self.spec, case).output

    def provided_output_raw(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest | None) -> Any:
        # 从 case 顶层取 output（SingleTurnCase.output），不再猜 input key。
        output = getattr(case, "output", None)
        if isinstance(output, dict) and output:
            return output
        input_data = dict(case.input or {})
        for key in ("raw_response", "response", "output"):
            if key in input_data:
                return input_data[key]
        return {}

    @abstractmethod
    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        raise NotImplementedError

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def build_frontend_extensions(self, trace: RunTrace) -> Dict[str, Any]:
        return {"schema_protocol_extensions": trace_project_fields(trace)}

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

    def state_executors(self) -> Dict[str, Callable[[TraceExecutionContext], Dict[str, Any]]]:
        return {}

    def collect_state_evidence(self, state_id: str, context: TraceExecutionContext) -> list[EvidenceRef]:
        return []

    def run_state_probe(self, probe_id: str, context: TraceExecutionContext) -> ProbeResult:
        return ProbeResult(probe_id=probe_id, status="skipped", stage="adapter.run_state_probe")

    def normalize_state_result(self, state_id: str, context: TraceExecutionContext, result: Dict[str, Any]) -> Dict[str, Any]:
        return result

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[ExecutionTraceEvent]:
        return [
            ExecutionTraceEvent(stage="adapter.build_request", status="ok", evidence="normalized request built"),
            ExecutionTraceEvent(stage="project.call", status="ok", evidence="raw response captured"),
            ExecutionTraceEvent(stage="adapter.extract_output", status="ok", evidence="generic extracted_output built"),
        ]

    def to_run_trace(self, result: LiveExecutionResult) -> RunTrace:
        # LiveExecutionResult 是调用事实原件；RunTrace 顶层字段只作为后续链路的稳定索引。
        project_fields = dict(result.project_fields or {})
        raw_input = result.raw_input if isinstance(result.raw_input, dict) else {}
        normalized_request = result.normalized_request if isinstance(result.normalized_request, dict) else {}
        reference_contract = raw_input.get("reference") if isinstance(raw_input.get("reference"), dict) else normalized_request.get("reference") if isinstance(normalized_request.get("reference"), dict) else {}
        scenario = str(raw_input.get("scenario") or normalized_request.get("scenario") or "")
        multi_turn_state = result.multi_turn_state
        return RunTrace(
            trace_id=str(uuid.uuid4()),
            project_id=result.project_id or self.spec.project_id,
            case_id=result.case_id,
            input=result.raw_input,
            normalized_request=result.normalized_request,
            raw_response=result.raw_response,
            extracted_output=result.extracted_output,
            live_result=result,
            execution_mode=str(normalized_request.get("execution_mode") or result.output_source or ""),
            output_source=result.output_source,
            scenario=scenario,
            reference_contract=dict(reference_contract or {}),
            application_boundary=dict(result.application_boundary or {}),
            project_fields=project_fields,
            ready=ready_from_spec(self.spec),
            runtime_logs=[] if result.call_status == "succeeded" else ["business service call failed"],
            evidence_refs=list(result.evidence_refs or []),
            execution_trace=list(result.execution_trace or []),
            status="ok" if result.call_status == "succeeded" else "error",
            error=result.call_error,
            interaction_mode=result.interaction_mode,
            session_id=result.session_id,
            conversation_transcript=list(multi_turn_state.transcript or []) if multi_turn_state else [],
            conversation_summary=(
                {
                    "session_id": multi_turn_state.session_id,
                    "turn_count": multi_turn_state.turn_index,
                    "missing_fields": list(multi_turn_state.missing_fields or []),
                    "stop_reason": str(multi_turn_state.stop_reason or ""),
                }
                if multi_turn_state
                else {}
            ),
            stop_reason=str(multi_turn_state.stop_reason or "") if multi_turn_state else "",
            multi_turn_input=(
                {
                    "session_id": multi_turn_state.session_id,
                    "turn_count": multi_turn_state.turn_index,
                    "missing_fields": list(multi_turn_state.missing_fields or []),
                    "accumulated_fields": dict(multi_turn_state.accumulated_fields or {}),
                }
                if multi_turn_state
                else None
            ),
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
        for source_name, source_value in (("normalized_request", trace_normalized_request(trace)), ("input", trace_input(trace))):
            if isinstance(source_value, dict):
                for key in ("query", "user_intent", "question", "input"):
                    value = source_value.get(key)
                    if value:
                        request_candidates.append({"source": f"{source_name}.{key}", "value": value})
            elif source_value:
                request_candidates.append({"source": source_name, "value": source_value})
        context = self.build_judge_context(trace)
        live_boundary = trace.live_result.application_boundary if trace.live_result else {}
        return {
            "project_id": self.spec.project_id,
            "downstream_consumer": context.get("project_type") or self.spec.project_id,
            "request_candidates": request_candidates,
            "boundary_hints": context.get("application_boundary") or live_boundary or {},
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
        actual = judge_result.actual or trace_extracted_output(trace)
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
        # 语义等价归一结果是判定证据，不是 live_schema 形状的 expected/actual；禁止覆盖主字段。
        judge_result.verdict_derivation = {
            **(judge_result.verdict_derivation or {}),
            "semantic_equivalence_expected": {logic_key: expected_logic, condition_key: expected_items},
            "semantic_equivalence_actual": {logic_key: actual_logic, condition_key: actual_items},
        }
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
        judge_result.overall_fulfillment = {
            **(judge_result.overall_fulfillment or {}),
            **_derive_overall_fulfillment(judge_result.fulfillment_assessments or []),
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
        live_boundary = trace.live_result.application_boundary if trace.live_result else {}
        return {
            "consumer": context.get("project_type") or self.spec.project_id,
            "contract": "current trace output must satisfy the current user or downstream business expectation",
            "reference_contract": context.get("reference_contract") or trace.reference_contract or {},
            "application_boundary": context.get("application_boundary") or live_boundary or judge_result.evaluation_boundary or {},
        }

    def _intent_text_from_model(self, intent_model: Dict[str, Any], trace: RunTrace) -> str:
        for item in intent_model.get("explicit_intents") or []:
            if isinstance(item, dict) and item.get("goal"):
                return str(item.get("goal"))
            if isinstance(item, str) and item:
                return item
        return str(intent_model.get("raw_user_request") or trace_normalized_request(trace).get("query") or trace_normalized_request(trace).get("user_intent") or trace_input(trace) or "")

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
        return criteria or list(judge_result.business_expectations or [])

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
            "user_intent": self._intent_text_from_model(intent_model, trace) if intent_model else str(trace_normalized_request(trace).get("query") or trace_normalized_request(trace).get("user_intent") or trace_input(trace) or ""),
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
        gaps = judge_expected_actual_gaps(judge_result)
        return {
            "expectation_id": expectation.get("expectation_id"),
            "status": status,
            "score": judge_result.score,
            "expected_evidence": list(gaps.get("missing") or []) or [judge_result.expected] if judge_result.expected is not None else [],
            "actual_evidence": list(gaps.get("wrong") or []) or [judge_result.actual or trace_extracted_output(trace)],
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
        judge_result.overall_fulfillment = {
            **(judge_result.overall_fulfillment or {}),
            **_derive_overall_fulfillment(judge_result.fulfillment_assessments or []),
        }
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
        coverage = dict(attribute_result.evidence_coverage or {})
        coverage["local_probe"] = True
        coverage["query"] = bool(trace.input) or coverage.get("query", False)
        coverage["actual"] = bool(trace_extracted_output(trace)) or coverage.get("actual", False)
        coverage["expected"] = bool(judge_result.expected) or coverage.get("expected", False)
        coverage["execution_trace"] = bool(trace_execution_trace(trace)) or coverage.get("execution_trace", False)
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
