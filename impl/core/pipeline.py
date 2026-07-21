from __future__ import annotations

import json
import logging
import threading
import time
from copy import deepcopy
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
from .mock_agent import MockAgent, build_spec_from_project, load_live_schema
from .live_stub import LiveStubGenerationError, LiveStubSchemaError, generate_live_output_with_check
from .project_loader import load_adapter, load_project, load_project_role_instance, list_projects
from .trace import trace_from_live
from .schema import AttributeResult, BatchRunResult, CheckReport, ClusterSummary, FallbackDecision, FrontendViewModel, JudgeResult, MockSpec, ProjectAnalysis, RunTrace, SingleTurnCase, TraceExecutionContext, normalize_attribute_result, normalize_check_report, normalize_cluster_summary, normalize_frontend_view, normalize_judge_result, normalize_mock_case, normalize_mock_dataset, normalize_mock_spec, normalize_run_trace, to_dict, trace_extracted_output, trace_input, trace_normalized_request, trace_output_source
from .summary import summary_from_fulfillment

logger = logging.getLogger(__name__)
_manual_attribute_cache: dict[tuple[str, str], AttributeResult] = {}
_manual_attribute_lock = threading.Lock()
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
        user_intent=str(case.user_intent or ""),
        reference=case.reference if isinstance(case.reference, dict) else None,
        source=str(case.source or project_id),
        status=str(case.status or "pending"),
        metadata=case.metadata if isinstance(case.metadata, dict) else {},
    )


def live_run(project_id: str, case: SingleTurnCase | Dict[str, Any]) -> RunTrace:
    """主流程入口：case → trace_from_live → RunTrace

    流程（spec/adapter/trace.md 第 8 节）：
    1. 加载 spec / adapter / live
    2. 调 trace_from_live(live, case) 完成 trace 层职责（意图计算、execute_live、RunTrace 组装）

    trace 和 live 串联方向单向依赖：trace 依赖 live，live 不依赖 trace。
    """
    spec = load_project(project_id)
    if spec.local_deployment_enabled:
        from .local_service import ensure_project_service

        ensure_project_service(spec)
    adapter = load_adapter(spec)
    from impl.core.live_protocol import ProjectLive
    live = adapter.live()
    if not isinstance(live, ProjectLive):
        raise TypeError(f"{project_id} adapter.live() must return ProjectLive")
    return trace_from_live(live, case)


def _normalize_judge_schema_payload(judge_result: JudgeResult) -> JudgeResult:
    return normalize_judge_result(judge_result) or judge_result


def _mark_judge_not_evaluable(result: JudgeResult) -> JudgeResult:
    result.overall_fulfillment = {
        **(result.overall_fulfillment or {}),
        "status": "not_evaluable",
    }
    # live-schema validation runs after the project Judge has finalized its
    # deterministic summary. Keep the public status and frontend summary atomic.
    result.summary = summary_from_fulfillment(to_dict(result))
    return result


