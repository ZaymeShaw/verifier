from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from .analysis import analyze_project
from .check import check_chain
from .cluster import cluster_attributes
from .frontend_view import build_frontend_view, project_frontend_extensions
from .table_view import build_case_pool_table, build_case_pool_table_from_runs, build_trace_table_row, build_trace_table_row_from_run, display_input_for_project
from .interaction_protocol import normalize_case_interaction, resolve_ready, ready_from_spec
from .judge import generate_reference
from .live import interaction_contract, trace_from_live_result
from .mock_agent import MockAgent, build_spec_from_project, load_live_schema
from .live_stub import LiveStubGenerationError, LiveStubSchemaError, generate_live_output_with_check
from .project_loader import load_adapter, load_project, load_project_role_instance, list_projects
from .schema import AttributeResult, BatchRunResult, CheckReport, ClusterSummary, FallbackDecision, FrontendViewModel, JudgeResult, LiveExecutionResult, MockSpec, ProjectAnalysis, RunTrace, SingleTurnCase, TraceExecutionContext, normalize_attribute_result, normalize_check_report, normalize_cluster_summary, normalize_frontend_view, normalize_judge_result, normalize_mock_case, normalize_mock_dataset, normalize_mock_spec, normalize_run_trace, to_dict, trace_extracted_output, trace_input, trace_normalized_request, trace_output_source

logger = logging.getLogger(__name__)
from .state_machine import TraceStateMachineRunner, flatten_gate_decisions, flatten_transition_decisions

IMPL_ROOT = Path(__file__).resolve().parents[1]


