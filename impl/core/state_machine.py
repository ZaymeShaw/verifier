from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Optional

from .schema import GateDecision, SubagentResult, TraceExecutionContext, TraceStateRecord, TransitionDecision, attribute_causal_category, attribute_probe_evidence, judge_primary_signal, now_iso, to_dict

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
        "build_business_expectations": {"role": "build_business_expectations", "gates": ["consumer_contract_present", "business_expectation_coverage"]},
        "evaluate_fulfillment": {"role": "evaluate_fulfillment", "gates": ["fulfillment_assessment_coverage", "boundary_decision_present", "derived_verdict_consistency"]},
        "fulfillment_critic": {"role": "fulfillment_critic", "gates": ["contradiction_free", "unsupported_claims_absent", "fulfillment_assessment_coverage"]},
        "attribute_expectations": {"role": "attribute_expectations", "gates": ["attribute_targets_expectation_gap"]},
        "run_attribution_probes": {"role": "run_attribution_probes", "gates": ["probe_evidence_or_blocked_reason"]},
        "attribution_critic": {"role": "attribution_critic", "gates": ["expectation_attribution_evidence", "causal_category_support", "improvement_direction_support"]},
        "finalize": {"role": "finalize", "gates": ["finalization_ready", "contradiction_free", "unsupported_claims_absent"]},
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
        "run_attribution_probes": [
            {"to": "attribution_critic", "condition": "always"},
        ],
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
                if state_id in ("fulfillment_critic", "evaluate_fulfillment", "build_business_expectations"):
                    judge = context.get("judge_result")
                    if judge:
                        exp_ids = [getattr(e, "expectation_id", e.get("expectation_id") if isinstance(e, dict) else None) for e in (getattr(judge, "business_expectations", []) or [])]
                        ass_ids = [getattr(a, "expectation_id", a.get("expectation_id") if isinstance(a, dict) else None) for a in (getattr(judge, "fulfillment_assessments", []) or [])]
                        _log.warning("  judge: exp_ids=%s ass_ids=%s verdict=%s overall=%s", exp_ids, ass_ids, getattr(judge, "verdict", ""), getattr(judge, "overall_fulfillment", {}))
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


def _judge_has_intent(judge: Any) -> bool:
    primary_signal = judge_primary_signal(judge)
    return bool(judge and (_has_value(primary_signal.get("business_expectations")) or _has_value(getattr(judge, "reconstructed_intent", "")) or _has_value(getattr(judge, "expected", None))))


def _judge_has_comparison(judge: Any) -> bool:
    return bool(judge and _has_value(getattr(judge, "actual", None)) and (_has_value(getattr(judge, "expected", None)) or _has_value(getattr(judge, "reconstructed_intent", ""))))


def _judge_has_derivation(judge: Any) -> bool:
    return bool(judge and (_has_value(getattr(judge, "verdict_derivation", {})) or _has_value(getattr(judge, "reasoning_summary", "")) or _has_value(getattr(judge, "judge_basis", ""))))


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
    return bool(getattr(judge, "verdict", "") in {"incorrect", "uncertain"})


def _judge_has_fulfillment(judge: Any) -> bool:
    return bool(judge and _has_value(getattr(judge, "fulfillment_assessments", [])) and _has_value(getattr(judge, "overall_fulfillment", {})))


def _expected_fulfillment_state(judge: Any) -> tuple[str, str, list[str]]:
    assessments = list(getattr(judge, "fulfillment_assessments", []) or []) if judge else []
    statuses = [_item_value(item, "status", "") for item in assessments]
    failing_statuses = {"not_fulfilled", "not_evaluable"}
    blocking_ids = [_item_value(item, "expectation_id") for item in assessments if _item_value(item, "status", "") in failing_statuses and _item_value(item, "blocking", False)]
    if not statuses:
        return "uncertain", "not_evaluable", []
    if any(status == "not_fulfilled" for status in statuses):
        return "incorrect", "not_fulfilled", blocking_ids
    if any(status == "not_evaluable" for status in statuses):
        return "uncertain", "not_evaluable", blocking_ids
    return "correct", "fulfilled", []


