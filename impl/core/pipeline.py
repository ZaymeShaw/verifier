from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from .analysis import analyze_project
from .attribute import attribute_failure
from .check import check_chain
from .cluster import cluster_attributes
from .frontend_view import build_frontend_view
from .interaction_protocol import normalize_case_interaction
from .judge import judge_trace
from .project_loader import load_adapter, load_project
from .schema import AttributeResult, BatchRunResult, CheckReport, ClusterSummary, FrontendViewModel, JudgeResult, ProjectAnalysis, RunTrace
from .state_machine import TraceStateMachineRunner, flatten_gate_decisions, flatten_transition_decisions

IMPL_ROOT = Path(__file__).resolve().parents[1]


def analysis(project_id: str) -> ProjectAnalysis:
    return analyze_project(project_id)


def build(project_id: str) -> Dict[str, Any]:
    project_analysis = analyze_project(project_id)
    return {
        "project_id": project_analysis.project_id,
        "source_analysis": {"project_id": project_analysis.project_id, "documents": project_analysis.documents},
        "frontend_architecture": project_analysis.frontend_build_handoff.get("frontend_architecture", {}),
        "project_frontend_standards": project_analysis.frontend_build_handoff.get("project_frontend_standards", {}),
        "display_contract": project_analysis.frontend_build_handoff.get("display_contract", {}),
        "application_startup_steps": [],
    }


def live_run(project_id: str, input_data: Dict[str, Any]) -> RunTrace:
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    request = adapter.build_request(input_data)
    if adapter.has_provided_output(input_data, request):
        raw = adapter.provided_output_raw(input_data, request)
        trace = adapter.to_run_trace(input_data, request, raw)
        trace.project_fields = {**(trace.project_fields or {}), "execution_mode": "provided", "output_source": "provided_output"}
        return trace
    try:
        raw = adapter.call_or_prepare(request)
    except Exception as exc:
        trace = RunTrace(
            trace_id=f"run-error-{request.get('case_id') or project_id}",
            project_id=project_id,
            input=input_data,
            normalized_request=request,
            status="error",
            error=str(exc),
            runtime_logs=["business service call failed"],
            project_fields={"execution_mode": "live", "output_source": "live_service_unavailable"},
            execution_trace=[{"stage": "project.call", "status": "failed", "evidence": str(exc)}],
        )
        return trace
    trace = adapter.to_run_trace(input_data, request, raw)
    trace.project_fields = {**(trace.project_fields or {}), "execution_mode": "live", "output_source": "live_service"}
    return trace