def _enforce_judge_live_schema(project_id: str, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    result = _normalize_judge_schema_payload(judge_result)
    live_schema = load_live_schema(project_id)
    checker = getattr(live_schema, "check", None) if live_schema is not None else None
    if checker is None:
        return result
    if result.actual is None:
        result.actual = trace_extracted_output(trace)
    if result.actual is not None and not checker.output(result.actual):
        return _mark_judge_not_evaluable(result)
    if result.expected is None:
        return _mark_judge_not_evaluable(result)
    if not checker.reference(result.expected):
        return _mark_judge_not_evaluable(result)
    return result


def _normalize_attribute_schema_payload(attribute_result: AttributeResult) -> AttributeResult:
    return normalize_attribute_result(attribute_result) or attribute_result


def judge(project_id: str, trace: RunTrace, user_intent: Optional[str] = None) -> JudgeResult:
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
        result = judge_inst.judge_trace(trace, user_intent=user_intent)
        return _enforce_judge_live_schema(project_id, trace, normalize_judge_result(result) or result)
    judge_inst = adapter.judge()
    if not isinstance(judge_inst, ProjectJudge):
        raise TypeError(f"{project_id} adapter.judge() must return ProjectJudge")
    result = judge_inst.judge_trace(trace, user_intent=user_intent)
    return _enforce_judge_live_schema(project_id, trace, normalize_judge_result(result) or result)


def attribute(
    project_id: str,
    trace: RunTrace,
    judge_result: JudgeResult,
    *,
    manual_override: bool = True,
) -> AttributeResult:
    spec = load_project(project_id)
    if not spec.attribution_enabled and not manual_override:
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.case_id or ""),
            unresolved_reason="attribution disabled by project configuration",
            summary={
                "attribution_status": "skipped",
                "execution_source": "project_default",
                "manual_override": False,
                "is_formal_attribution": False,
            },
        )
    cache_key = (project_id, trace.trace_id)
    if manual_override:
        with _manual_attribute_lock:
            cached = _manual_attribute_cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)
    adapter = load_adapter(spec)
    from impl.core.attribute_protocol import ProjectAttribute
    # 显式启用项目级 draft 时加载其协议实现，和 production 使用同一模板方法入口。
    if (spec.attribute_draft or {}).get("enabled") is True:
        attr_inst = load_project_role_instance(spec, "attribute", adapter)
        if not isinstance(attr_inst, ProjectAttribute):
            raise TypeError("enabled attribute draft must provide a ProjectAttribute implementation")
        if not _satisfied_fulfillment_status(judge_result):
            from impl.core.attribute_environment import build_attribute_environment
            attr_inst.configure_execution_environment(build_attribute_environment(spec, trace))
        result = attr_inst.attribute_failure(trace, judge_result)
        normalized = _normalize_attribute_schema_payload(result)
        return _record_manual_attribute(cache_key, normalized) if manual_override else normalized
    attr_inst = adapter.attribute()
    if not isinstance(attr_inst, ProjectAttribute):
        raise TypeError(f"{project_id} adapter.attribute() must return ProjectAttribute")
    if not _satisfied_fulfillment_status(judge_result):
        from impl.core.attribute_environment import build_attribute_environment
        attr_inst.configure_execution_environment(build_attribute_environment(spec, trace))
    result = attr_inst.attribute_failure(trace, judge_result)
    normalized = _normalize_attribute_schema_payload(result)
    return _record_manual_attribute(cache_key, normalized) if manual_override else normalized


