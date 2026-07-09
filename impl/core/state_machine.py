"""spec/info-volume.md：通用层 state machine。

精简后：删除依赖被删 schema 字段（verdict/consumer_contract/incomplete_reason/analysis_quality/chain_nodes 等）
的 gate 检查。state machine 只保留通用流程，项目特有 gate 由项目层 override。
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Optional

from .schema import GateDecision, SubagentResult, TraceExecutionContext, TraceStateRecord, TransitionDecision, judge_primary_signal, now_iso, to_dict

StateExecutor = Callable[[TraceExecutionContext], Dict[str, Any]]


DEFAULT_TRACE_GRAPH: Dict[str, Any] = {
    "graph_id": "default_trace_state_machine",
    "version": "2",
    "initial_state": "prepare_trace",
    "limits": {"max_steps": 28, "max_retries_per_state": 1},
    "states": {
        "prepare_trace": {"role": "prepare_trace"},
        "mock_or_input": {"role": "mock_or_input"},
        "execute_or_capture": {"role": "execute_or_capture", "gates": ["trace_available"]},
        "collect_evidence": {"role": "collect_evidence"},
        "build_business_expectations": {"role": "build_business_expectations", "gates": ["business_expectation_coverage"]},
        "evaluate_fulfillment": {"role": "evaluate_fulfillment", "gates": ["fulfillment_assessment_coverage"]},
        "fulfillment_critic": {"role": "fulfillment_critic", "gates": ["contradiction_free"]},
        "attribute_expectations": {"role": "attribute_expectations", "gates": ["attribute_targets_expectation_gap"]},
        "run_attribution_probes": {"role": "run_attribution_probes"},
        "attribution_critic": {"role": "attribution_critic", "gates": ["expectation_attribution_evidence"]},
        "finalize": {"role": "finalize", "gates": ["finalization_ready", "contradiction_free"]},
        "incomplete_or_human_review": {"role": "incomplete_or_human_review"},
    },
    "transitions": {
        "prepare_trace": [{"to": "mock_or_input", "condition": "always"}],
        "mock_or_input": [{"to": "execute_or_capture", "condition": "always"}],
        "execute_or_capture": [
            {"to": "incomplete_or_human_review", "condition": "gate_failed_unrecoverable"},
            {"to": "collect_evidence", "condition": "always"},
        ],
        "collect_evidence": [{"to": "build_business_expectations", "condition": "always"}],
        "build_business_expectations": [
            {"to": "collect_evidence", "condition": "gate_failed_recoverable"},
            {"to": "incomplete_or_human_review", "condition": "gate_failed_unrecoverable"},
            {"to": "evaluate_fulfillment", "condition": "always"},
        ],
        "evaluate_fulfillment": [
            {"to": "collect_evidence", "condition": "gate_failed_recoverable"},
            {"to": "incomplete_or_human_review", "condition": "gate_failed_unrecoverable"},
            {"to": "fulfillment_critic", "condition": "always"},
        ],
        "fulfillment_critic": [
            {"to": "incomplete_or_human_review", "condition": "gate_failed_unrecoverable"},
            {"to": "collect_evidence", "condition": "gate_failed_recoverable"},
            {"to": "attribute_expectations", "condition": "fulfillment_requires_attribute"},
            {"to": "finalize", "condition": "always"},
        ],
        "attribute_expectations": [
            {"to": "finalize", "condition": "gate_failed_unrecoverable"},
            {"to": "run_attribution_probes", "condition": "always"},
        ],
        "run_attribution_probes": [{"to": "attribution_critic", "condition": "always"}],
        "attribution_critic": [
            {"to": "run_attribution_probes", "condition": "gate_failed_recoverable"},
            {"to": "incomplete_or_human_review", "condition": "gate_failed_unrecoverable"},
            {"to": "finalize", "condition": "always"},
        ],
        "finalize": [
            {"to": "incomplete_or_human_review", "condition": "gate_failed_unrecoverable"},
            {"to": "completed", "condition": "stop"},
        ],
        "incomplete_or_human_review": [{"to": "completed", "condition": "stop"}],
    },
}


class TraceStateMachineRunner:
    def __init__(self, graph: Optional[Dict[str, Any]] = None, executors: Optional[Dict[str, StateExecutor]] = None):
        self.graph = graph or DEFAULT_TRACE_GRAPH
        self.executors = executors or {}
        self._attempts: Dict[str, int] = defaultdict(int)

    def run(self, context: TraceExecutionContext) -> TraceExecutionContext:
        import logging as _logging
        _log = _logging.getLogger("verifier.state_machine")
        state_id = str(self.graph.get("initial_state") or "prepare_trace")
        max_steps = int((self.graph.get("limits") or {}).get("max_steps") or 24)
        for _ in range(max_steps):
            if state_id == "completed":
                return context
            self._attempts[state_id] += 1
            result = self._execute_state(state_id, context)
            gates = result.get("gate_decisions") or self._evaluate_gates(state_id, context, result)
            transition = self._select_transition(state_id, context, gates)
            failed_gates = [g for g in gates if not g.passed]
            if failed_gates:
                _log.warning("state=%s attempt=%d failed_gates=%s -> %s", state_id, self._attempts[state_id], [(g.gate_id, g.reason, g.recoverable, g.missing_evidence) for g in failed_gates], transition.to_state)
            if self._retry_exceeded(state_id, transition):
                transition = TransitionDecision(from_state=state_id, to_state="incomplete_or_human_review", condition="retry_limit", reason="state retry limit exceeded", gate_ids=transition.gate_ids, retry_count=transition.retry_count, stop_reason="incomplete_retry_limit")
                _log.warning("RETRY_EXCEEDED state=%s retry_count=%d", state_id, transition.retry_count)
            self._append_record(state_id, context, result, gates, transition)
            if transition.stop_reason:
                context["stop_reason"] = transition.stop_reason
            state_id = transition.to_state
        context["stop_reason"] = "incomplete_retry_limit"
        self._append_incomplete_record(context, "state machine exceeded max_steps")
        return context

    def _execute_state(self, state_id: str, context: TraceExecutionContext) -> Dict[str, Any]:
        declaration = (self.graph.get("states") or {}).get(state_id, {})
        executor_refs = list(declaration.get("executor_refs") or [])
        if executor_refs:
            return self._execute_refs(state_id, context, executor_refs, str(declaration.get("merge_policy") or "single_output"))
        executor = self.executors.get(state_id)
        if not executor:
            return {"status": "skipped", "outputs": {}}
        try:
            output = executor(context)
            if output is None:
                output = {}
            if not isinstance(output, dict):
                output = {"status": "succeeded", "outputs": {"schema_result_type": type(output).__name__}}
            return output
        except Exception as exc:
            return {"status": "failed", "outputs": {}, "errors": [str(exc)]}

    def _execute_refs(self, state_id: str, context: TraceExecutionContext, executor_refs: list[Dict[str, Any]], merge_policy: str) -> Dict[str, Any]:
        if merge_policy == "parallel_agreement":
            results = self._execute_refs_parallel(context, executor_refs)
        else:
            results = self._execute_refs_sequential(context, executor_refs)
        return self._merge_results(state_id, executor_refs, results, merge_policy)

    def _execute_refs_sequential(self, context: TraceExecutionContext, executor_refs: list[Dict[str, Any]]) -> list[SubagentResult]:
        results = []
        for reference in executor_refs:
            result = self._execute_ref(context, reference)
            results.append(result)
            context.setdefault("executor_outputs", {})[result.executor_id] = result.output
        return results

    def _execute_refs_parallel(self, context: TraceExecutionContext, executor_refs: list[Dict[str, Any]]) -> list[SubagentResult]:
        results = []
        with ThreadPoolExecutor(max_workers=max(1, len(executor_refs))) as executor:
            futures = {executor.submit(self._execute_ref, context, reference): reference for reference in executor_refs}
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                context.setdefault("executor_outputs", {})[result.executor_id] = result.output
        return results

    def _execute_ref(self, context: TraceExecutionContext, reference: Dict[str, Any]) -> SubagentResult:
        executor_id = str(reference.get("executor_id") or reference.get("id") or reference.get("role") or "executor")
        role = str(reference.get("role") or executor_id)
        executor = self.executors.get(executor_id)
        if not executor:
            if reference.get("required", True):
                return SubagentResult(executor_id=executor_id, executor_type=str(reference.get("executor_type") or "unknown"), role=role, status="failed", error="executor missing", missing_evidence=["executor"])
            return SubagentResult(executor_id=executor_id, executor_type=str(reference.get("executor_type") or "unknown"), role=role, status="skipped")
        try:
            output = executor(context) or {}
            if isinstance(output, SubagentResult):
                return output
            status = str(output.get("status") or "succeeded") if isinstance(output, dict) else "succeeded"
            evidence_refs = list(output.get("evidence_refs") or []) if isinstance(output, dict) else []
            claims = list(output.get("claims") or []) if isinstance(output, dict) else []
            contradictions = list(output.get("contradictions") or []) if isinstance(output, dict) else []
            missing_evidence = list(output.get("missing_evidence") or []) if isinstance(output, dict) else []
            return SubagentResult(executor_id=executor_id, executor_type=str(reference.get("executor_type") or "deterministic"), role=role, status=status, output=output, evidence_refs=evidence_refs, claims=claims, contradictions=contradictions, missing_evidence=missing_evidence)
        except Exception as exc:
            return SubagentResult(executor_id=executor_id, executor_type=str(reference.get("executor_type") or "deterministic"), role=role, status="failed", error=str(exc))

    def _merge_results(self, state_id: str, executor_refs: list[Dict[str, Any]], results: list[SubagentResult], merge_policy: str) -> Dict[str, Any]:
        errors = [str(result.error) for result in results if result.error]
        evidence_refs = [evidence for result in results for evidence in result.evidence_refs]
        outputs = {result.executor_id: result.output for result in results}
        status = "failed" if any(result.status == "failed" and self._ref_required(result.executor_id, executor_refs) for result in results) else "succeeded"
        if merge_policy == "single_output" and results:
            outputs = {"result": results[-1].output}
        if merge_policy == "contradiction_record":
            contradictions = [item for result in results for item in result.contradictions]
            outputs = {**outputs, "contradictions": contradictions}
        if merge_policy == "parallel_agreement":
            claims = [item for result in results for item in result.claims]
            contradictions = [item for result in results for item in result.contradictions]
            outputs = {**outputs, "claims": claims, "contradictions": contradictions, "agreement": not contradictions}
        return {"status": status, "outputs": outputs, "subagent_results": results, "evidence_refs": evidence_refs, "errors": errors}

    def _ref_required(self, executor_id: str, executor_refs: list[Dict[str, Any]]) -> bool:
        for reference in executor_refs:
            if str(reference.get("executor_id") or reference.get("id") or reference.get("role") or "executor") == executor_id:
                return bool(reference.get("required", True))
        return True

    def _evaluate_gates(self, state_id: str, context: TraceExecutionContext, result: Dict[str, Any]) -> list[GateDecision]:
        gates = []
        for gate_id in (self.graph.get("states", {}).get(state_id, {}).get("gates") or []):
            gates.append(evaluate_gate(str(gate_id), context, result))
        return gates

    def _select_transition(self, state_id: str, context: TraceExecutionContext, gates: list[GateDecision]) -> TransitionDecision:
        transitions = (self.graph.get("transitions") or {}).get(state_id, [])
        for transition in transitions:
            condition = str(transition.get("condition") or "always")
            if self._condition_matches(condition, context, gates):
                to_state = str(transition.get("to") or "completed")
                stop_reason = "completed" if to_state == "completed" and state_id == "finalize" else ""
                if to_state == "completed" and state_id == "incomplete_or_human_review":
                    stop_reason = context.get("stop_reason") or "human_review_required"
                return TransitionDecision(
                    from_state=state_id,
                    to_state=to_state,
                    condition=condition,
                    reason=self._transition_reason(condition, gates),
                    gate_ids=[gate.gate_id for gate in gates],
                    retry_count=self._attempts[state_id] - 1,
                    stop_reason=stop_reason,
                )
        return TransitionDecision(from_state=state_id, to_state="incomplete_or_human_review", condition="no_transition", reason="no matching transition", stop_reason="incomplete_gate_failed")

    def _condition_matches(self, condition: str, context: TraceExecutionContext, gates: list[GateDecision]) -> bool:
        failed = [gate for gate in gates if not gate.passed]
        if condition == "always":
            return True
        if condition == "stop":
            return True
        if condition == "gate_failed_recoverable":
            return bool(failed and all(gate.recoverable for gate in failed))
        if condition == "gate_failed_unrecoverable":
            return bool(failed and any(not gate.recoverable for gate in failed))
        if condition == "fulfillment_requires_attribute":
            return _attribute_required(context)
        return False

    def _retry_exceeded(self, state_id: str, transition: TransitionDecision) -> bool:
        if transition.to_state != state_id and transition.to_state not in {"collect_evidence", "run_attribution_probes"}:
            return False
        state_limit = (self.graph.get("states") or {}).get(state_id, {}).get("max_retries")
        max_retries = int(state_limit if state_limit is not None else (self.graph.get("limits") or {}).get("max_retries_per_state") or 1)
        return transition.retry_count >= max_retries

    def _transition_reason(self, condition: str, gates: list[GateDecision]) -> str:
        failed = [gate.reason for gate in gates if not gate.passed]
        if failed:
            return "；".join(failed)
        return condition

    def _append_record(self, state_id: str, context: TraceExecutionContext, result: Dict[str, Any], gates: list[GateDecision], transition: TransitionDecision) -> None:
        history = context.setdefault("state_history", [])
        history.append(
            TraceStateRecord(
                state_id=state_id,
                role=str((self.graph.get("states") or {}).get(state_id, {}).get("role") or state_id),
                status=str(result.get("status") or "succeeded"),
                attempt=self._attempts[state_id],
                started_at=str(result.get("started_at") or now_iso()),
                finished_at=str(result.get("finished_at") or now_iso()),
                input_summary=dict(result.get("input_summary") or {}),
                outputs=dict(result.get("outputs") or {}),
                subagent_results=list(result.get("subagent_results") or []),
                evidence_refs=list(result.get("evidence_refs") or []),
                gate_decisions=gates,
                transition_decision=transition,
                errors=list(result.get("errors") or []),
            )
        )

    def _append_incomplete_record(self, context: TraceExecutionContext, reason: str) -> None:
        transition = TransitionDecision(from_state="max_steps", to_state="completed", condition="max_steps", reason=reason, stop_reason="incomplete_retry_limit")
        self._append_record("incomplete_or_human_review", context, {"status": "blocked", "errors": [reason]}, [], transition)


def _context_subagent_results(context: TraceExecutionContext) -> list[SubagentResult]:
    history = list(context.get("state_history") or [])
    return [result for record in history for result in getattr(record, "subagent_results", [])]


def _result_subagent_results(result: Dict[str, Any]) -> list[SubagentResult]:
    return list(result.get("subagent_results") or [])


def _context_contradictions(context: TraceExecutionContext, result: Dict[str, Any]) -> list[Any]:
    contradictions = list(result.get("contradictions") or [])
    for subagent in _result_subagent_results(result) + _context_subagent_results(context):
        contradictions.extend(list(getattr(subagent, "contradictions", []) or []))
    return contradictions


def _context_unsupported_claims(context: TraceExecutionContext, result: Dict[str, Any]) -> list[Any]:
    unsupported = list(result.get("unsupported_claims") or [])
    for subagent in _result_subagent_results(result) + _context_subagent_results(context):
        unsupported.extend(list(getattr(subagent, "missing_evidence", []) or []))
    return unsupported


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple, set)):
        return bool(value)
    return True


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _attribute_required(context: TraceExecutionContext) -> bool:
    judge = context.get("judge_result")
    if not judge:
        return False
    assessments = list(getattr(judge, "fulfillment_assessments", []) or [])
    for assessment in assessments:
        status = _item_value(assessment, "status", "")
        if status in {"not_fulfilled", "not_evaluable"}:
            return True
        if _item_value(assessment, "blocking", False):
            return True
    overall = getattr(judge, "overall_fulfillment", {}) or {}
    overall_status = _item_value(overall, "status", "")
    if overall_status in {"not_fulfilled", "not_evaluable"}:
        return True
    if assessments:
        return False
    return False


def evaluate_gate(gate_id: str, context: TraceExecutionContext, result: Dict[str, Any]) -> GateDecision:
    """通用 gate 评估器。spec/info-volume.md 后只保留通用流程 gate。"""
    if gate_id == "trace_available":
        trace = context.get("trace")
        passed = bool(trace and getattr(trace, "status", "ok") != "error")
        missing = [] if passed else (["trace.status"] if trace else ["trace"])
        return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=passed, checked_inputs={"trace": bool(trace), "status": getattr(trace, "status", "") if trace else ""}, missing_evidence=missing, recoverable=False, reason="trace exists" if passed else "trace missing or errored")
    if gate_id == "business_expectation_coverage":
        judge = context.get("judge_result")
        expectations = list(getattr(judge, "business_expectations", []) or []) if judge else []
        passed = bool(expectations)
        return GateDecision(gate_id=gate_id, gate_type="business_expectation_coverage", passed=passed, checked_inputs={"expectation_count": len(expectations)}, missing_evidence=[] if passed else ["business_expectations"], recoverable=True, recommended_transition="build_business_expectations", reason="business expectations available" if passed else "business expectations missing")
    if gate_id == "fulfillment_assessment_coverage":
        judge = context.get("judge_result")
        expectations = list(getattr(judge, "business_expectations", []) or []) if judge else []
        assessments = list(getattr(judge, "fulfillment_assessments", []) or []) if judge else []
        expected_ids = {_item_value(item, "expectation_id") for item in expectations if _item_value(item, "expectation_id")}
        assessed_ids = {_item_value(item, "expectation_id") for item in assessments if _item_value(item, "expectation_id")}
        missing_ids = sorted(expected_ids - assessed_ids)
        passed = bool(assessments) and not missing_ids and _has_value(getattr(judge, "overall_fulfillment", {}) if judge else {})
        missing = [] if passed else [*(["fulfillment_assessments"] if not assessments else []), *(["overall_fulfillment"] if not (judge and _has_value(getattr(judge, "overall_fulfillment", {}))) else []), *missing_ids]
        return GateDecision(gate_id=gate_id, gate_type="fulfillment_assessment_coverage", passed=passed, checked_inputs={"expectation_count": len(expectations), "assessment_count": len(assessments), "missing_expectation_ids": missing_ids}, missing_evidence=missing, recoverable=True, recommended_transition="evaluate_fulfillment", reason="fulfillment assessments cover expectations" if passed else "fulfillment assessments incomplete")
    if gate_id == "contradiction_free":
        contradictions = _context_contradictions(context, result)
        return GateDecision(gate_id=gate_id, gate_type="contradiction_free", passed=not contradictions, contradictions=contradictions, recoverable=True, recommended_transition="collect_evidence", reason="no contradictions" if not contradictions else "contradictions require critique or more evidence")
    if gate_id == "unsupported_claims_absent":
        unsupported_claims = _context_unsupported_claims(context, result)
        return GateDecision(gate_id=gate_id, gate_type="unsupported_claims_absent", passed=not unsupported_claims, unsupported_claims=unsupported_claims, recoverable=True, recommended_transition="collect_evidence", reason="no unsupported claims" if not unsupported_claims else "unsupported claims require evidence")
    if gate_id == "attribute_targets_expectation_gap":
        required = _attribute_required(context)
        attribute = context.get("attribute_result")
        targets = list(getattr(attribute, "expectation_attributions", []) or []) if attribute else []
        passed = bool(not required or targets or not attribute)
        return GateDecision(gate_id=gate_id, gate_type="attribute_targets_expectation_gap", passed=passed, checked_inputs={"fulfillment_requires_attribute": required, "target_count": len(targets)}, missing_evidence=[] if passed else ["expectation_attributions"], recoverable=False, recommended_transition="finalize", reason="attribute targets fulfillment gaps" if required else "attribute not required by fulfillment")
    if gate_id == "expectation_attribution_evidence":
        attribute = context.get("attribute_result")
        if not attribute and not _attribute_required(context):
            return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=True, reason="attribute not required")
        attributions = list(getattr(attribute, "expectation_attributions", []) or []) if attribute else []
        passed = bool(attributions or (attribute and getattr(attribute, "root_cause_hypothesis", "")))
        return GateDecision(gate_id=gate_id, gate_type="expectation_attribution_evidence", passed=passed, checked_inputs={"attribution_count": len(attributions)}, missing_evidence=[] if passed else ["expectation_attributions"], recoverable=not passed, recommended_transition="run_attribution_probes", reason="expectation attribution evidence available" if passed else "expectation attribution evidence missing")
    if gate_id == "finalization_ready":
        passed = bool(context.get("trace") and context.get("judge_result"))
        return GateDecision(gate_id=gate_id, gate_type="finalization_ready", passed=passed, checked_inputs={"has_trace": bool(context.get("trace")), "has_judge_result": bool(context.get("judge_result"))}, missing_evidence=[] if passed else ["trace", "judge_result"], recoverable=False, reason="finalization ready" if passed else "finalization missing trace or judge")
    return GateDecision(gate_id=gate_id, gate_type="unknown", passed=True, reason="no generic evaluator configured")


def flatten_gate_decisions(history: list[TraceStateRecord]) -> list[GateDecision]:
    return [gate for record in history for gate in record.gate_decisions]


def flatten_transition_decisions(history: list[TraceStateRecord]) -> list[TransitionDecision]:
    return [record.transition_decision for record in history if record.transition_decision]


def subagent_result(executor_id: str, executor_type: str, role: str, output: Any = None, evidence_refs: Optional[list[Dict[str, Any]]] = None, status: str = "succeeded") -> SubagentResult:
    return SubagentResult(executor_id=executor_id, executor_type=executor_type, role=role, output=output, evidence_refs=evidence_refs or [], status=status)