def judge(project_id: str, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    pre_judge_result = adapter.pre_judge_result(trace, expected_intent=expected_intent)
    if pre_judge_result is not None:
        return adapter.reconcile_judge_result(trace, pre_judge_result)
    project_judge_context = adapter.build_judge_context(trace)
    project_judge_context = {**(project_judge_context or {}), "intent_frame": adapter.build_intent_frame(trace)}
    result = judge_trace(spec, trace, expected_intent=expected_intent, project_judge_context=project_judge_context)
    return adapter.reconcile_judge_result(trace, result)


def attribute(project_id: str, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    result = attribute_failure(spec, trace, judge_result, project_attribute_context=adapter.build_attribute_context(trace, judge_result))
    result = adapter.apply_attribution_probes(trace, judge_result, result)
    return adapter.normalize_attribute_result(trace, judge_result, result)


def incomplete_state_attribute_result(trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    reason = trace.stop_reason or "state machine stopped before producing failure attribution"
    evidence = list(judge_result.evidence or [reason])
    return AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or ""),
        failure_category="needs_human_review",
        failure_stage="state_machine_incomplete",
        analysis_method="state_machine_incomplete_blocked_attribute",
        evidence_chain=evidence,
        trace_analysis=list(trace.execution_trace or []),
        chain_nodes=[{"name": "state_machine", "status": "not_verified", "evidence": evidence, "reason": reason}],
        local_verifications=[],
        earliest_divergence={"node": "state_machine", "evidence": evidence, "confidence": "unknown"},
        evidence_coverage={"query": bool(trace.input), "actual": bool(trace.extracted_output), "expected": bool(judge_result.expected), "execution_trace": bool(trace.execution_trace), "unsupported_claims": []},
        analysis_quality={"passed": False, "missing": ["completed run_attribution_probes"], "standard": "non-fulfilled business expectations must retain an explicit blocked attribution result."},
        incomplete_reason=reason,
        suspected_locations=[],
        root_cause_hypothesis="状态机未完成归因质量门，当前只能保留待复核失败归因。",
        verification_steps=["检查 state_history 和 gate_decisions，确认 run_attribution_probes 未完成的原因。"],
        patch_direction=["补足当前 case 的归因证据后重新运行；不要在缺少 AttributeResult 时静默通过。"],
        business_impact="该 case 不能进入正式根因聚簇，只能作为待复核失败保留。",
        primary_error_type="needs_human_review",
        error_types=["needs_human_review"],
        severity="unknown",
        needs_human_review=True,
        scenario=str(trace.project_fields.get("scenario") or ""),
        quality_flags=[*(judge_result.quality_flags or []), "attribute_incomplete"],
    )


def cluster(project_id: str, attributes: Iterable[AttributeResult]) -> ClusterSummary:
    return cluster_attributes(project_id, attributes)


def check(
    project_id: str,
    trace: Optional[RunTrace] = None,
    judge_result: Optional[JudgeResult] = None,
    attribute_result: Optional[AttributeResult] = None,
    cluster_summary: Optional[ClusterSummary] = None,
) -> CheckReport:
    return check_chain(load_project(project_id), trace, judge_result, attribute_result, cluster_summary, IMPL_ROOT)


def frontend_view(
    project_id: str,
    trace: Optional[RunTrace] = None,
    judge_result: Optional[JudgeResult] = None,
    attribute_result: Optional[AttributeResult] = None,
    cluster_summary: Optional[ClusterSummary] = None,
    check_report: Optional[CheckReport] = None,
) -> FrontendViewModel:
    spec = load_project(project_id)
    extensions = {}
    if trace:
        extensions = load_adapter(spec).build_frontend_extensions(trace)
    return build_frontend_view(spec, trace, judge_result, attribute_result, cluster_summary, check_report, extensions)


def mock_cases(project_id: str) -> list[Dict[str, Any]]:
    spec = load_project(project_id)
    return load_adapter(spec).build_mock_cases()


def mock_datasets(project_id: str) -> list[Dict[str, Any]]:
    spec = load_project(project_id)
    return load_adapter(spec).build_mock_datasets()


def _unsupported_interactive_run(project_id: str, case_id: str, case: Dict[str, Any]) -> Dict[str, Any]:
    from .schema import to_dict

    trace = RunTrace(
        trace_id=f"interactive-unsupported-{case_id}",
        project_id=project_id,
        input=case,
        normalized_request={},
        status="error",
        error="interactive_intent is not supported by this project adapter",
        runtime_logs=["interactive adapter hook missing"],
        project_fields={"interaction_mode": "interactive_intent", "output_source": "unsupported_interactive_intent"},
        execution_trace=[{"stage": "interactive.dispatch", "status": "failed", "evidence": "adapter does not implement run_interactive"}],
    )
    judge_result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        verdict="uncertain",
        score=0,
        confidence=1,
        judge_method="unsupported_interactive_intent",
        verdict_derivation={"why_verdict": "interactive_intent case cannot run because adapter has no interactive hook", "blocking_gaps": ["adapter.run_interactive missing"]},
        reasoning_summary="该项目 adapter 不支持 interactive_intent，已将该 case 限界为 uncertain，不中断批次。",
        quality_flags=["unsupported_interactive_intent"],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        failure_category="执行能力缺失",
        failure_stage="interactive.dispatch",
        analysis_method="unsupported_interactive_intent",
        chain_nodes=[{"name": "interactive.dispatch", "status": "failed", "evidence": ["adapter.run_interactive missing"], "reason": "interactive_intent unsupported"}],
        earliest_divergence={"node": "interactive.dispatch", "evidence": ["adapter capability missing"], "confidence": "high"},
        analysis_quality={"passed": False, "missing": ["adapter.run_interactive"], "standard": "interactive_intent 必须由项目 adapter 显式支持。"},
        incomplete_reason="adapter does not implement interactive execution",
        root_cause_hypothesis="当前项目未声明或实现 interactive_intent adapter hook。",
        verification_steps=["检查项目 adapter 是否需要支持 run_interactive。", "确认该 case 是否应归属到声明支持 interactive_intent 的项目。"],
        patch_direction=["为该项目补充 run_interactive 实现，或从该项目 mock 池中移除不属于其边界的 interactive_intent case。"],
        quality_flags=["unsupported_interactive_intent"],
    )
    return {"case_id": case_id, "execution_mode": "interactive_intent", "output_source": "unsupported_interactive_intent", "trace": to_dict(trace), "judge": to_dict(judge_result), "attribute": to_dict(attribute_result), "error": trace.error}