def _fallback_decision(
    fallback_id: str,
    source_stage: str,
    fallback_type: str,
    status: str,
    reason: str,
    missing_evidence: Optional[list[str]] = None,
    recoverable: bool = False,
    needs_human_review: bool = False,
    quality_flags: Optional[list[str]] = None,
    evidence_refs: Optional[list[Dict[str, Any]]] = None,
    failed_gate_ids: Optional[list[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> FallbackDecision:
    return FallbackDecision(
        fallback_id=fallback_id,
        source_stage=source_stage,
        fallback_type=fallback_type,
        status=status,
        reason=reason,
        missing_evidence=list(missing_evidence or []),
        recoverable=recoverable,
        needs_human_review=needs_human_review,
        quality_flags=list(quality_flags or []),
        evidence_refs=list(evidence_refs or []),
        failed_gate_ids=list(failed_gate_ids or []),
        metadata=dict(metadata or {}),
    )


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


def _case_from_input(project_id: str, case: SingleTurnCase) -> SingleTurnCase:
    return SingleTurnCase(
        id=str(case.id or ""),
        input=dict(case.input or {}),
        output=case.output if isinstance(case.output, dict) else None,
        scenario=str(case.scenario or ""),
        expected_intent=str(case.expected_intent or ""),
        reference=case.reference if isinstance(case.reference, dict) else None,
        source=str(case.source or project_id),
        status=str(case.status or "pending"),
        metadata=case.metadata if isinstance(case.metadata, dict) else {},
    )


def live_run(project_id: str, case: SingleTurnCase | Dict[str, Any]) -> RunTrace:
    input_data = case.input if isinstance(case, SingleTurnCase) else case
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    normalized_case = _case_from_input(project_id, normalize_mock_case(input_data) or SingleTurnCase(id="", input=dict(input_data or {})))
    contract = interaction_contract(normalized_case)
    from impl.core.live_protocol import ProjectLive
    live = adapter.live()
    if not isinstance(live, ProjectLive):
        raise TypeError(f"{project_id} adapter.live() must return ProjectLive")
    result = live.deliver(normalized_case, contract)
    trace = trace_from_live_result(result)
    trace.execution_mode = "provided" if result.output_source == "provided_output" else "live"
    trace.ready = ready_from_spec(spec)
    return trace


def _normalize_judge_schema_payload(judge_result: JudgeResult) -> JudgeResult:
    return normalize_judge_result(judge_result) or judge_result


def _enforce_judge_live_schema(project_id: str, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    result = _normalize_judge_schema_payload(judge_result)
    live_schema = load_live_schema(project_id)
    checker = getattr(live_schema, "check", None) if live_schema is not None else None
    if checker is None:
        return result
    if result.actual is None:
        result.actual = trace_extracted_output(trace)
    if result.actual is not None and not checker.output(result.actual):
        result.overall_fulfillment = {**(result.overall_fulfillment or {}), "status": "not_evaluable"}
        return result
    if result.expected is None:
        result.overall_fulfillment = {**(result.overall_fulfillment or {}), "status": "not_evaluable"}
        return result
    if not checker.reference(result.expected):
        result.overall_fulfillment = {**(result.overall_fulfillment or {}), "status": "not_evaluable"}
        return result
    return result


def _normalize_attribute_schema_payload(attribute_result: AttributeResult) -> AttributeResult:
    return normalize_attribute_result(attribute_result) or attribute_result


def judge(project_id: str, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    if not getattr(trace, "ready", None):
        trace.ready = ready_from_spec(spec)
    from impl.core.judge_protocol import ProjectJudge
    # 显式启用项目级 draft 时加载其协议实现，和 production 使用同一模板方法入口。
    if (spec.judge_draft or {}).get("enabled") is True:
        judge_inst = load_project_role_instance(spec, "judge", adapter)
        if not isinstance(judge_inst, ProjectJudge):
            raise TypeError("enabled judge draft must provide a ProjectJudge implementation")
        result = judge_inst.judge_trace(trace, expected_intent=expected_intent)
        return _enforce_judge_live_schema(project_id, trace, normalize_judge_result(result) or result)
    judge_inst = adapter.judge()
    if not isinstance(judge_inst, ProjectJudge):
        raise TypeError(f"{project_id} adapter.judge() must return ProjectJudge")
    result = judge_inst.judge_trace(trace, expected_intent=expected_intent)
    return _enforce_judge_live_schema(project_id, trace, normalize_judge_result(result) or result)


def attribute(project_id: str, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    from impl.core.attribute_protocol import ProjectAttribute
    # 显式启用项目级 draft 时加载其协议实现，和 production 使用同一模板方法入口。
    if (spec.attribute_draft or {}).get("enabled") is True:
        attr_inst = load_project_role_instance(spec, "attribute", adapter)
        if not isinstance(attr_inst, ProjectAttribute):
            raise TypeError("enabled attribute draft must provide a ProjectAttribute implementation")
        result = attr_inst.attribute_failure(trace, judge_result)
        return _normalize_attribute_schema_payload(result)
    attr_inst = adapter.attribute()
    if not isinstance(attr_inst, ProjectAttribute):
        raise TypeError(f"{project_id} adapter.attribute() must return ProjectAttribute")
    result = attr_inst.attribute_failure(trace, judge_result)
    return _normalize_attribute_schema_payload(result)


def _satisfied_fulfillment_status(judge_result: JudgeResult) -> Optional[str]:
    overall = getattr(judge_result, "overall_fulfillment", {}) or {}
    if isinstance(overall, dict):
        status = overall.get("status")
        if status == "fulfilled":
            return status
    return None


def _resolve_attribute_fallback(
    context: TraceExecutionContext,
    judge_result: JudgeResult,
    project_id: str,
    trace: RunTrace,
) -> AttributeResult:
    if context.attribute_result is not None:
        return context.attribute_result
    if _satisfied_fulfillment_status(judge_result):
        context.attribute_result = incomplete_state_attribute_result(trace, judge_result)
        return context.attribute_result
    context.attribute_result = attribute(project_id, trace, judge_result)
    return context.attribute_result


def incomplete_state_attribute_result(trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    reason = trace.stop_reason or "state machine stopped before producing failure attribution"
    fallback = _fallback_decision(
        fallback_id=f"attribute-incomplete-{trace.trace_id}",
        source_stage="attribute",
        fallback_type="state_machine_incomplete",
        status="needs_human_review",
        reason=reason,
        missing_evidence=["completed_attribution_probes"],
        recoverable=True,
        needs_human_review=True,
        quality_flags=["attribute_incomplete"],
        evidence_refs=list(trace.evidence_refs or []),
        metadata={"trace_id": trace.trace_id},
    )
    return AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or "") if isinstance(trace.input, dict) else "",
        root_cause_hypothesis="状态机未完成归因质量门，当前只能保留待复核失败归因。",
        evidence=[reason],
        evidence_strength="none",
        summary={
            "attribution_count": 0,
            "probe_count": 0,
            "summary_text": reason,
            "is_complete": False,
            "is_formal_attribution": False,
        },
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
        extensions = project_frontend_extensions(spec, trace)
    return build_frontend_view(spec, trace, judge_result, attribute_result, cluster_summary, check_report, extensions)


def mock_spec(project_id: str) -> MockSpec:
    spec = load_project(project_id)
    analysis_result = analyze_project(project_id)
    mock = normalize_mock_spec({
        "input_modes": ["single_turn", "interactive_intent"],
        "case_sources": analysis_result.mock_handoff.get("case_sources", []),
        "intent_generation_guidance": json.dumps(analysis_result.mock_handoff.get("mock_guidance", {}), ensure_ascii=False),
        "expected_intent_format": json.dumps(analysis_result.mock_handoff.get("expected_intent_format", {}), ensure_ascii=False),
    })
    return mock if mock is not None else MockSpec()


def _generate_reference_for_case(spec, case, project_id):
    ref = generate_reference(spec, case.get("input", case), project_id=project_id)
    if isinstance(ref, dict):
        case["reference"] = ref
    return case


def _run_payload(trace, judge_result, attribute_result, case_id="", execution_mode="", output_source="", error=""):
    run = {
        "trace": trace,
        "judge": judge_result,
        "attribute": attribute_result,
        "case_id": case_id or trace.case_id,
        "execution_mode": execution_mode or trace.execution_mode,
        "output_source": output_source or trace.output_source,
    }
    if error:
        run["error"] = error
    return run


def _run_trace(run: Dict[str, Any]) -> RunTrace:
    trace = normalize_run_trace(run.get("trace"))
    if trace is not None:
        return trace
    return RunTrace(trace_id=str(run.get("trace_id") or ""), project_id=str(run.get("project_id") or ""), input={}, normalized_request={})


def _run_judge(run: Dict[str, Any]) -> Optional[JudgeResult]:
    return normalize_judge_result(run.get("judge"))


def _run_attribute(run: Dict[str, Any]) -> Optional[AttributeResult]:
    return normalize_attribute_result(run.get("attribute"))


def _run_frontend_view(run: Dict[str, Any]) -> Optional[FrontendViewModel]:
    return normalize_frontend_view(run.get("frontend_view"))


def _run_check(run: Dict[str, Any]) -> Optional[CheckReport]:
    return normalize_check_report(run.get("check"))


def _run_fallbacks(run: Dict[str, Any]) -> list[FallbackDecision]:
    return list(run.get("fallbacks") or [])


def _unsupported_interactive_run(project_id: str, case_id: str, source_case: Dict[str, Any]) -> Dict[str, Any]:
    fallback = _fallback_decision(
        fallback_id=f"interactive-unsupported-{case_id}",
        source_stage="interactive",
        fallback_type="unsupported",
        status="needs_human_review",
        reason="interactive_intent is not supported by this project adapter",
        missing_evidence=["live.run_interactive"],
        recoverable=True,
        needs_human_review=True,
        quality_flags=["unsupported_interactive_intent"],
        metadata={"case_id": case_id},
    )
    trace = RunTrace(
        trace_id=f"interactive-unsupported-{case_id}",
        project_id=project_id,
        case_id=case_id,
        input=source_case.get("input", source_case) if isinstance(source_case, dict) else {},
        normalized_request={},
        live_result=LiveExecutionResult(
            project_id=project_id,
            case_id=case_id,
            call_status="failed",
            call_error="interactive_intent is not supported by this project adapter",
            output_source="unsupported_interactive_intent",
            interaction_mode="interactive_intent",
            fallbacks=[fallback],
        ),
        status="error",
        error="interactive_intent is not supported by this project adapter",
        runtime_logs=["interactive adapter hook missing"],
        execution_mode="interactive_intent",
        output_source="unsupported_interactive_intent",
        interaction_mode="interactive_intent",
        execution_trace=[{"stage": "interactive.dispatch", "status": "failed", "evidence": "adapter does not implement run_interactive"}],
        fallbacks=[fallback],
    )
    judge_result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        overall_fulfillment={"status": "not_evaluable"},
        reasoning_summary="该项目 adapter 不支持 interactive_intent，已将该 case 限界为 not_evaluable，不中断批次。",
        evidence=["live.run_interactive missing"],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        root_cause_hypothesis="当前项目未声明或实现 interactive_intent adapter hook。",
        evidence=["live.run_interactive missing"],
        evidence_strength="weak",
    )
    run = _run_payload(trace, judge_result, attribute_result, case_id=case_id, execution_mode="interactive_intent", output_source="unsupported_interactive_intent", error=trace.error)
    return run


def _batch_case(index: int, case: Dict[str, Any], project_id: str, expected_intent: Optional[str]) -> Dict[str, Any]:
    normalized = normalize_case_interaction(project_id, case, index) if isinstance(case, dict) else None
    if normalized and normalized.mode == "interactive_intent":
        try:
            live = load_adapter(load_project(project_id)).live()
            run = live.run_interactive(normalized)
            trace = _run_trace(run)
            if trace:
                trace.case_id = trace.case_id or normalized.case_id
                trace.execution_mode = trace.execution_mode or "interactive_intent"
                trace.output_source = trace.output_source or "interactive_adapter"
                run["trace"] = trace
            run["case_id"] = trace.case_id if trace else normalized.case_id
            run["execution_mode"] = trace.execution_mode if trace else "interactive_intent"
            run["output_source"] = trace_output_source(trace) if trace else run.get("output_source") or "interactive_adapter"
            if not run.get("table_row") and run.get("trace") and run.get("judge"):
                run["table_row"] = build_trace_table_row(_run_trace(run), _run_judge(run), _run_attribute(run), _run_frontend_view(run), _run_check(run), case_context=run)
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
            trace = _run_trace(run)
            if trace:
                trace.case_id = trace.case_id or case_id
                run["trace"] = trace
            run["case_id"] = trace.case_id if trace else case_id
            run["execution_mode"] = trace.execution_mode if trace else run.get("execution_mode") or "live"
            run["output_source"] = trace_output_source(trace) if trace else run.get("output_source") or "live"
            if not run.get("table_row") and run.get("trace") and run.get("judge"):
                run["table_row"] = build_trace_table_row(_run_trace(run), _run_judge(run), _run_attribute(run), _run_frontend_view(run), _run_check(run), case_context=run)
            return run
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                continue
    error_text = str(last_exc)
    fallback = _fallback_decision(
        fallback_id=f"batch-case-failed-{case_id}",
        source_stage="batch",
        fallback_type="batch_case_exception",
        status="error",
        reason=error_text,
        missing_evidence=["completed_run_chain"],
        recoverable=True,
        needs_human_review=True,
        quality_flags=["batch_case_failed"],
        metadata={"case_id": case_id},
    )
    trace = RunTrace(
        trace_id=f"batch-error-{case_id}",
        project_id=project_id,
        case_id=case_id,
        input={**case_input, "case_id": case_id},
        normalized_request={},
        status="error",
        error=error_text,
        runtime_logs=[f"batch case failed after {MAX_RETRIES + 1} attempts"],
        execution_mode="error",
        output_source="batch_case_exception",
        fallbacks=[fallback],
    )
    judge_result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        overall_fulfillment={"status": "not_evaluable"},
        reasoning_summary=error_text,
        evidence=["batch_case_failed"],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        root_cause_hypothesis=error_text,
        evidence=[error_text],
        evidence_strength="none",
    )
    run = _run_payload(trace, judge_result, attribute_result, case_id=case_id, execution_mode="error", output_source="batch_case_exception", error=error_text)
    return run


def _batch_error_run(index: int, case: Dict[str, Any], project_id: str, exc: Exception) -> Dict[str, Any]:
    case_id = str(case.get("id")) if isinstance(case, dict) and case.get("id") else f"case-{index + 1}"
    case_input = case.get("input", case) if isinstance(case, dict) else {"value": case}
    if not isinstance(case_input, dict):
        case_input = {"value": case_input}
    fallback = _fallback_decision(
        fallback_id=f"batch-future-error-{case_id}",
        source_stage="batch",
        fallback_type="batch_future_exception",
        status="error",
        reason=str(exc),
        missing_evidence=["completed_future_result"],
        recoverable=True,
        needs_human_review=True,
        quality_flags=["batch_case_failed"],
        metadata={"case_id": case_id},
    )
    trace = RunTrace(
        trace_id=f"batch-error-{case_id}",
        project_id=project_id,
        case_id=case_id,
        input={**case_input, "case_id": case_id},
        normalized_request={},
        status="error",
        error=str(exc),
        runtime_logs=["batch case failed outside run_chain"],
        execution_mode="error",
        output_source="batch_future_exception",
        fallbacks=[fallback],
    )
    judge_result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        overall_fulfillment={"status": "not_evaluable"},
        reasoning_summary=str(exc),
        evidence=["batch_case_failed"],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        root_cause_hypothesis=str(exc),
        evidence=[str(exc)],
        evidence_strength="none",
    )
    run = _run_payload(trace, judge_result, attribute_result, case_id=case_id, execution_mode="error", output_source="batch_future_exception", error=str(exc))
    return run


def batch_run(
    project_id: str,
    cases: Iterable[Dict[str, Any]],
    expected_intent: Optional[str] = None,
    concurrency: int = 4,
    on_case_done: Optional[Callable[[int, Dict[str, Any]], None]] = None,
) -> BatchRunResult:
    case_list = list(cases)
    if not case_list:
        cluster_summary = cluster(project_id, [])
        check_report = check(project_id, None, None, None, cluster_summary)
        table = build_case_pool_table_from_runs(project_id, [])
        return BatchRunResult(project_id=project_id, total=0, runs=[], cluster=cluster_summary, check=check_report, table=table)
    max_workers = max(1, min(int(concurrency or 1), len(case_list)))
    runs_by_index: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_batch_case, index, case, project_id, expected_intent): index for index, case in enumerate(case_list)}
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
    attributes = [item for item in (_run_attribute(run) for run in runs if isinstance(run, dict) and run.get("attribute")) if item is not None]
    cluster_summary = cluster(project_id, attributes)
    representative = None
    for priority_status in ("not_fulfilled", "not_evaluable"):
        for run in (runs or []):
            if not isinstance(run, dict):
                continue
            judge_candidate = run.get("judge")
            if judge_candidate is not None:
                js = getattr(judge_candidate, "summary", None) or run.get("judge_summary") or {}
                js = js if isinstance(js, dict) else {}
            else:
                js = run.get("judge_summary") or {}
            if js.get("fulfillment_status") == priority_status:
                representative = run
                break
        if representative:
            break
    if not representative and runs:
        representative = next((r for r in runs if isinstance(r, dict) and not r.get("error")), runs[-1])
    trace = _run_trace(representative) if representative and representative.get("trace") else None
    judge_result = _run_judge(representative) if representative and representative.get("judge") else None
    attribute_result = _run_attribute(runs[-1]) if runs and runs[-1].get("attribute") else None
    check_report = check(project_id, trace, judge_result, attribute_result, cluster_summary)
    failed_run_checks = [item for item in (_run_check(run) for run in runs if isinstance(run, dict) and run.get("check")) if item is not None and item.passed is False]
    table = build_case_pool_table_from_runs(project_id, runs)
    return BatchRunResult(project_id=project_id, total=len(case_list), runs=runs, cluster=cluster_summary, check=check_report, table=table)


def _run_chain_replay(project_id: str, trace: RunTrace, context: TraceExecutionContext):
    from .state_machine import TraceStateMachineRunner
    runner = TraceStateMachineRunner()
    return runner.run(context)


def run_chain(project_id: str, case_input: Dict[str, Any], expected_intent: Optional[str] = None) -> Dict[str, Any]:
    trace = live_run(project_id, SingleTurnCase(id="", input=dict(case_input or {})))
    judge_result = judge(project_id, trace, expected_intent=expected_intent)
    attribute_result = attribute(project_id, trace, judge_result)
    cluster_summary = cluster(project_id, [attribute_result])
    check_report = check(project_id, trace, judge_result, attribute_result, cluster_summary)
    frontend = frontend_view(project_id, trace, judge_result, attribute_result, cluster_summary, check_report)
    run = _run_payload(trace, judge_result, attribute_result, case_id=trace.case_id, execution_mode=trace.execution_mode, output_source=trace.output_source)
    run["cluster"] = cluster_summary
    run["check"] = check_report
    run["frontend_view"] = frontend
    run["table_row"] = build_trace_table_row(trace, judge_result, attribute_result, frontend, check_report, case_context=run)
    return run


def _fixture_mock_cases(project_id: str) -> list[Dict[str, Any]]:
    """Read persisted mock cases for API/check flows.

    spec/live.md: mock cases are REQUEST_SCHEMA-shaped inputs.  Persisted fixtures are
    the stable source for API smoke checks; generation remains an explicit
    mock_build_* action, not an implicit fallback on every /api/mock_cases call.
    """
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"mock cases file must contain a list: {path}")
    return [to_dict(case) for case in (normalize_mock_case(item) for item in data) if case is not None]


