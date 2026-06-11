from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict

from .schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace


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
        return any(key in input_data for key in ("raw_response", "response", "output"))

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

    def build_judge_context(self, trace: RunTrace) -> Dict[str, Any]:
        return {}

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

    def reconcile_equivalent_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        if judge_result.verdict != "incorrect":
            return judge_result
        if judge_result.missing or judge_result.wrong or judge_result.extra:
            return judge_result
        actual = judge_result.actual or trace.extracted_output
        if not self.judge_items_equivalent(judge_result.expected, actual):
            return judge_result
        expected_items = self.normalize_judge_items(judge_result.expected)
        actual_items = self.normalize_judge_items(actual)
        logic_key = "query" + "_logic"
        judge_result.verdict = "correct"
        judge_result.score = 1
        judge_result.confidence = max(float(judge_result.confidence or 0), 0.9)
        judge_result.probability = max(float(judge_result.probability or 0), 0.9)
        condition_key = "condition" + "s"
        judge_result.expected = {logic_key: "AND", condition_key: expected_items}
        judge_result.actual = {logic_key: "AND", condition_key: actual_items}
        judge_result.reasoning_summary = judge_result.reasoning_summary or "按项目语义等价规则归一后，actual 与 expected 条件一致。"
        judge_result.judge_basis = judge_result.judge_basis or "semantic_equivalence_reconciliation"
        judge_result.quality_flags = [flag for flag in (judge_result.quality_flags or []) if flag not in {"operator_mismatch", "llm_call_failed"}]
        if "semantic_equivalence_reconciled" not in judge_result.quality_flags:
            judge_result.quality_flags.append("semantic_equivalence_reconciled")
        return judge_result

    def apply_judge_consistency_gate(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        assessments = [item for item in (judge_result.condition_assessments or []) if isinstance(item, dict)]
        blocking = [item for item in assessments if item.get("status") in {"missing", "wrong", "extra"}]
        if judge_result.verdict == "correct" and (judge_result.missing or judge_result.wrong or judge_result.extra or blocking):
            if "judge_verdict_diff_conflict" not in judge_result.quality_flags:
                judge_result.quality_flags.append("judge_verdict_diff_conflict")
            judge_result.needs_human_review = True
            judge_result.verdict_derivation = {
                **(judge_result.verdict_derivation or {}),
                "consistency_gate": "verdict is correct but judge diff contains missing/wrong/extra evidence",
            }
        if judge_result.verdict == "uncertain" and not (judge_result.verdict_derivation or {}).get("blocking_gaps") and "llm_call_failed" not in (judge_result.quality_flags or []):
            if "uncertain_without_blocking_gaps" not in judge_result.quality_flags:
                judge_result.quality_flags.append("uncertain_without_blocking_gaps")
            judge_result.needs_human_review = True
        return judge_result

    def normalize_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        return judge_result

    def reconcile_judge_result(self, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
        result = self.normalize_judge_result(trace, judge_result)
        result = self.reconcile_equivalent_judge_result(trace, result)
        return self.apply_judge_consistency_gate(trace, result)

    def build_attribute_context(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        return {}

    def normalize_attribute_result(self, trace: RunTrace, judge_result: JudgeResult, attribute_result: AttributeResult) -> AttributeResult:
        return attribute_result

    def mock_response(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "mock": True,
            "request": request,
            "message": "Project service unavailable or mock mode requested.",
        }

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