def _batch_case(index: int, case: Dict[str, Any], project_id: str, expected_intent: Optional[str]) -> Dict[str, Any]:
    from .schema import to_dict

    normalized = normalize_case_interaction(project_id, case, index) if isinstance(case, dict) else None
    if normalized and normalized.mode == "interactive_intent":
        try:
            adapter = load_adapter(load_project(project_id))
            if not hasattr(adapter, "run_interactive"):
                return _unsupported_interactive_run(project_id, normalized.case_id, normalized.source_case)
            run = adapter.run_interactive(normalized)
            run["case_id"] = normalized.case_id
            run["execution_mode"] = "interactive_intent"
            run["output_source"] = run.get("output_source") or "interactive_adapter"
            return run
        except Exception as exc:
            return _unsupported_interactive_run(project_id, normalized.case_id, normalized.source_case | {"interactive_error": str(exc)})

    case_input = normalized.execution_input if normalized else (case.get("input", case) if isinstance(case, dict) else case)
    if not isinstance(case_input, dict):
        case_input = {"value": case_input}
    case_id = normalized.case_id if normalized else f"case-{index + 1}"
    case_expected = case.get("expected_intent") if isinstance(case, dict) else None
    MAX_RETRIES = 2
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            run = run_chain(project_id, case_input, expected_intent=case_expected or expected_intent)
            run["case_id"] = case_id
            run["execution_mode"] = "provided" if any(key in case_input for key in ("raw_response", "response", "output")) else "live"
            run["output_source"] = (run.get("trace") or {}).get("project_fields", {}).get("output_source")
            if attempt > 0:
                run["retry_attempt"] = attempt
            return run
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                import time as _time
                _time.sleep(2.0 * (attempt + 1))
    error_text = str(last_exc or "batch case failed")
    trace = RunTrace(
        trace_id=f"batch-error-{case_id}",
        project_id=project_id,
        input=case_input,
        normalized_request={},
        status="error",
        error=error_text,
        runtime_logs=[f"batch case failed after {MAX_RETRIES + 1} attempts"],
    )
    judge_result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        verdict="uncertain",
        score=0,
        confidence=1,
        judge_method="batch_case_exception",
        verdict_derivation={"why_verdict": error_text, "blocking_gaps": [f"batch case failed after {MAX_RETRIES + 1} attempts"]},
        reasoning_summary=error_text,
        quality_flags=["batch_case_failed"],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        failure_category="执行失败",
        failure_stage="batch_run",
        analysis_method="batch_case_exception",
        chain_nodes=[{"name": "batch_run", "status": "failed", "evidence": [error_text], "reason": error_text}],
        earliest_divergence={"node": "batch_run", "evidence": [error_text], "confidence": "high"},
        analysis_quality={"passed": False, "missing": ["completed run_chain"], "standard": "单 case 失败需要保留错误并让批次继续。"},
        incomplete_reason=f"batch case failed after {MAX_RETRIES + 1} attempts",
        root_cause_hypothesis=error_text,
        verification_steps=["用相同 case 单独运行 run_chain，定位是输入、adapter 还是外部服务异常。", "检查 trace.error 和 runtime_logs 后再决定是否修改业务实现。"],
        patch_direction=["修复导致 run_chain 抛错的源头；不要只在 batch 层吞掉异常或改展示结果。"],
        quality_flags=["batch_case_failed"],
    )
    return {"case_id": case_id, "execution_mode": "error", "output_source": "batch_case_exception", "trace": to_dict(trace), "judge": to_dict(judge_result), "attribute": to_dict(attribute_result), "error": error_text}