def mock_build_intent(
    project_id: str,
    scenario: str = "",
    intent_labels: Optional[list[str]] = None,
    template: Optional[Dict[str, Any]] = None,
    required_input_fields: Optional[list[str]] = None,
) -> Dict[str, Any]:
    spec = load_project(project_id)
    build_spec = build_spec_from_project(spec, scenario=scenario)
    if intent_labels:
        build_spec.intent_labels = list(intent_labels or [])
    if required_input_fields:
        build_spec.required_input_fields = list(required_input_fields or [])
    if template:
        build_spec.template = dict(template or {})
    return to_dict(MockAgent(spec).build(build_spec))


def mock_build_interaction(
    project_id: str,
    intent_result: Dict[str, Any],
    live_context: Dict[str, Any],
    previous_turns: list[Dict[str, Any]],
) -> Dict[str, Any]:
    spec = load_project(project_id)
    next_turn = MockAgent(spec).next_turn(intent_result or {}, previous_turns or [], live_context or {})
    case_id = str((intent_result or {}).get("case_id") or (intent_result or {}).get("id") or "")
    input_data = dict((intent_result or {}).get("input") or {})
    turns = list(input_data.get("turns") or previous_turns or [])
    if next_turn.get("query"):
        turns.append({"role": "user", "content": next_turn.get("query")})
    input_data["turns"] = turns
    input_data["query"] = next_turn.get("query") or input_data.get("query") or ""
    return {
        "case_id": case_id,
        "input": input_data,
        "scenario": str((intent_result or {}).get("scenario") or ""),
        "metadata": {"source": "mock_agent_next_turn", "project_id": project_id, "next_turn": next_turn},
    }