def _record_manual_attribute(key: tuple[str, str], result: AttributeResult) -> AttributeResult:
    result.summary = {
        **dict(result.summary or {}),
        "execution_source": "manual_override",
        "manual_override": True,
    }
    with _manual_attribute_lock:
        _manual_attribute_cache[key] = deepcopy(result)
    return result


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
    context.attribute_result = attribute(project_id, trace, judge_result, manual_override=False)
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
        case_id=str(trace.case_id or ""),
        unresolved_reason="状态机未完成归因质量门，当前只能保留待复核失败归因。 " + reason,
        summary={
            "summary_text": reason,
            "finding_count": 0,
            "covered_expectation_ids": [],
            "unresolved_expectation_ids": [],
            "attribution_status": "unresolved",
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
    handoff = analysis_result.analysis_handoff if isinstance(analysis_result.analysis_handoff, dict) else {}
    mock = normalize_mock_spec({
        "input_modes": ["single_turn", "interactive_intent"],
        "case_sources": handoff.get("case_sources", []),
        "intent_generation_guidance": analysis_result.mock_guidance,
        "user_intent_format": json.dumps(handoff.get("user_intent_format", {}), ensure_ascii=False),
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
        missing_evidence=["MultiTurnInteractiveLive"],
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
        status="error",
        error="interactive_intent is not supported by this project adapter",
        runtime_logs=["interactive adapter hook missing"],
        execution_mode="interactive_intent",
        output_source="unsupported_interactive_intent",
        interaction_mode="interactive_intent",
        execution_trace=[{"stage": "interactive.dispatch", "status": "failed", "evidence": "adapter does not inherit MultiTurnInteractiveLive"}],
        fallbacks=[fallback],
    )
    judge_result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        overall_fulfillment={"status": "not_evaluable"},
        reasoning_summary="该项目 adapter 不支持 interactive_intent，已将该 case 限界为 not_evaluable，不中断批次。",
        evidence=["MultiTurnInteractiveLive missing"],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        unresolved_reason="当前项目未声明或实现 interactive_intent adapter hook。",
    )
    run = _run_payload(trace, judge_result, attribute_result, case_id=case_id, execution_mode="interactive_intent", output_source="unsupported_interactive_intent", error=trace.error)
    return run


def _run_interactive_case(project_id: str, normalized: Any) -> Dict[str, Any]:
    """多轮 case 执行入口：调 trace_from_live 完成多轮执行和 RunTrace 组装。

    职责仅限：加载 spec/adapter/live、不支持场景的兜底、调 trace_from_live、跑下游链路。
    意图计算由 trace_from_live 内部调 live._resolve_intent；trace 字段由 trace 层从 TraceContext 推导。
    """
    from impl.core.live_protocol import MultiTurnInteractiveLive

    spec = load_project(project_id)
    adapter = load_adapter(spec)
    live = adapter.live()
    if not isinstance(live, MultiTurnInteractiveLive):
        return _unsupported_interactive_run(project_id, normalized.case_id, normalized.source_case)

    # 调 trace 层入口（内部完成意图计算、execute_live、RunTrace 组装）
    trace = trace_from_live(live, normalized)

    # 继续单轮下游链路（judge/attribute/cluster/check/frontend_view）
    judge_result = judge(project_id, trace, user_intent=None)
    attribute_result = attribute(project_id, trace, judge_result, manual_override=False)
    cluster_summary = cluster(project_id, [attribute_result])
    check_report = check(project_id, trace, judge_result, attribute_result, cluster_summary)
    frontend = frontend_view(project_id, trace, judge_result, attribute_result, cluster_summary, check_report)

    run = _run_payload(
        trace,
        judge_result,
        attribute_result,
        case_id=trace.case_id,
        execution_mode=trace.execution_mode,
        output_source=trace.output_source,
    )
    run["cluster"] = cluster_summary
    run["check"] = check_report
    run["frontend_view"] = frontend
    run["table_row"] = build_trace_table_row(trace, judge_result, attribute_result, frontend, check_report, case_context=run)
    return run


def _batch_case(index: int, case: Dict[str, Any], project_id: str, user_intent: Optional[str]) -> Dict[str, Any]:
    from impl.core.mock import mock_case_to_single_turn, parse_mock_case
    stored_case = parse_mock_case(case, project_id=project_id)
    runtime_case = to_dict(mock_case_to_single_turn(stored_case))
    normalized = normalize_case_interaction(project_id, runtime_case, index)
    if normalized and normalized.mode == "interactive_intent":
        # _run_interactive_case 内部已处理 isinstance 不支持的兜底；
        # 这里不要 catch 异常包装为 unsupported，否则会掩盖真实 bug。
        return _run_interactive_case(project_id, normalized)

    case_input = normalized.execution_input if normalized else (case.get("input", case) if isinstance(case, dict) else case)
    if not isinstance(case_input, dict):
        case_input = {"value": case_input}
    case_id = normalized.case_id if normalized else f"case-{index + 1}"
    case_expected = stored_case.intent.user_intent if stored_case.intent is not None else ""
    from .config import get_runtime_config

    max_attempts = get_runtime_config().execution.case_retry_attempts
    last_exc = None
    for attempt in range(max_attempts):
        try:
            # 传完整 case（含 scenario/user_intent/metadata），run_chain 内部用 normalize_mock_case 恢复
            run = run_chain(project_id, runtime_case, user_intent=case_expected or user_intent)
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
            if attempt + 1 < max_attempts:
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
        runtime_logs=[f"batch case failed after {max_attempts} attempts"],
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
        unresolved_reason=error_text,
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
        unresolved_reason=str(exc),
    )
    run = _run_payload(trace, judge_result, attribute_result, case_id=case_id, execution_mode="error", output_source="batch_future_exception", error=str(exc))
    return run