def _derived_verdict_contradictions(judge: Any) -> list[str]:
    if not judge or not _judge_has_fulfillment(judge):
        return []
    expected_verdict, expected_status, expected_blocking = _expected_fulfillment_state(judge)
    overall = getattr(judge, "overall_fulfillment", {}) or {}
    actual_status = _item_value(overall, "status", "")
    actual_blocking = list(_item_value(overall, "blocking_expectations", []) or [])
    contradictions = []
    if getattr(judge, "verdict", "") != expected_verdict:
        contradictions.append(f"verdict={getattr(judge, 'verdict', '')} conflicts with fulfillment-derived verdict={expected_verdict}")
    if actual_status != expected_status:
        contradictions.append(f"overall_fulfillment.status={actual_status} conflicts with fulfillment-derived status={expected_status}")
    if sorted(str(item) for item in actual_blocking) != sorted(str(item) for item in expected_blocking):
        contradictions.append("overall_fulfillment.blocking_expectations conflicts with non-fulfilled assessments")
    return contradictions


def evaluate_gate(gate_id: str, context: TraceExecutionContext, result: Dict[str, Any]) -> GateDecision:
    if gate_id == "trace_available":
        trace = context.get("trace")
        passed = bool(trace and getattr(trace, "status", "ok") != "error")
        missing = [] if passed else (["trace.status"] if trace else ["trace"])
        return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=passed, checked_inputs={"trace": bool(trace), "status": getattr(trace, "status", "") if trace else ""}, missing_evidence=missing, recoverable=False, reason="trace exists" if passed else "trace missing or errored")
    if gate_id == "consumer_contract_present":
        judge = context.get("judge_result")
        passed = bool(judge and _has_value(getattr(judge, "consumer_contract", {})))
        return GateDecision(gate_id=gate_id, gate_type="consumer_contract_present", passed=passed, checked_inputs={"has_judge": bool(judge)}, missing_evidence=[] if passed else ["consumer_contract"], recoverable=True, recommended_transition="build_business_expectations", reason="consumer contract available" if passed else "consumer contract missing")
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
        missing = [] if passed else [*( ["fulfillment_assessments"] if not assessments else []), *( ["overall_fulfillment"] if not (judge and _has_value(getattr(judge, "overall_fulfillment", {}))) else []), *missing_ids]
        return GateDecision(gate_id=gate_id, gate_type="fulfillment_assessment_coverage", passed=passed, checked_inputs={"expectation_count": len(expectations), "assessment_count": len(assessments), "missing_expectation_ids": missing_ids}, missing_evidence=missing, recoverable=True, recommended_transition="evaluate_fulfillment", reason="fulfillment assessments cover expectations" if passed else "fulfillment assessments incomplete")
    if gate_id == "boundary_decision_present":
        judge = context.get("judge_result")
        assessments = list(getattr(judge, "fulfillment_assessments", []) or []) if judge else []
        has_assessment_boundary = any(_has_value(_item_value(item, "boundary_decision", {})) for item in assessments)
        passed = bool(judge and (has_assessment_boundary or _has_value(getattr(judge, "boundary_decision", None)) or _has_value(getattr(judge, "evaluation_boundary", None))))
        return GateDecision(gate_id=gate_id, gate_type="boundary_decision_present", passed=passed, checked_inputs={"has_judge": bool(judge), "assessment_count": len(assessments)}, missing_evidence=[] if passed else ["boundary decision"], recoverable=False, reason="fulfillment boundary available" if passed else "fulfillment boundary missing")
    if gate_id == "derived_verdict_consistency":
        judge = context.get("judge_result")
        contradictions = _derived_verdict_contradictions(judge)
        passed = bool(judge and _judge_has_fulfillment(judge) and _has_value(getattr(judge, "verdict", "")) and not contradictions)
        return GateDecision(gate_id=gate_id, gate_type="derived_verdict_consistency", passed=passed, checked_inputs={"has_judge": bool(judge), "has_fulfillment": _judge_has_fulfillment(judge)}, missing_evidence=[] if passed or contradictions else ["derived verdict from fulfillment"], contradictions=contradictions, recoverable=True, recommended_transition="evaluate_fulfillment", reason="derived verdict matches fulfillment state" if passed else "derived verdict conflicts with fulfillment state" if contradictions else "derived verdict lacks fulfillment basis")
    if gate_id == "judge_intent_present":
        judge = context.get("judge_result")
        passed = _judge_has_intent(judge)
        return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=passed, checked_inputs={"has_judge": bool(judge)}, missing_evidence=[] if passed else ["reconstructed_intent"], recoverable=True, recommended_transition="judge_compare", reason="judge intent available" if passed else "judge intent missing")
    if gate_id == "judge_expected_actual":
        judge = context.get("judge_result")
        passed = _judge_has_comparison(judge)
        return GateDecision(gate_id=gate_id, gate_type="expected_actual_coverage", passed=passed, checked_inputs={"has_judge": bool(judge), "has_actual": bool(judge and _has_value(getattr(judge, "actual", None))), "has_expected_or_intent": bool(judge and (_has_value(getattr(judge, "expected", None)) or _has_value(getattr(judge, "reconstructed_intent", ""))))}, missing_evidence=[] if passed else ["expected/actual comparison"], recoverable=True, recommended_transition="collect_evidence", reason="judge comparison covered" if passed else "judge comparison lacks expected/actual coverage")
    if gate_id == "judge_verdict_derivation":
        judge = context.get("judge_result")
        passed = _judge_has_derivation(judge)
        return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=passed, checked_inputs={"has_judge": bool(judge)}, missing_evidence=[] if passed else ["verdict_derivation"], recoverable=True, recommended_transition="judge_compare", reason="judge verdict derivation available" if passed else "judge verdict derivation missing")
    if gate_id == "judge_boundary":
        judge = context.get("judge_result")
        passed = bool(judge and (_has_value(getattr(judge, "boundary_decision", None)) or _has_value(getattr(judge, "evaluation_boundary", None))))
        return GateDecision(gate_id=gate_id, gate_type="boundary_decision_present", passed=passed, checked_inputs={"has_judge": bool(judge)}, missing_evidence=[] if passed else ["boundary decision"], recoverable=False, reason="judge boundary available" if passed else "judge boundary missing")
    if gate_id == "contradiction_free":
        contradictions = _context_contradictions(context, result)
        return GateDecision(gate_id=gate_id, gate_type="contradiction_free", passed=not contradictions, contradictions=contradictions, recoverable=True, recommended_transition="collect_evidence", reason="no contradictions" if not contradictions else "contradictions require critique or more evidence")
    if gate_id == "unsupported_claims_absent":
        unsupported_claims = _context_unsupported_claims(context, result)
        return GateDecision(gate_id=gate_id, gate_type="unsupported_claims_absent", passed=not unsupported_claims, unsupported_claims=unsupported_claims, recoverable=True, recommended_transition="collect_evidence", reason="no unsupported claims" if not unsupported_claims else "unsupported claims require evidence")
    if gate_id == "attribute_judge_gap":
        required = _attribute_required(context)
        return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=required, checked_inputs={"judge_requires_attribute": required}, missing_evidence=[] if required else ["incorrect_or_uncertain_judge_gap"], recoverable=False, recommended_transition="finalize", reason="attribute has inspectable judge gap" if required else "attribute not required by judge verdict")
    if gate_id == "probe_available_or_incomplete":
        attribute = context.get("attribute_result")
        probe_evidence = attribute_probe_evidence(attribute) if attribute else []
        incomplete_reason = getattr(attribute, "incomplete_reason", "") if attribute else ""
        passed = bool(probe_evidence or incomplete_reason or not _attribute_required(context))
        return GateDecision(gate_id=gate_id, gate_type="probe_available_or_incomplete", passed=passed, checked_inputs={"probe_evidence_count": len(probe_evidence), "has_incomplete_reason": bool(incomplete_reason)}, missing_evidence=[] if passed else ["probe_evidence or incomplete_reason"], recoverable=True, recommended_transition="attribute_probe", reason="probe evidence or incomplete marker available" if passed else "probe evidence missing")
    if gate_id == "attribute_evidence":
        attribute = context.get("attribute_result")
        if not attribute:
            passed = not _attribute_required(context)
            return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=passed, checked_inputs={"judge_requires_attribute": _attribute_required(context)}, missing_evidence=[] if passed else ["attribute_result"], recoverable=not passed, recommended_transition="attribute_probe", reason="attribute not required" if passed else "attribute result missing")
        quality = getattr(attribute, "analysis_quality", {}) or {}
        passed = quality.get("passed") is True or bool(getattr(attribute, "incomplete_reason", ""))
        return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=passed, checked_inputs={"analysis_quality_passed": quality.get("passed"), "has_incomplete_reason": bool(getattr(attribute, "incomplete_reason", ""))}, missing_evidence=list(quality.get("missing") or []), recoverable=False, reason="attribute evidence resolved" if passed else "attribute evidence incomplete")
    if gate_id == "attribute_chain_coverage":
        attribute = context.get("attribute_result")
        if not attribute and not _attribute_required(context):
            return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=True, reason="attribute not required")
        chain_nodes = list(getattr(attribute, "chain_nodes", []) or []) if attribute else []
        earliest = getattr(attribute, "earliest_divergence", {}) if attribute else {}
        suspected = list(getattr(attribute, "suspected_locations", []) or []) if attribute else []
        incomplete = bool(getattr(attribute, "incomplete_reason", "")) if attribute else False
        passed = bool((chain_nodes and earliest and (suspected or incomplete)) or incomplete)
        missing = []
        if not chain_nodes:
            missing.append("chain_nodes")
        if not earliest:
            missing.append("earliest_divergence")
        if not suspected and not incomplete:
            missing.append("suspected_locations_or_incomplete_reason")
        return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=passed, checked_inputs={"chain_node_count": len(chain_nodes), "has_earliest_divergence": bool(earliest), "suspected_location_count": len(suspected), "has_incomplete_reason": incomplete}, missing_evidence=[] if passed else missing, recoverable=True, recommended_transition="attribute_probe", reason="attribute chain coverage available" if passed else "attribute chain coverage incomplete")
    if gate_id == "attribute_patch_direction":
        attribute = context.get("attribute_result")
        if not attribute and not _attribute_required(context):
            return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=True, reason="attribute not required")
        patch_direction = list(getattr(attribute, "patch_direction", []) or []) if attribute else []
        incomplete = bool(getattr(attribute, "incomplete_reason", "")) if attribute else False
        passed = bool(patch_direction or incomplete)
        return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=passed, checked_inputs={"patch_direction_count": len(patch_direction), "has_incomplete_reason": incomplete}, missing_evidence=[] if passed else ["patch_direction_or_incomplete_reason"], recoverable=True, recommended_transition="attribute_probe", reason="attribute patch direction or incomplete marker available" if passed else "attribute patch direction missing")
    if gate_id == "attribute_targets_expectation_gap":
        required = _attribute_required(context)
        attribute = context.get("attribute_result")
        targets = list(getattr(attribute, "expectation_attributions", []) or []) if attribute else []
        passed = bool(not required or targets or not attribute)
        return GateDecision(gate_id=gate_id, gate_type="attribute_targets_expectation_gap", passed=passed, checked_inputs={"fulfillment_requires_attribute": required, "target_count": len(targets)}, missing_evidence=[] if passed else ["expectation_attributions"], recoverable=False, recommended_transition="finalize", reason="attribute targets fulfillment gaps" if required else "attribute not required by fulfillment")
    if gate_id == "probe_evidence_or_blocked_reason":
        attribute = context.get("attribute_result")
        probe_evidence = attribute_probe_evidence(attribute) if attribute else []
        incomplete_reason = getattr(attribute, "incomplete_reason", "") if attribute else ""
        if not attribute:
            import logging as _l; _l.getLogger("verifier.state_machine").warning(f"[gate:{gate_id}] attribute_result is None/missing in context keys={list(context.keys())}")
        elif not incomplete_reason and not probe_evidence:
            import logging as _l; _l.getLogger("verifier.state_machine").warning(f"[gate:{gate_id}] attribute has no probe evidence/incomplete_reason; causal_category={attribute_causal_category(attribute)}")
        passed = bool(probe_evidence or incomplete_reason or not _attribute_required(context))
        return GateDecision(gate_id=gate_id, gate_type="probe_evidence_or_blocked_reason", passed=passed, checked_inputs={"probe_evidence_count": len(probe_evidence), "has_incomplete_reason": bool(incomplete_reason)}, missing_evidence=[] if passed else ["probe_evidence or incomplete_reason"], recoverable=True, recommended_transition="run_attribution_probes", reason="probe evidence or blocked reason available" if passed else "probe evidence missing")
    if gate_id == "expectation_attribution_evidence":
        attribute = context.get("attribute_result")
        if not attribute and not _attribute_required(context):
            return GateDecision(gate_id=gate_id, gate_type="required_evidence", passed=True, reason="attribute not required")
        attributions = list(getattr(attribute, "expectation_attributions", []) or []) if attribute else []
        passed = bool(attributions or (attribute and getattr(attribute, "incomplete_reason", "")))
        return GateDecision(gate_id=gate_id, gate_type="expectation_attribution_evidence", passed=passed, checked_inputs={"attribution_count": len(attributions)}, missing_evidence=[] if passed else ["expectation_attributions"], recoverable=not passed, recommended_transition="run_attribution_probes", reason="expectation attribution evidence available" if passed else "expectation attribution evidence missing")
    if gate_id == "causal_category_support":
        attribute = context.get("attribute_result")
        attributions = list(getattr(attribute, "expectation_attributions", []) or []) if attribute else []
        supported = bool(attribute_causal_category(attribute) if attribute else "") or any(_has_value(_item_value(item, "causal_category", "")) for item in attributions)
        incomplete = bool(getattr(attribute, "incomplete_reason", "") if attribute else "")
        passed = bool(supported or incomplete or not _attribute_required(context))
        return GateDecision(gate_id=gate_id, gate_type="causal_category_support", passed=passed, checked_inputs={"has_causal_category": supported, "has_incomplete_reason": incomplete}, missing_evidence=[] if passed else ["causal_category"], recoverable=True, recommended_transition="run_attribution_probes", reason="causal category supported" if passed else "causal category missing")
    if gate_id == "improvement_direction_support":
        attribute = context.get("attribute_result")
        attributions = list(getattr(attribute, "expectation_attributions", []) or []) if attribute else []
        directions = list(getattr(attribute, "patch_direction", []) or []) if attribute else []
        directions.extend(direction for item in attributions for direction in (_item_value(item, "improvement_direction", []) or []))
        incomplete = bool(getattr(attribute, "incomplete_reason", "") if attribute else "")
        passed = bool(directions or incomplete or not _attribute_required(context))
        return GateDecision(gate_id=gate_id, gate_type="improvement_direction_support", passed=passed, checked_inputs={"direction_count": len(directions), "has_incomplete_reason": incomplete}, missing_evidence=[] if passed else ["improvement_direction"], recoverable=True, recommended_transition="run_attribution_probes", reason="improvement direction available" if passed else "improvement direction missing")
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