def _batch_error_run(index: int, case: Dict[str, Any], project_id: str, exc: Exception) -> Dict[str, Any]:
    from .schema import to_dict

    case_id = str(case.get("id")) if isinstance(case, dict) and case.get("id") else f"case-{index + 1}"
    case_input = case.get("input", case) if isinstance(case, dict) else {"value": case}
    if not isinstance(case_input, dict):
        case_input = {"value": case_input}
    trace = RunTrace(
        trace_id=f"batch-error-{case_id}",
        project_id=project_id,
        input={**case_input, "case_id": case_id},
        normalized_request={},
        status="error",
        error=str(exc),
        runtime_logs=["batch case failed outside run_chain"],
    )
    judge_result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        verdict="uncertain",
        score=0,
        confidence=1,
        judge_method="batch_future_exception",
        verdict_derivation={"why_verdict": str(exc), "blocking_gaps": ["batch case failed outside run_chain"]},
        reasoning_summary=str(exc),
        quality_flags=["batch_case_failed"],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        failure_category="执行失败",
        failure_stage="batch_run",
        analysis_method="batch_future_exception",
        chain_nodes=[{"name": "batch_run", "status": "failed", "evidence": [str(exc)], "reason": str(exc)}],
        earliest_divergence={"node": "batch_run", "evidence": [str(exc)], "confidence": "high"},
        analysis_quality={"passed": False, "missing": ["completed future result"], "standard": "线程外层失败需要保留错误并让批次继续。"},
        incomplete_reason="batch case failed outside run_chain",
        root_cause_hypothesis=str(exc),
        verification_steps=["检查 batch worker future 的异常栈和对应 case 输入。", "用该 case 单独运行 run_chain 或 adapter 入口复现。"],
        patch_direction=["修复 batch worker 外层异常源头；保持批次继续但不要把异常 case 聚合为正式根因。"],
        quality_flags=["batch_case_failed"],
    )
    return {"case_id": case_id, "execution_mode": "error", "output_source": "batch_future_exception", "trace": to_dict(trace), "judge": to_dict(judge_result), "attribute": to_dict(attribute_result), "error": str(exc)}


def batch_run(
    project_id: str,
    cases: Iterable[Dict[str, Any]],
    expected_intent: Optional[str] = None,
    concurrency: int = 4,
    on_case_done: Optional[Callable[[int, Dict[str, Any]], None]] = None,
) -> BatchRunResult:
    from .schema import to_dict

    case_list = list(cases)
    if not case_list:
        cluster_summary = cluster(project_id, [])
        check_report = check(project_id, None, None, None, cluster_summary)
        return BatchRunResult(project_id=project_id, total=0, runs=[], cluster=to_dict(cluster_summary), check=to_dict(check_report))

    max_workers = max(1, min(int(concurrency or 1), len(case_list)))
    runs_by_index: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_batch_case, index, case, project_id, expected_intent): index
            for index, case in enumerate(case_list)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                run = future.result()
            except Exception as exc:
                run = _batch_error_run(index, case_list[index], project_id, exc)
            runs_by_index[index] = run
            if on_case_done:
                on_case_done(index, run)

    runs = [runs_by_index[index] for index in range(len(case_list))]
    attributes = [AttributeResult(**run["attribute"]) for run in runs if run.get("attribute")]
    cluster_summary = cluster(project_id, attributes)
    # Select representative run: prefer not_fulfilled, else first non-error
    representative = None
    for priority_status in ("not_fulfilled", "partially_fulfilled", "not_evaluable"):
        for run in (runs or []):
            if not isinstance(run, dict): continue
            js = run.get("judge_summary") or run.get("judge") or {}
            if js.get("fulfillment_status") == priority_status or js.get("verdict") == "incorrect":
                representative = run; break
        if representative: break
    if not representative and runs:
        representative = next((r for r in runs if isinstance(r, dict) and not r.get("error")), runs[-1])
    trace = RunTrace(**representative["trace"]) if representative and representative.get("trace") else None
    judge_result = JudgeResult(**representative["judge"]) if representative and representative.get("judge") else None
    attribute_result = AttributeResult(**runs[-1]["attribute"]) if runs and runs[-1].get("attribute") else None
    check_report = check(project_id, trace, judge_result, attribute_result, cluster_summary)
    failed_run_checks = [run.get("check") for run in runs if isinstance(run.get("check"), dict) and not run["check"].get("passed", True)]
    if failed_run_checks:
        failed_issues = []
        for item in failed_run_checks:
            failed_issues.extend(str(issue) for issue in item.get("issues") or [])
        check_report.passed = False
        check_report.issues = list(check_report.issues or []) + [issue for issue in failed_issues if issue not in (check_report.issues or [])]
        if "Batch contains case-level check failures." not in check_report.consistency_gaps:
            check_report.consistency_gaps.append("Batch contains case-level check failures.")
        if "Inspect failed case-level CheckReport before trusting aggregate batch output." not in check_report.recommended_fixes:
            check_report.recommended_fixes.append("Inspect failed case-level CheckReport before trusting aggregate batch output.")
    return BatchRunResult(
        project_id=project_id,
        total=len(runs),
        runs=runs,
        cluster=to_dict(cluster_summary),
        check=to_dict(check_report),
    )