def batch_run(
    project_id: str,
    cases: Iterable[Dict[str, Any]],
    user_intent: Optional[str] = None,
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
        futures = {executor.submit(_batch_case, index, case, project_id, user_intent): index for index, case in enumerate(case_list)}
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


def run_chain(project_id: str, case_input: Dict[str, Any], user_intent: Optional[str] = None) -> Dict[str, Any]:
    # case_input 可能是完整 case dict（含 scenario/user_intent/metadata）或仅 input dict；
    # normalize_mock_case 能从两种形状恢复完整 SingleTurnCase
    trace = live_run(project_id, case_input)
    judge_result = judge(project_id, trace, user_intent=user_intent)
    attribute_result = attribute(project_id, trace, judge_result, manual_override=False)
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

    存储格式为 MockCase（三层：标识/intent/live_request）。
    normalize_mock_case 兼容新旧两种格式，自动转换到 SingleTurnCase 形状
    供下游 pipeline 消费。

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
    from impl.core.mock import parse_mock_case
    return [to_dict(parse_mock_case(item, project_id=project_id)) for item in data]


def mock_build_intent(
    project_id: str,
    scenario: str = "",
    intent_labels: Optional[list[str]] = None,
    template: Optional[Dict[str, Any]] = None,
    required_input_fields: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """生成一条 mock case，返回 MockCase 存储格式。

    MockCase 三层结构：标识 — intent — live_request。
    """
    spec = load_project(project_id)
    build_spec = build_spec_from_project(spec, scenario=scenario)
    if intent_labels:
        build_spec.intent_labels = list(intent_labels or [])
    if required_input_fields:
        build_spec.required_input_fields = list(required_input_fields or [])
    if template:
        build_spec.template = dict(template or {})
    from impl.core.mock import build_mock_case
    result = MockAgent(spec).build(build_spec)
    mc = build_mock_case(spec, {"_result": result, "scenario": scenario})
    # 直接返回 MockCase dataclass，让 to_public_dict 按 PUBLIC_SCHEMA_FIELDS['MockCase'] 序列化
    # output/reference 即使为 None 也保留（ready 协议控制存在性）
    return mc


def _attach_case_table_rows(project_id: str, cases: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    for case in cases:
        if isinstance(case, dict):
            request_data = case.get("live_request") or case.get("input") or {}
            case["table_row"] = {"input": display_input_for_project(project_id, request_data)}
    return cases


def _pick_fixtures_with_multiturn(fixtures: list[Dict[str, Any]], count: int) -> list[Dict[str, Any]]:
    """从 fixtures 里挑 count 条，保证若存在 interactive_intent fixture 则至少带 1 条。

    策略：先按文件顺序取前 count 条；若这批没有多轮 fixture，但 fixtures 里存在多轮 fixture，
    则用第一条多轮 fixture 替换本批最后一条（保持 count 不变，不改变单轮 fixture 的相对顺序）。
    """
    if count <= 0 or not fixtures:
        return list(fixtures[:max(0, count)])

    def _is_multiturn(case: Dict[str, Any]) -> bool:
        interaction = case.get("interaction") if isinstance(case, dict) else None
        if not isinstance(interaction, dict):
            return False
        return str(interaction.get("mode") or "") == "interactive_intent"

    picked = list(fixtures[:count])
    if any(_is_multiturn(c) for c in picked):
        return picked
    first_mt = next((c for c in fixtures if _is_multiturn(c)), None)
    if first_mt is None:
        return picked
    picked[-1] = first_mt
    return picked


def mock_cases(project_id: str, count: int = 3, cases_per_scenario: int = 0) -> list[Dict[str, Any]]:
    """生成 mock cases。优先用固化的 fixture；否则用 mock_agent LLM 动态生成。

    cases_per_scenario > 0 时按场景遍历生成（每场景 N 条），覆盖 count。

    fixture 切片策略：默认 count 条里若存在 interaction.mode=interactive_intent
    的多轮 fixture，至少带 1 条进入返回（否则多轮路径无法被下游 batch_run/验收覆盖）。
    """
    fixtures = _fixture_mock_cases(project_id)
    if fixtures:
        picked = _pick_fixtures_with_multiturn(fixtures, count)
        return picked
    spec = load_project(project_id)
    live_schema = load_live_schema(project_id)
    scenarios = list(getattr(live_schema, "SCENARIO_ENUM", []) or []) or [""]
    cases: list[Dict[str, Any]] = []
    if cases_per_scenario and cases_per_scenario > 0:
        for scenario in scenarios:
            for _ in range(cases_per_scenario):
                built = mock_build_intent(project_id, scenario=scenario)
                payload = to_dict(built) if built is not None else None
                if payload and isinstance(payload.get("live_request"), dict):
                    cases.append(payload)
    else:
        for scenario in scenarios[:count]:
            built = mock_build_intent(project_id, scenario=scenario)
            payload = to_dict(built) if built is not None else None
            if payload and isinstance(payload.get("live_request"), dict):
                cases.append(payload)
    _ = spec  # 保留 spec 引用以备扩展
    return cases


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
    skip_invalid: bool = False,
) -> Dict[str, Any]:
    """把 cases 写入 JSON 文件，使用 MockCase 存储格式。

    MockCase 三层结构：标识 — 意图层（intent）— API 请求层（live_request）。
    case.input 校验通过后，转成 MockCase 格式再写盘。

    output_path:
        None 或 "default" → impl/data/<project>/mock_cases.json
        其他路径 → 按指定路径写

    skip_invalid:
        False（默认）— 如果有 case.input 不符合 REQUEST_SCHEMA，抛 ValueError 阻断固化
        True — 跳过不符合 schema 的 case，只固化有效的

    返回 {"saved": ..., "save_path": ..., "save_count": ..., "invalid_count": ..., "invalid_cases": ...}。
    """
    # 校验：所有 case.input 必须符合 REQUEST_SCHEMA（基于 SingleTurnCase 形状校验）
    live_schema = load_live_schema(project_id)
    checker = getattr(live_schema, "check", None) if live_schema else None
    valid_cases = []
    invalid_cases = []

    if checker:
        for case in cases:
            case_input = case.get("input") if isinstance(case, dict) else None
            if not isinstance(case_input, dict):
                invalid_cases.append({"case_id": str(case.get("id") or ""), "error": "input 不是 dict"})
                continue
            if not checker.request(case_input):
                # 具体错误
                errors = checker.case_errors(case) if hasattr(checker, "case_errors") else ["input 不符合 REQUEST_SCHEMA"]
                invalid_cases.append({"case_id": str(case.get("id") or ""), "errors": errors})
                continue
            valid_cases.append(case)
    else:
        valid_cases = list(cases)

    if invalid_cases and not skip_invalid:
        raise ValueError(
            f"save_mock_cases: {len(invalid_cases)} 个 case 不符合 REQUEST_SCHEMA，拒绝固化。"
            f"invalid_cases={invalid_cases[:3]}... "
            f"设置 skip_invalid=True 可跳过无效 case。"
        )

    # 转 MockCase 存储格式：三层分离（标识 / intent / live_request）
    from impl.core.schema.normalize import normalize_mock_case
    from impl.core.mock import single_turn_to_mock_case
    mock_case_dicts = []
    for case in valid_cases:
        stc = normalize_mock_case(case)
        if stc is None:
            continue
        mc = single_turn_to_mock_case(stc, project_id)
        intent = mc.intent
        mock_case_dicts.append({
            "id": mc.id,
            "project_id": mc.project_id,
            "scenario": mc.scenario,
            "intent": None if intent is None else {
                "user_intent": intent.user_intent,
                "query": intent.query,
                "user_context": intent.user_context,
                "system_understanding": intent.system_understanding,
                "scenario": intent.scenario,
            },
            "live_request": mc.live_request,
            "output": mc.output,
            "reference": mc.reference,
        })

    target = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    if output_path and output_path != "default":
        target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(mock_case_dicts, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "saved": True,
        "save_path": str(target),
        "save_count": len(mock_case_dicts),
        "invalid_count": len(invalid_cases),
        "invalid_cases": invalid_cases if invalid_cases else None,
    }


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