def _attach_case_table_rows(project_id: str, cases: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    for case in cases:
        if isinstance(case, dict):
            case["table_row"] = {"input": display_input_for_project(project_id, case.get("input"))}
    return cases


def mock_cases(project_id: str, count: int = 3, cases_per_scenario: int = 0) -> list[Dict[str, Any]]:
    """生成 mock cases。优先用固化的 fixture；否则用 mock_agent LLM 动态生成。

    cases_per_scenario > 0 时按场景遍历生成（每场景 N 条），覆盖 count。
    """
    fixtures = _fixture_mock_cases(project_id)
    if fixtures:
        return _attach_case_table_rows(project_id, fixtures[:count])
    spec = load_project(project_id)
    live_schema = load_live_schema(project_id)
    scenarios = list(getattr(live_schema, "SCENARIO_ENUM", []) or []) or [""]
    cases: list[Dict[str, Any]] = []
    if cases_per_scenario and cases_per_scenario > 0:
        for scenario in scenarios:
            for _ in range(cases_per_scenario):
                built = mock_build_intent(project_id, scenario=scenario)
                if built and isinstance(built.get("input"), dict):
                    cases.append(built)
    else:
        for scenario in scenarios[:count]:
            built = mock_build_intent(project_id, scenario=scenario)
            if built and isinstance(built.get("input"), dict):
                cases.append(built)
    _ = spec  # 保留 spec 引用以备扩展
    return _attach_case_table_rows(project_id, cases)


def mock_datasets(
    project_id: str,
    count: int = 3,
    cases_per_scenario: int = 0,
) -> list[Dict[str, Any]]:
    cases = mock_cases(project_id, count=count, cases_per_scenario=cases_per_scenario)
    if not cases:
        return []
    by_scenario: dict[str, list[Dict[str, Any]]] = {}
    for case in cases:
        scenario = str(case.get("scenario") or "default")
        by_scenario.setdefault(scenario, []).append(case)
    return [
        {
            "dataset_id": f"{project_id}_{scenario}",
            "name": f"{scenario} mock 数据集",
            "dimension_type": scenario,
            "description": f"mock_agent 生成或固化的 {scenario} 场景用例",
            "cases": scenario_cases,
            "case_count": len(scenario_cases),
        }
        for scenario, scenario_cases in by_scenario.items()
    ]


def save_mock_cases(
    project_id: str,
    cases: list[Dict[str, Any]],
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """把 cases 写入 JSON 文件。格式与 _fixture_mock_cases 读取的格式一致。

    output_path:
        None 或 "default" → impl/data/<project>/mock_cases.json
        其他路径 → 按指定路径写
    返回 {"path": ..., "case_count": ...}。
    """
    target = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    if output_path and output_path != "default":
        target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": True, "save_path": str(target), "save_count": len(cases)}


def check_mock_data(project_id: str, data_path: Optional[str] = None, cases: Optional[list[Dict[str, Any]]] = None) -> Dict[str, Any]:
    items = []
    source_cases = cases if cases is not None else mock_cases(project_id)
    live_schema = load_live_schema(project_id)
    checker = getattr(live_schema, "check", None) if live_schema else None
    for index, case in enumerate(source_cases or []):
        errors = []
        if checker:
            try:
                errors = checker.case_errors(case)
            except Exception as exc:
                errors = [str(exc)]
        items.append({"index": index, "case_id": case.get("id") or case.get("case_id") or "", "ok": not errors, "details": errors})
    return {"project_id": project_id, "data_path": data_path or "", "ok": all(item["ok"] for item in items), "items": items}