def run_chain(project_id: str, input_data: Dict[str, Any], expected_intent: Optional[str] = None) -> Dict[str, Any]:
    from .schema import to_dict

    spec = load_project(project_id)
    adapter = load_adapter(spec)

    def execute_trace(context: Dict[str, Any]) -> Dict[str, Any]:
        context["trace"] = live_run(project_id, input_data)
        trace = context["trace"]
        return {
            "status": "succeeded" if trace.status != "error" else "failed",
            "input_summary": {"project_id": project_id, "input_keys": sorted(input_data.keys())},
            "outputs": {"trace_id": trace.trace_id, "status": trace.status},
            "evidence_refs": trace.evidence_refs,
            "errors": [trace.error] if trace.error else [],
        }

    def collect_evidence(context: Dict[str, Any]) -> Dict[str, Any]:
        trace = context.get("trace")
        evidence_refs = list(getattr(trace, "evidence_refs", []) or []) if trace else []
        execution_trace = list(getattr(trace, "execution_trace", []) or []) if trace else []
        project_evidence = adapter.collect_state_evidence("collect_evidence", context)
        return {
            "status": "succeeded",
            "outputs": {"evidence_count": len(evidence_refs) + len(project_evidence), "execution_trace_count": len(execution_trace)},
            "evidence_refs": evidence_refs + project_evidence,
        }

    def collect_project_evidence(context: Dict[str, Any]) -> Dict[str, Any]:
        project_evidence = adapter.collect_state_evidence("project_collect_evidence", context)
        return {
            "status": "succeeded",
            "outputs": {"project_evidence_count": len(project_evidence)},
            "evidence_refs": project_evidence,
        }

    def build_expectations(context: Dict[str, Any]) -> Dict[str, Any]:
        trace = context["trace"]
        context["judge_result"] = judge(project_id, trace, expected_intent=expected_intent)
        judge_result = context["judge_result"]
        if hasattr(judge_result, "derive_verdict_from_fulfillment") and judge_result.fulfillment_assessments:
            judge_result.derive_verdict_from_fulfillment()
        return {
            "status": "succeeded",
            "outputs": {
                "consumer_contract": bool(getattr(judge_result, "consumer_contract", {})),
                "business_expectation_count": len(getattr(judge_result, "business_expectations", []) or []),
            },
            "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
        }

    def evaluate_fulfillment(context: Dict[str, Any]) -> Dict[str, Any]:
        judge_result = context["judge_result"]
        if hasattr(judge_result, "derive_verdict_from_fulfillment") and judge_result.fulfillment_assessments:
            judge_result.derive_verdict_from_fulfillment()
        return {
            "status": "succeeded",
            "outputs": {
                "overall_fulfillment": getattr(judge_result, "overall_fulfillment", {}),
                "fulfillment_assessment_count": len(getattr(judge_result, "fulfillment_assessments", []) or []),
                "derived_verdict": judge_result.verdict,
            },
        }

    def probe_attribute(context: Dict[str, Any]) -> Dict[str, Any]:
        trace = context["trace"]
        judge_result = context["judge_result"]
        context["attribute_result"] = attribute(project_id, trace, judge_result)
        attribute_result = context["attribute_result"]
        return {
            "status": "succeeded",
            "outputs": {
                "expectation_attribution_count": len(getattr(attribute_result, "expectation_attributions", []) or []),
                "causal_category": getattr(attribute_result, "causal_category", ""),
                "failure_category": attribute_result.failure_category,
                "failure_stage": attribute_result.failure_stage,
                "incomplete_reason": attribute_result.incomplete_reason,
            },
            "evidence_refs": list(getattr(trace, "evidence_refs", []) or []),
        }

    def finalize(context: Dict[str, Any]) -> Dict[str, Any]:
        trace = context["trace"]
        judge_result = context["judge_result"]
        attribute_result = context.get("attribute_result") or attribute(project_id, trace, judge_result)
        context["attribute_result"] = attribute_result
        context["cluster_summary"] = cluster(project_id, [attribute_result])
        context["check_report"] = check(project_id, trace, judge_result, attribute_result, context["cluster_summary"])
        return {
            "status": "succeeded",
            "outputs": {"stop_reason": "completed", "check_passed": context["check_report"].passed},
        }

    context: Dict[str, Any] = {"project_id": project_id, "input_data": input_data, "expected_intent": expected_intent}
    executors = {
        "execute_or_capture": execute_trace,
        "collect_evidence": collect_evidence,
        "project_collect_evidence": collect_project_evidence,
        "build_business_expectations": build_expectations,
        "evaluate_fulfillment": evaluate_fulfillment,
        "attribute_expectations": probe_attribute,
        "run_attribution_probes": probe_attribute,
        "finalize": finalize,
    }
    executors.update(adapter.state_executors())
    TraceStateMachineRunner(graph=adapter.trace_state_graph() or None, executors=executors).run(context)

    trace = context["trace"]
    trace.state_history = list(context.get("state_history") or [])
    trace.gate_decisions = flatten_gate_decisions(trace.state_history)
    trace.transition_decisions = flatten_transition_decisions(trace.state_history)
    trace.stop_reason = str(context.get("stop_reason") or trace.stop_reason or "completed")
    judge_result = context.get("judge_result")
    if not judge_result:
        judge_result = JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="uncertain",
            actual=trace.extracted_output,
            reconstructed_intent=str(trace.normalized_request.get("query") or trace.normalized_request.get("user_intent") or ""),
            judge_basis="trace_execution_incomplete",
            judge_method="state_machine_human_review",
            verdict_derivation={"blocking_gaps": [trace.error or trace.stop_reason or "trace execution incomplete"], "why_verdict": "trace did not reach judge because execution failed or required human review"},
            boundary_decision={"within_evaluable_scope": False, "reasoning": trace.error or trace.stop_reason or "trace execution incomplete"},
            evaluation_boundary={"primary_boundary_id": "trace_execution_incomplete", "verdict_basis": "judge skipped because trace execution did not complete"},
            evidence=[trace.error or trace.stop_reason or "trace execution incomplete"],
            reasoning_summary=trace.error or "trace execution incomplete; human review required before judge",
            needs_human_review=True,
            quality_flags=["trace_execution_incomplete", "human_review_required"],
        )
        context["judge_result"] = judge_result
    attribute_result = context.get("attribute_result")
    if not attribute_result:
        fulfillment_status = (getattr(judge_result, "overall_fulfillment", {}) or {}).get("status")
        if fulfillment_status == "fulfilled" or judge_result.verdict == "correct":
            attribute_result = attribute(project_id, trace, judge_result)
        else:
            attribute_result = incomplete_state_attribute_result(trace, judge_result)
        context["attribute_result"] = attribute_result
    cluster_summary = context.get("cluster_summary") or (cluster(project_id, [attribute_result]) if attribute_result else cluster(project_id, []))
    check_report = context.get("check_report") or check(project_id, trace, judge_result, attribute_result, cluster_summary)

    judge_result.gate_decisions = trace.gate_decisions
    judge_result.transition_decisions = trace.transition_decisions
    if attribute_result:
        attribute_result.gate_decisions = trace.gate_decisions
        attribute_result.transition_decisions = trace.transition_decisions

    view = frontend_view(project_id, trace, judge_result, attribute_result, cluster_summary, check_report)
    return {
        "trace": to_dict(trace),
        "judge": to_dict(judge_result),
        "attribute": to_dict(attribute_result) if attribute_result else None,
        "cluster": to_dict(cluster_summary),
        "check": to_dict(check_report),
        "frontend_view": to_dict(view),
    }
