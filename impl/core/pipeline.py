from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from .analysis import analyze_project
from .adapter import ProjectAdapter
from .attribute import attribute_failure
from .check import check_chain
from .cluster import cluster_attributes
from .frontend_view import build_frontend_view
from .table_view import build_case_pool_table, build_case_pool_table_from_runs, build_trace_table_row, build_trace_table_row_from_run
from .interaction_protocol import normalize_case_interaction, resolve_ready, ready_from_spec
from .judge import judge_trace, generate_reference
from .mock_agent import load_live_schema
from .live_stub import generate_live_output_with_check
from .project_loader import load_adapter, load_project, list_projects
from .runtime_query_tools import extract_runtime_values
from .schema import AttributeResult, BatchRunResult, CheckReport, ClusterSummary, FallbackDecision, FrontendViewModel, JudgeResult, LiveExecutionResult, LiveMultiTurnResult, LiveMultiTurnState, LiveRequest, MockSpec, MultiTurnInteraction, MultiTurnPolicy, MultiTurnTraceSummary, MultiTurnTurnExpectation, ProjectAnalysis, RunTrace, SingleTurnCase, TraceExecutionContext, normalize_attribute_result, normalize_check_report, normalize_cluster_summary, normalize_frontend_view, normalize_judge_result, normalize_live_execution_result, normalize_live_multi_turn_result, normalize_mock_case, normalize_mock_dataset, normalize_mock_spec, normalize_multi_turn_trace_summary, normalize_run_trace, to_dict, trace_conversation_transcript, trace_execution_trace, trace_extracted_output, trace_input, trace_normalized_request, trace_output_source

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


def _build_live_request(adapter: ProjectAdapter, case: SingleTurnCase, project_id: str) -> LiveRequest:
    try:
        request = adapter.build_request(case)
    except (AttributeError, TypeError):
        request = adapter.build_request(case.input)
    if isinstance(request, LiveRequest):
        return request
    return LiveRequest(project_id=project_id, raw_input=dict(case.input or {}), case_id=case.id, normalized_request=request if isinstance(request, dict) else {})


def _call_live(adapter: ProjectAdapter, request: LiveRequest) -> LiveExecutionResult:
    try:
        candidate = adapter.call_or_prepare(request)
    except (AttributeError, TypeError):
        candidate = adapter.call_or_prepare(request.normalized_request)
    if isinstance(candidate, LiveExecutionResult):
        return candidate
    if isinstance(candidate, dict) and {"project_id", "raw_input", "normalized_request", "extracted_output"}.intersection(candidate):
        normalized = normalize_live_execution_result(candidate)
        if normalized is not None:
            return normalized
    raw_response = candidate
    extracted_output = adapter.extract_output(raw_response)
    # 挂载 live_schema 校验：extract_output 是否符合 EXTRACT_OUTPUT_SHAPE
    _check_extracted_output_with_live_schema(request.project_id, extracted_output)
    return LiveExecutionResult(
        project_id=request.project_id,
        case_id=request.case_id,
        session_id=request.session_id,
        raw_input=request.raw_input,
        normalized_request=request.normalized_request,
        raw_response=raw_response,
        extracted_output=extracted_output,
        output_source=request.execution_mode,
        execution_trace=adapter.build_execution_trace(request.raw_input, request.normalized_request, raw_response, extracted_output),
        project_fields=adapter.project_fields(raw_response, extracted_output),
        application_boundary=adapter.application_boundary(raw_response, extracted_output),
        interaction_mode="interactive_intent" if request.turns else "single_turn",
    )


def _trace_from_live_result(adapter: ProjectAdapter, result: LiveExecutionResult) -> RunTrace:
    try:
        trace = adapter.to_run_trace(result)
    except TypeError:
        from .adapter import ProjectAdapter

        trace = ProjectAdapter.to_run_trace(adapter, result)
    return normalize_run_trace(trace)


def _multi_turn_trace_summary(trace: RunTrace) -> MultiTurnTraceSummary | None:
    if trace.interaction_mode != "interactive_intent" and not trace_conversation_transcript(trace):
        return None
    return normalize_multi_turn_trace_summary({
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
        "session_id": trace.session_id,
        "input": trace.input,
        "turn_traces": [trace],
        "conversation_transcript": trace_conversation_transcript(trace),
        "stop_reason": trace.stop_reason,
        "final_output": trace_extracted_output(trace),
    })


def _live_multi_turn_result(result: LiveExecutionResult) -> LiveMultiTurnResult | None:
    if result.interaction_mode != "interactive_intent" and result.multi_turn_state is None:
        return None
    state = result.multi_turn_state or LiveMultiTurnState(
        session_id=result.session_id,
        transcript=result.execution_trace,
        accumulated_fields=result.extracted_output,
    )
    result.multi_turn_state = state
    return normalize_live_multi_turn_result({
        "project_id": result.project_id,
        "case_id": result.case_id,
        "session_id": result.session_id,
        "turn_results": [result],
        "conversation_transcript": state.transcript,
        "stop_reason": state.stop_reason,
        "final_output": result.extracted_output,
    })


def _interaction_contract(case: SingleTurnCase) -> MultiTurnInteraction | None:
    if not case.metadata.get("interaction"):
        return None
    interaction = normalize_mock_case({**to_dict(case), "interaction": case.metadata.get("interaction")})
    if hasattr(interaction, "interaction"):
        return interaction.interaction
    return MultiTurnInteraction(policy=MultiTurnPolicy(), turn_expectations=[MultiTurnTurnExpectation(turn=1)])


def live_run(project_id: str, case: SingleTurnCase | Dict[str, Any]) -> RunTrace:
    input_data = case.input if isinstance(case, SingleTurnCase) else case
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    case = _case_from_input(project_id, normalize_mock_case(input_data) or SingleTurnCase(id="", input=dict(input_data or {})))
    interaction_contract = _interaction_contract(case)
    live_request = _build_live_request(adapter, case, project_id)
    if adapter.has_provided_output(case, live_request):
        # provided 分支由协议层 ready gate 决定，统一构造 LiveExecutionResult，
        # 不再依赖子类 override call_or_prepare 或硬编码 execution_mode；
        # output_source / execution_mode 在此统一覆盖，项目 build_request 不参与 ready 判定。
        raw_response = adapter.provided_output_raw(case, live_request)
        extracted_output = adapter.extract_output(raw_response)
        result = LiveExecutionResult(
            project_id=project_id,
            case_id=live_request.case_id,
            session_id=live_request.session_id,
            raw_input=live_request.raw_input,
            normalized_request=live_request.normalized_request,
            raw_response=raw_response,
            extracted_output=extracted_output,
            output_source="provided_output",
            call_status="succeeded",
            execution_trace=adapter.build_execution_trace(live_request.raw_input, live_request.normalized_request, raw_response, extracted_output),
            project_fields=adapter.project_fields(raw_response, extracted_output),
            application_boundary=adapter.application_boundary(raw_response, extracted_output),
            interaction_mode="interactive_intent" if live_request.turns else "single_turn",
        )
        if interaction_contract is not None:
            result.interaction_mode = interaction_contract.mode
            result.multi_turn_state = LiveMultiTurnState(session_id=live_request.session_id, transcript=live_request.turns, accumulated_fields=extracted_output)
            _ = _live_multi_turn_result(result)
        trace = _trace_from_live_result(adapter, result)
        trace.execution_mode = "provided"
        trace.ready = ready_from_spec(spec)
        return trace
    try:
        result = _call_live(adapter, live_request)
    except Exception as exc:
        fallback = _fallback_decision(
            fallback_id=f"live-error-{live_request.case_id or project_id}",
            source_stage="live",
            fallback_type="live_error",
            status="error",
            reason=str(exc),
            missing_evidence=["live_response"],
            recoverable=True,
            needs_human_review=True,
            quality_flags=["live_service_unavailable"],
            metadata={"case_id": live_request.case_id, "session_id": live_request.session_id},
        )
        failed_result = LiveExecutionResult(
            project_id=project_id,
            case_id=live_request.case_id,
            session_id=live_request.session_id,
            raw_input=live_request.raw_input,
            normalized_request=live_request.normalized_request,
            call_status="failed",
            call_error=str(exc),
            output_source="live_service_unavailable",
            execution_trace=[{"stage": "project.call", "status": "failed", "evidence": str(exc)}],
            interaction_mode=interaction_contract.mode if interaction_contract is not None else "single_turn",
            fallbacks=[fallback],
        )
        if interaction_contract is not None:
            return RunTrace(
                trace_id=f"run-error-{live_request.case_id or project_id}",
                project_id=project_id,
                case_id=live_request.case_id,
                input=live_request.raw_input,
                normalized_request=live_request.normalized_request,
                live_result=failed_result,
                status="error",
                error=str(exc),
                runtime_logs=["business service call failed"],
                execution_mode="live",
                output_source=failed_result.output_source,
                execution_trace=[{"stage": "project.call", "status": "failed", "evidence": str(exc)}],
                interaction_mode=interaction_contract.mode,
                conversation_transcript=live_request.turns,
                conversation_summary={
                    "session_id": live_request.session_id,
                    "turn_count": len(live_request.turns),
                    "stop_reason": "live_error",
                },
                multi_turn_input={"input": live_request.raw_input},
                fallbacks=[fallback],
            )
        return RunTrace(
            trace_id=f"run-error-{live_request.case_id or project_id}",
            project_id=project_id,
            case_id=live_request.case_id,
            input=live_request.raw_input,
            normalized_request=live_request.normalized_request,
            live_result=failed_result,
            status="error",
            error=str(exc),
            runtime_logs=["business service call failed"],
            execution_mode="live",
            output_source=failed_result.output_source,
            execution_trace=[{"stage": "project.call", "status": "failed", "evidence": str(exc)}],
            fallbacks=[fallback],
        )
    if interaction_contract is not None:
        result.interaction_mode = interaction_contract.mode
        result.multi_turn_state = LiveMultiTurnState(session_id=live_request.session_id, transcript=live_request.turns, accumulated_fields=result.extracted_output)
        _ = _live_multi_turn_result(result)
    trace = _trace_from_live_result(adapter, result)
    trace.execution_mode = "live"
    trace.ready = ready_from_spec(spec)
    return trace


def _normalize_judge_schema_payload(judge_result: JudgeResult) -> JudgeResult:
    return normalize_judge_result(judge_result) or judge_result


def _enforce_judge_live_schema(project_id: str, trace: RunTrace, judge_result: JudgeResult) -> JudgeResult:
    """协议级统一校验：judge 的 actual/expected 必须符合项目 EXTRACT_OUTPUT_SHAPE。

    不抛异常（业务上判 case 失败），标 quality_flags + verdict=uncertain + needs_human_review=True。
    校验全部委托给 LiveSchemaCheck（统一从 SchemaValidator 取）。
    """
    result = _normalize_judge_schema_payload(judge_result)
    live_schema = load_live_schema(project_id)
    checker = getattr(live_schema, "check", None) if live_schema is not None else None
    if checker is None:
        return result
    if result.actual is None:
        result.actual = trace_extracted_output(trace)
    if result.actual is not None and not checker.output(result.actual):
        result.quality_flags = list(result.quality_flags or []) + ["invalid_actual_shape"]
        result.verdict = "uncertain"
        result.needs_human_review = True
        return result
    if result.expected is None:
        result.quality_flags = list(result.quality_flags or []) + ["missing_expected"]
        result.verdict = "uncertain"
        result.needs_human_review = True
        return result
    if not checker.reference(result.expected):
        result.quality_flags = list(result.quality_flags or []) + ["invalid_expected_shape"]
        result.verdict = "uncertain"
        result.needs_human_review = True
        return result
    return result


def _normalize_attribute_schema_payload(attribute_result: AttributeResult) -> AttributeResult:
    return normalize_attribute_result(attribute_result) or attribute_result


def judge(project_id: str, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    # spec/reference.md：trace.ready 是 ready 信号唯一来源。API 路径（前端直接调 /api/judge）传来的 trace
    # 可能不带 ready 快照，此处按 spec.common.ready 补齐，确保 judge 能正确推断 has_reference 阶段。
    if not getattr(trace, "ready", None):
        trace.ready = ready_from_spec(spec)
    pre_judge_result = adapter.pre_judge_result(trace, expected_intent=expected_intent)
    if pre_judge_result is not None:
        return _enforce_judge_live_schema(project_id, trace, adapter.reconcile_judge_result(trace, pre_judge_result))
    project_judge_context = adapter.build_judge_context(trace)
    project_judge_context = {**(project_judge_context or {}), "intent_frame": adapter.build_intent_frame(trace)}
    try:
        result = judge_trace(spec, trace, expected_intent=expected_intent, project_judge_context=project_judge_context)
    except ValueError as e:
        logger.error(f"[pipeline] judge LLM 产出不合规，阻断: {e}")
        fallback = JudgeResult(
            trace_id=trace.trace_id,
            project_id=project_id,
            verdict="uncertain",
            score=None,
            needs_human_review=True,
            quality_flags=["llm_output_validation_failed"],
            reasoning_summary=str(e)[:500],
            judge_method="current_case_llm_judge",
        )
        # 仍走 adapter reconcile 路径，让项目 adapter 有机会从 trace.reference_contract 等本地证据
        # 补充 expected/actual，避免 LLM 失败时直接跳过业务判定。
        try:
            return _enforce_judge_live_schema(project_id, trace, adapter.reconcile_judge_result(trace, fallback))
        except ValueError:
            return fallback
    return _enforce_judge_live_schema(project_id, trace, adapter.reconcile_judge_result(trace, result))


def attribute(project_id: str, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    project_attribute_context = adapter.build_attribute_context(trace, judge_result)
    project_attribute_context = dict(project_attribute_context or {})
    actual = judge_result.actual or trace_extracted_output(trace) or {}
    expected = judge_result.expected or trace.reference_contract or {}
    runtime_context = {
        "expected": expected,
        "actual": actual,
        "reference": trace.reference_contract or {},
        "wrong": list(judge_result.wrong or []),
        "missing": list(judge_result.missing or []),
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
    }
    runtime_values = extract_runtime_values(trace_execution_trace(trace), actual)
    project_attribute_context["runtime_checks"] = adapter.get_runtime_checks(runtime_values, runtime_context)
    result = attribute_failure(spec, trace, judge_result, project_attribute_context=project_attribute_context)
    result = adapter.apply_attribution_probes(trace, judge_result, result)
    return _normalize_attribute_schema_payload(adapter.normalize_attribute_result(trace, judge_result, result))


def _satisfied_fulfillment_status(judge_result: JudgeResult) -> Optional[str]:
    """judge 判定为"已满足"时返回 status 字符串，否则返回 None。"""
    overall = getattr(judge_result, "overall_fulfillment", {}) or {}
    if isinstance(overall, dict):
        status = overall.get("status")
        if status == "fulfilled":
            return status
    if judge_result.verdict == "correct":
        return "correct"
    return None


def _resolve_attribute_fallback(
    context: TraceExecutionContext,
    judge_result: JudgeResult,
    project_id: str,
    trace: RunTrace,
) -> AttributeResult:
    """state_machine 没跑到 attribute 阶段时的兜底归因。

    正常流程：state_machine 的 attribute_expectations / finalize 已在
    context.attribute_result 填好归因。这里只处理 state_machine 提前停止
    （重试耗尽、max_steps 等）的情况。

    - not_fulfilled / incorrect → 跑归因，找不及预期的原因
    - fulfilled / correct → 满足，不需要归因，填固定空壳
    """
    if context.attribute_result is not None:
        return context.attribute_result

    if _satisfied_fulfillment_status(judge_result):
        context.attribute_result = incomplete_state_attribute_result(trace, judge_result)
        return context.attribute_result

    context.attribute_result = attribute(project_id, trace, judge_result)
    return context.attribute_result


def incomplete_state_attribute_result(trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    reason = trace.stop_reason or "state machine stopped before producing failure attribution"
    evidence = list(judge_result.evidence or [reason])
    fallback = _fallback_decision(
        fallback_id=f"attribute-incomplete-{trace.trace_id}",
        source_stage="attribute",
        fallback_type="state_machine_incomplete",
        status="needs_human_review",
        reason=reason,
        missing_evidence=["completed_attribution_probes"],
        recoverable=True,
        needs_human_review=True,
        quality_flags=[*(judge_result.quality_flags or []), "attribute_incomplete"],
        evidence_refs=list(trace.evidence_refs or []),
        metadata={"trace_id": trace.trace_id},
    )
    return AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or ""),
        causal_category="needs_human_review",
        probe_results=[],
        analysis_method="state_machine_incomplete_blocked_attribute",
        chain_nodes=[{"name": "state_machine", "status": "not_verified", "evidence": evidence, "reason": reason}],
        earliest_divergence={"node": "state_machine", "evidence": evidence, "confidence": "unknown"},
        evidence_coverage={"query": bool(trace_input(trace)), "actual": bool(trace_extracted_output(trace)), "expected": bool(judge_result.expected), "execution_trace": bool(trace_execution_trace(trace)), "unsupported_claims": []},
        analysis_quality={"passed": False, "missing": ["completed run_attribution_probes"], "standard": "non-fulfilled business expectations must retain an explicit blocked attribution result."},
        incomplete_reason=reason,
        suspected_locations=[],
        root_cause_hypothesis="状态机未完成归因质量门，当前只能保留待复核失败归因。",
        verification_steps=["检查 state_history 和 gate_decisions，确认 run_attribution_probes 未完成的原因。"],
        patch_direction=["补足当前 case 的归因证据后重新运行；不要在缺少 AttributeResult 时静默通过。"],
        needs_human_review=True,
        scenario=str(trace.scenario or ""),
        quality_flags=[*(judge_result.quality_flags or []), "attribute_incomplete"],
        fallbacks=[fallback],
        summary={
            "causal_category": "needs_human_review",
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
        extensions = load_adapter(spec).build_frontend_extensions(trace)
    return build_frontend_view(spec, trace, judge_result, attribute_result, cluster_summary, check_report, extensions)


def mock_spec(project_id: str) -> MockSpec:
    spec = load_project(project_id)
    analysis_result = analyze_project(project_id)
    mock = normalize_mock_spec({
        "input_modes": ["single_turn", "interactive_intent"],
        "case_sources": list((spec.documents or {}).keys()),
        "mock_guidance": analysis_result.mock_guidance,
        "expected_intent_format": "business expectation text or structured reference",
    })
    return mock or MockSpec()


def mock_cases(project_id: str) -> list[Dict[str, Any]]:
    spec = load_project(project_id)
    _ = mock_spec(project_id)
    # 读固化 mock 数据（impl/data/<pid>/mock_cases.json），不再每次调 LLM。
    import json as _json
    from pathlib import Path as _Path
    seed_path = _Path(__file__).resolve().parents[1] / "data" / project_id / "mock_cases.json"
    if not seed_path.exists():
        return []
    try:
        cases = _json.loads(seed_path.read_text(encoding="utf-8"))
        if isinstance(cases, list):
            return [to_dict(case) for case in (normalize_mock_case(item) for item in cases) if case is not None]
    except Exception:
        logger.warning(f"[mock_cases] failed to parse {seed_path} — treating as data corruption, not empty pool")
        raise


def _regenerate_mock_cases(project_id: str) -> list[Dict[str, Any]]:
    # 重新调 mock_agent 生成并固化 mock 数据。
    # ready 含 output/reference 时，_mock_build_result_to_case 会调度系统侧/judge 侧产出，
    # 形状校验失败会抛 ValueError——这里不能静默吞，否则 ready 项目会静默缺 case。
    spec = load_project(project_id)
    from .mock_agent import MockAgent, build_spec_from_project, load_live_schema
    import json as _json
    from pathlib import Path as _Path
    cases: list[Dict[str, Any]] = []
    live_schema = load_live_schema(project_id)
    if live_schema is not None:
        agent = MockAgent(spec)
        scenarios = getattr(live_schema, "SCENARIO_ENUM", []) or [""]
        for s in scenarios:
            build_spec = build_spec_from_project(spec, scenario=s)
            result = agent.build(build_spec)
            case_dict = _mock_build_result_to_case(result)
            if case_dict and (result.input.get("query") or result.input.get("user_text") or (isinstance(result.input.get("input"), dict) and (result.input["input"].get("question") or result.input["input"].get("query")))):
                cases.append(case_dict)
    seed_path = _Path(__file__).resolve().parents[1] / "data" / project_id / "mock_cases.json"
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(_json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # live_schema 汇总校验：不阻断写入，但打印每个 case 的通过/失败详情，失败记 schema_ok=False
    if live_schema is not None and hasattr(live_schema, "check"):
        summary = live_schema.check.check_all(cases)
        passed = summary["passed"]
        failed = summary["failed"]
        print(f"[live_schema] {project_id}: {passed}/{passed + failed} cases passed schema check", flush=True)
        for detail in summary["details"]:
            if not detail["passed"]:
                print(f"  FAIL [{detail['case_id']}] {detail['scenario']}: {'; '.join(detail['errors'])}", flush=True)
                for c in cases:
                    if c.get("id") == detail["case_id"]:
                        c.setdefault("metadata", {})["schema_ok"] = False
                        break
    return cases


def mock_build_intent(project_id: str, scenario: str = "", intent_labels: list | None = None,
                      template: Dict[str, Any] | None = None, required_input_fields: list | None = None) -> Dict[str, Any]:
    # 顶层入口：调 mock_agent.build_intent 生成单条 case（input 侧字段，无 output/reference）。
    spec = load_project(project_id)
    from .mock_agent import MockAgent, build_spec_from_project
    build_spec = build_spec_from_project(spec, scenario=scenario)
    if intent_labels:
        build_spec.intent_labels = list(intent_labels)
    if required_input_fields:
        build_spec.required_input_fields = list(required_input_fields)
    if template:
        build_spec.template = template
    agent = MockAgent(spec)
    result = agent.build_intent(build_spec)
    return _mock_build_result_to_case(result)


def mock_build_interaction(project_id: str, intent_result: Dict[str, Any], live_context: Dict[str, Any],
                           previous_turns: list | None = None) -> Dict[str, Any]:
    # 顶层入口：调 mock_agent.build_interaction，在已有意图上追加下一轮 turns。
    spec = load_project(project_id)
    from .mock_agent import MockAgent, MockBuildResult, build_spec_from_project
    build_spec = build_spec_from_project(spec, scenario=str(intent_result.get("scenario") or ""))
    base = MockBuildResult(
        case_id=str(intent_result.get("case_id") or ""),
        input=dict(intent_result.get("input") or {}),
        expected_intent=intent_result.get("expected_intent"),
        scenario=str(intent_result.get("scenario") or ""),
        metadata=dict(intent_result.get("metadata") or {}),
    )
    context = dict(live_context or {})
    if previous_turns:
        context["previous_turns"] = list(previous_turns)
    agent = MockAgent(spec)
    result = agent.build_interaction(base, context)
    return _mock_build_result_to_case(result)


def _generate_live_output_for_ready(spec, case_input: Dict[str, Any], intent: Dict[str, Any], project_id: str) -> Optional[Dict[str, Any]]:
    """ready 含 output 时，由系统侧产出 output。
    有真实 live 可调 → 调 adapter.call_or_prepare 真调；
    无 live（QA 这类无真实系统）→ 用系统扮演模块（LLM 扮演系统，按 EXTRACT_OUTPUT_SHAPE 产出合理回答）。
    调度层用 live_schema.check.output() 强校验，不合规阻断。
    """
    output = generate_live_output_with_check(spec, intent, project_id)
    if output is not None:
        return output
    return None


def _generate_reference_for_ready(spec, intent: Dict[str, Any], project_id: str) -> Optional[Dict[str, Any]]:
    """ready 含 reference 时，由 judge 评估侧产出 reference（仅生成 expected 模式，无 actual）。
    调度层用 live_schema.check.reference() 强校验，不合规阻断。
    """
    reference = generate_reference(spec, intent, project_id=project_id)
    if reference is None:
        return None
    live_schema = load_live_schema(project_id)
    if live_schema is not None and hasattr(live_schema, "check"):
        if not live_schema.check.reference(reference):
            raise ValueError(f"reference 不符合 EXTRACT_OUTPUT_SHAPE: {project_id}")
    return reference


def _mock_build_result_to_case(result) -> Dict[str, Any]:
    # MockBuildResult → case dict。
    # ready 协议（spec/reference.md）：mock_agent 只产用户侧产物（意图 + live 输入）。
    # output 在 ready 中 → 系统侧产出（系统扮演模块）；reference 在 ready 中 → judge 评估侧产出（仅生成 expected 模式）。
    # 此函数负责调度这两个外部角色，把产出固化进 case。
    spec = load_project(result.metadata.get("project_id") or "") if result.metadata.get("project_id") else None
    ready = list(result.metadata.get("ready") or []) if result.metadata else []
    project_id = result.metadata.get("project_id") if result.metadata else None

    case = {
        "id": result.case_id,
        "input": dict(result.input or {}),
        "scenario": result.scenario,
        "expected_intent": result.expected_intent or "",
        "source": "mock_agent_llm",
        "status": "pending",
        "metadata": dict(result.metadata or {}),
    }

    if "output" in ready and spec is not None:
        intent_payload = {
            "input": dict(result.input or {}),
            "expected_intent": result.expected_intent,
            "scenario": result.scenario,
        }
        output = _generate_live_output_for_ready(spec, dict(result.input or {}), intent_payload, project_id)
        if output is not None:
            case["output"] = output

    if "reference" in ready and spec is not None:
        intent_payload = {
            "input": dict(result.input or {}),
            "expected_intent": result.expected_intent,
            "scenario": result.scenario,
        }
        reference = _generate_reference_for_ready(spec, intent_payload, project_id)
        if reference is not None:
            case["reference"] = reference

    # 挂载 live_schema 校验
    case["metadata"]["schema_ok"] = _check_case_with_live_schema(case)
    return case


def _check_extracted_output_with_live_schema(project_id: str, output: Any) -> None:
    """挂载 live_schema 校验：adapter.extract_output 是否符合 EXTRACT_OUTPUT_SHAPE。

    校验不阻断，失败记 WARNING。委托给 LiveSchemaCheck（统一从 SchemaValidator 取）。
    """
    try:
        ls = load_live_schema(project_id)
        if ls is not None and hasattr(ls, "check") and isinstance(output, dict):
            ls.check.output(output)
    except Exception as e:
        import sys
        print(f"[live_schema] WARNING: output check failed for {project_id}: {e}", file=sys.stderr)


def _check_case_with_live_schema(case: Dict[str, Any]) -> bool:
    """对 case 跑 live_schema.check.case，失败返回 False。

    委托给 LiveSchemaCheck（统一从 SchemaValidator 取）。
    校验器自身异常 → 不通过（不打通过），记录 WARNING，不静默兜底。
    """
    try:
        pid = _extract_project_id_from_case(case)
        if not pid:
            return True
        ls = load_live_schema(pid)
        if ls is not None and hasattr(ls, "check"):
            return ls.check.case(case)
    except Exception:
        import sys
        print(f"[live_schema] WARNING: schema check exception for case {case.get('id') or '?'} — treating as schema failure", file=sys.stderr)
        return False
    return True  # 无 live_schema → 不约束，默认通过


def _extract_project_id_from_case(case: Dict[str, Any]) -> str:
    """从 case 中提取 project_id，优先 metadata.project_id，其次 case_id 前缀。"""
    meta = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
    pid = meta.get("project_id")
    if pid:
        return str(pid)
    cid = str(case.get("id") or case.get("case_id") or "")
    # 格式: mock-agent-<project_id>-<hex>，project_id 可能含 '-'（如 marketting-planning-intent）
    prefix = "mock-agent-"
    if cid.startswith(prefix):
        rest = cid[len(prefix):]
        # project_id 段一直到最后一个 '-' 之前
        idx = rest.rfind("-")
        if idx > 0:
            return rest[:idx]
    return ""


def _read_mock_cases_file(path: Path) -> tuple[list[Dict[str, Any]], list[str]]:
    """读取一个 mock 数据文件。支持 list 或 {cases: [...]} 两种形状。"""
    import json as _json
    errors: list[str] = []
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [], [f"JSON 读取失败: {e}"]
    if isinstance(data, dict) and isinstance(data.get("cases"), list):
        data = data.get("cases")
    if not isinstance(data, list):
        return [], ["mock 数据必须是 list 或包含 cases:list 的 dict"]
    cases = [item for item in data if isinstance(item, dict)]
    skipped = len(data) - len(cases)
    if skipped:
        errors.append(f"跳过 {skipped} 条非 dict case")
    return cases, errors


def _looks_like_mock_cases(cases: list[Dict[str, Any]]) -> bool:
    """判断 JSON list 是否像 mock case 批数据，避免全库扫描时把索引/配置 JSON 当成 mock。"""
    if not cases:
        return False
    sample = cases[:5]
    hits = 0
    for case in sample:
        if not isinstance(case, dict):
            continue
        if isinstance(case.get("input"), dict) and (case.get("id") or case.get("case_id") or case.get("scenario") or case.get("source")):
            hits += 1
    return hits > 0


def _iter_json_data_files(root: Path) -> list[Path]:
    """扫描代码库内候选 JSON 数据文件，排除明显不是持久 mock 数据的目录。"""
    excluded_parts = {".git", ".claude", "tmp", "__pycache__", "context_store"}
    files: list[Path] = []
    for path in root.rglob("*.json"):
        if any(part in excluded_parts for part in path.parts):
            continue
        if not path.is_file():
            continue
        files.append(path)
    return sorted(files)


def _infer_project_id_for_mock_path(path: Path, case_samples: list[Dict[str, Any]]) -> str:
    """从路径和样本推断 project_id，用于扫描任意 mock 数据文件/目录。"""
    project_set = set(list_projects())
    for case in case_samples:
        pid = _extract_project_id_from_case(case)
        if pid in project_set:
            return pid
    parts = list(path.parts)
    for part in reversed(parts):
        if part in project_set:
            return part
    # 兼容 data/client_search/*.json 这类非标准目录，只要父目录是项目 ID 即可
    parent = path.parent.name
    if parent in project_set:
        return parent
    stem = path.stem
    if stem in project_set:
        return stem
    # 兼容文件名前缀，例如 client_search_xxx.json
    for pid in sorted(project_set, key=len, reverse=True):
        if stem == pid or stem.startswith(pid + "_") or stem.startswith(pid + "-"):
            return pid
    return ""


def _discover_mock_data_files(project_id: str = "", data_path: str = "") -> list[Dict[str, str]]:
    """扫描 mock 数据文件，返回 [{project_id, path}]。

    data_path 可为文件或目录；为空时扫描代码库 data/ 与 impl/data/ 下所有像 mock case 的 JSON。
    """
    files: list[Path] = []
    if data_path:
        p = Path(data_path).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        if p.is_file():
            files = [p]
        elif p.is_dir():
            files = _iter_json_data_files(p)
        else:
            return []
    elif project_id:
        # 指定项目时扫描标准目录 + repo/data/<pid> 非标准批数据目录。
        roots = [IMPL_ROOT / "data" / project_id, IMPL_ROOT.parent / "data" / project_id]
        for root in roots:
            if root.is_file():
                files.append(root)
            elif root.is_dir():
                files.extend(_iter_json_data_files(root))
    else:
        repo_root = IMPL_ROOT.parent
        scan_roots = [repo_root / "data", IMPL_ROOT / "data"]
        seen: set[str] = set()
        for root in scan_roots:
            if root.exists():
                for f in _iter_json_data_files(root):
                    key = str(f)
                    if key not in seen:
                        files.append(f)
                        seen.add(key)

    mapping: list[Dict[str, str]] = []
    for f in sorted(files):
        cases, _ = _read_mock_cases_file(f)
        if not _looks_like_mock_cases(cases):
            continue
        pid = project_id or _infer_project_id_for_mock_path(f, cases[:5])
        if pid:
            mapping.append({"project_id": pid, "path": str(f)})
    return mapping


def _check_mock_cases_for_project(project_id: str, cases: list[Dict[str, Any]], path: str = "", read_errors: list[str] | None = None) -> Dict[str, Any]:
    """检查一批指定项目的 mock cases。"""
    errors = list(read_errors or [])
    warnings: list[str] = []
    live_schema = load_live_schema(project_id)
    if live_schema is None or not hasattr(live_schema, "check"):
        return {"project_id": project_id, "path": path, "count": len(cases), "passed": 0, "failed": len(cases), "errors": errors + ["缺少 live_schema.check"], "warnings": warnings, "details": []}
    summary = live_schema.check.check_all(cases)
    scenarios = list(getattr(live_schema, "SCENARIO_ENUM", []) or [])
    scenario_counts: Dict[str, int] = {}
    for case in cases:
        s = str(case.get("scenario") or "")
        scenario_counts[s] = scenario_counts.get(s, 0) + 1
    missing_scenarios = [s for s in scenarios if scenario_counts.get(s, 0) == 0]
    if missing_scenarios:
        warnings.append("缺少场景: " + ", ".join(missing_scenarios))
    output_count = sum(1 for case in cases if case.get("output") is not None)
    reference_count = sum(1 for case in cases if case.get("reference") is not None)
    return {
        "project_id": project_id,
        "path": path,
        "count": len(cases),
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "scenario_covered": len(scenarios) - len(missing_scenarios) if scenarios else len(scenario_counts),
        "scenario_total": len(scenarios) if scenarios else len(scenario_counts),
        "scenario_counts": scenario_counts,
        "output_count": output_count,
        "reference_count": reference_count,
        "errors": errors,
        "warnings": warnings,
        "details": summary.get("details", []),
    }


def check_mock_data(project_id: str = "", data_path: str = "", cases: list[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """预构建 mock 数据检查点。

    - project_id：指定项目；为空时按路径/扫描结果推断。
    - data_path：指定 JSON 文件或目录；为空时扫描代码库 data/ 和 impl/data/ 中所有 mock JSON。
    - cases：一次性批量数据；传入后不读文件，必须能从 project_id 或 case metadata 推断项目。
    """
    results: Dict[str, Any] = {"items": [], "passed": 0, "failed": 0, "total": 0, "errors": [], "mapping": []}
    if cases is not None:
        pid = project_id or _infer_project_id_for_mock_path(Path(data_path or "inline_cases"), cases[:5])
        if not pid:
            results["errors"].append("无法推断 inline cases 的 project_id，请显式传 project_id")
            results["failed"] = len(cases)
            results["total"] = len(cases)
            return results
        item = _check_mock_cases_for_project(pid, cases, path=data_path or "<inline>")
        results["items"].append(item)
        results["mapping"].append({"project_id": pid, "path": item["path"]})
    else:
        mapping = _discover_mock_data_files(project_id=project_id, data_path=data_path)
        results["mapping"] = mapping
        if not mapping:
            results["errors"].append("未发现可检查的 mock 数据文件")
            return results
        for item in mapping:
            path = item["path"]
            pid = item["project_id"]
            mock_cases, read_errors = _read_mock_cases_file(Path(path))
            results["items"].append(_check_mock_cases_for_project(pid, mock_cases, path=path, read_errors=read_errors))
    for item in results["items"]:
        results["passed"] += int(item.get("passed") or 0)
        results["failed"] += int(item.get("failed") or 0)
        results["total"] += int(item.get("count") or 0)
        if item.get("errors"):
            results["errors"].extend([f"{item.get('project_id')}: {e}" for e in item.get("errors") or []])
    results["ok"] = not results["errors"] and results["failed"] == 0
    return results


def mock_datasets(project_id: str) -> list[Dict[str, Any]]:
    # 读固化 mock 数据，按 scenario 分组构造 dataset 列表。
    # mock 数据已固化在 impl/data/<pid>/mock_cases.json，不再每次调 LLM。
    cases = mock_cases(project_id)
    if not cases:
        return []
    by_scenario: dict[str, list[Dict[str, Any]]] = {}
    for c in cases:
        s = c.get("scenario") or ""
        by_scenario.setdefault(s, []).append(c)
    datasets: list[Dict[str, Any]] = []
    for s, c_list in by_scenario.items():
        datasets.append({
            "dataset_id": f"{project_id}_{s}",
            "name": f"{s} mock 数据集",
            "dimension_type": s,
            "description": f"mock_agent 生成的 {s} 场景用例",
            "case_count": len(c_list),
            "cases": c_list,
        })
    return datasets


def _run_payload(
    trace: RunTrace,
    judge_result: JudgeResult,
    attribute_result: Optional[AttributeResult],
    cluster_summary: Optional[ClusterSummary] = None,
    check_report: Optional[CheckReport] = None,
    view: Optional[FrontendViewModel] = None,
    table_row: Optional[TraceTableRow] = None,
    **metadata: Any,
) -> Dict[str, Any]:
    trace = normalize_run_trace(trace) or trace
    judge_result = normalize_judge_result(judge_result) or judge_result
    attribute_result = normalize_attribute_result(attribute_result) if attribute_result else None
    cluster_summary = normalize_cluster_summary(cluster_summary) if cluster_summary else None
    check_report = normalize_check_report(check_report) if check_report else None
    view = normalize_frontend_view(view) if view else None
    if table_row is None:
        table_row = build_trace_table_row(trace, judge_result, attribute_result, view, check_report, case_context=metadata)
    payload = {
        "trace": trace,
        "judge": judge_result,
        "attribute": attribute_result,
        "cluster": cluster_summary,
        "check": check_report,
        "frontend_view": view,
        "table_row": table_row,
    }
    payload.update({key: value for key, value in metadata.items() if value is not None})
    return payload


def _run_fallbacks(run: Mapping[str, Any]) -> list[FallbackDecision]:
    fallbacks: list[FallbackDecision] = []
    for key in ("trace", "judge", "attribute", "check"):
        payload = run.get(key)
        if payload is not None:
            fallbacks.extend(list(getattr(payload, "fallbacks", []) or []))
    return fallbacks


def _run_trace(run: Mapping[str, Any]) -> Optional[RunTrace]:
    return normalize_run_trace(run.get("trace"))


def _run_judge(run: Mapping[str, Any]) -> Optional[JudgeResult]:
    return normalize_judge_result(run.get("judge"))


def _run_attribute(run: Mapping[str, Any]) -> Optional[AttributeResult]:
    return normalize_attribute_result(run.get("attribute"))


def _run_check(run: Mapping[str, Any]) -> Optional[CheckReport]:
    return normalize_check_report(run.get("check"))


def _run_frontend_view(run: Mapping[str, Any]) -> Optional[FrontendViewModel]:
    return normalize_frontend_view(run.get("frontend_view"))


def _run_cluster(run: Mapping[str, Any]) -> Optional[ClusterSummary]:
    return normalize_cluster_summary(run.get("cluster"))


def _unsupported_interactive_run(project_id: str, case_id: str, case: Dict[str, Any]) -> Dict[str, Any]:
    fallback = _fallback_decision(
        fallback_id=f"interactive-unsupported-{case_id}",
        source_stage="interactive",
        fallback_type="unsupported_interactive_intent",
        status="needs_human_review",
        reason="interactive_intent is not supported by this project adapter",
        missing_evidence=["adapter.run_interactive"],
        recoverable=True,
        needs_human_review=True,
        quality_flags=["unsupported_interactive_intent"],
        metadata={"case_id": case_id},
    )
    trace = RunTrace(
        trace_id=f"interactive-unsupported-{case_id}",
        project_id=project_id,
        case_id=case_id,
        input=case,
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
        verdict="uncertain",
        score=0,
        confidence=1,
        judge_method="unsupported_interactive_intent",
        verdict_derivation={"why_verdict": "interactive_intent case cannot run because adapter has no interactive hook", "blocking_gaps": ["adapter.run_interactive missing"]},
        reasoning_summary="该项目 adapter 不支持 interactive_intent，已将该 case 限界为 uncertain，不中断批次。",
        quality_flags=["unsupported_interactive_intent"],
        fallbacks=[fallback],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        causal_category="boundary_limitation",
        analysis_method="unsupported_interactive_intent",
        chain_nodes=[{"name": "interactive.dispatch", "status": "failed", "evidence": ["adapter.run_interactive missing"], "reason": "interactive_intent unsupported"}],
        earliest_divergence={"node": "interactive.dispatch", "evidence": ["adapter capability missing"], "confidence": "high"},
        analysis_quality={"passed": False, "missing": ["adapter.run_interactive"], "standard": "interactive_intent 必须由项目 adapter 显式支持。"},
        incomplete_reason="adapter does not implement interactive execution",
        root_cause_hypothesis="当前项目未声明或实现 interactive_intent adapter hook。",
        verification_steps=["检查项目 adapter 是否需要支持 run_interactive。", "确认该 case 是否应归属到声明支持 interactive_intent 的项目。"],
        patch_direction=["为该项目补充 run_interactive 实现，或从该项目 mock 池中移除不属于其边界的 interactive_intent case。"],
        quality_flags=["unsupported_interactive_intent"],
        fallbacks=[fallback],
    )
    run = _run_payload(
        trace,
        judge_result,
        attribute_result,
        case_id=case_id,
        execution_mode="interactive_intent",
        output_source="unsupported_interactive_intent",
        error=trace.error,
    )
    return run


def _batch_case(index: int, case: Dict[str, Any], project_id: str, expected_intent: Optional[str]) -> Dict[str, Any]:
    normalized = normalize_case_interaction(project_id, case, index) if isinstance(case, dict) else None
    if normalized and normalized.mode == "interactive_intent":
        try:
            adapter = load_adapter(load_project(project_id))
            if not hasattr(adapter, "run_interactive"):
                return _unsupported_interactive_run(project_id, normalized.case_id, normalized.source_case)
            run = adapter.run_interactive(normalized)
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
                run["table_row"] = build_trace_table_row(
                    _run_trace(run),
                    _run_judge(run),
                    _run_attribute(run),
                    _run_frontend_view(run),
                    _run_check(run),
                    case_context=run,
                )
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
                trace.execution_mode = trace.execution_mode or ("provided" if any(key in case_input for key in ("raw_response", "response", "output")) else "live")
                trace.output_source = trace.output_source or trace_output_source(trace)
                run["trace"] = trace
            run["case_id"] = trace.case_id if trace else case_id
            run["execution_mode"] = trace.execution_mode if trace else ("provided" if any(key in case_input for key in ("raw_response", "response", "output")) else "live")
            run["output_source"] = trace_output_source(trace) if trace else ""
            if trace and run.get("table_row"):
                run["table_row"] = build_trace_table_row(
                    trace,
                    _run_judge(run),
                    _run_attribute(run),
                    _run_frontend_view(run),
                    _run_check(run),
                    case_context=run,
                )
            if attempt > 0:
                run["retry_attempt"] = attempt
            return run
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                import time as _time
                _time.sleep(2.0 * (attempt + 1))
    error_text = str(last_exc or "batch case failed")
    fallback = _fallback_decision(
        fallback_id=f"batch-case-error-{case_id}",
        source_stage="batch",
        fallback_type="batch_case_exception",
        status="error",
        reason=error_text,
        missing_evidence=["completed_run_chain"],
        recoverable=True,
        needs_human_review=True,
        quality_flags=["batch_case_failed"],
        metadata={"case_id": case_id, "attempts": MAX_RETRIES + 1},
    )
    trace = RunTrace(
        trace_id=f"batch-error-{case_id}",
        project_id=project_id,
        case_id=case_id,
        input=case_input,
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
        verdict="uncertain",
        score=0,
        confidence=1,
        judge_method="batch_case_exception",
        verdict_derivation={"why_verdict": error_text, "blocking_gaps": [f"batch case failed after {MAX_RETRIES + 1} attempts"]},
        reasoning_summary=error_text,
        quality_flags=["batch_case_failed"],
        fallbacks=[fallback],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        causal_category="implementation_bug",
        analysis_method="batch_case_exception",
        chain_nodes=[{"name": "batch_run", "status": "failed", "evidence": [error_text], "reason": error_text}],
        earliest_divergence={"node": "batch_run", "evidence": [error_text], "confidence": "high"},
        analysis_quality={"passed": False, "missing": ["completed run_chain"], "standard": "单 case 失败需要保留错误并让批次继续。"},
        incomplete_reason=f"batch case failed after {MAX_RETRIES + 1} attempts",
        root_cause_hypothesis=error_text,
        verification_steps=["用相同 case 单独运行 run_chain，定位是输入、adapter 还是外部服务异常。", "检查 trace.error 和 runtime_logs 后再决定是否修改业务实现。"],
        patch_direction=["修复导致 run_chain 抛错的源头；不要只在 batch 层吞掉异常或改展示结果。"],
        quality_flags=["batch_case_failed"],
        fallbacks=[fallback],
    )
    run = _run_payload(
        trace,
        judge_result,
        attribute_result,
        case_id=case_id,
        execution_mode="error",
        output_source="batch_case_exception",
        error=error_text,
    )
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
        verdict="uncertain",
        score=0,
        confidence=1,
        judge_method="batch_future_exception",
        verdict_derivation={"why_verdict": str(exc), "blocking_gaps": ["batch case failed outside run_chain"]},
        reasoning_summary=str(exc),
        quality_flags=["batch_case_failed"],
        fallbacks=[fallback],
    )
    attribute_result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=project_id,
        case_id=case_id,
        causal_category="implementation_bug",
        analysis_method="batch_future_exception",
        chain_nodes=[{"name": "batch_run", "status": "failed", "evidence": [str(exc)], "reason": str(exc)}],
        earliest_divergence={"node": "batch_run", "evidence": [str(exc)], "confidence": "high"},
        analysis_quality={"passed": False, "missing": ["completed future result"], "standard": "线程外层失败需要保留错误并让批次继续。"},
        incomplete_reason="batch case failed outside run_chain",
        root_cause_hypothesis=str(exc),
        verification_steps=["检查 batch worker future 的异常栈和对应 case 输入。", "用该 case 单独运行 run_chain 或 adapter 入口复现。"],
        patch_direction=["修复 batch worker 外层异常源头；保持批次继续但不要把异常 case 聚合为正式根因。"],
        quality_flags=["batch_case_failed"],
        fallbacks=[fallback],
    )
    run = _run_payload(
        trace,
        judge_result,
        attribute_result,
        case_id=case_id,
        execution_mode="error",
        output_source="batch_future_exception",
        error=str(exc),
    )
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
    fallbacks = []
    for run in runs:
        if isinstance(run, dict):
            fallbacks.extend(_run_fallbacks(run))
    attributes = [item for item in (_run_attribute(run) for run in runs if isinstance(run, dict) and run.get("attribute")) if item is not None]
    cluster_summary = cluster(project_id, attributes)
    # Select representative run: prefer not_fulfilled, else first non-error
    representative = None
    for priority_status in ("not_fulfilled", "not_evaluable"):
        for run in (runs or []):
            if not isinstance(run, dict): continue
            judge_candidate = run.get("judge")
            if judge_candidate is not None:
                js = getattr(judge_candidate, "summary", None) or run.get("judge_summary") or {}
                js = js if isinstance(js, dict) else {}
            else:
                js = run.get("judge_summary") or {}
            if js.get("fulfillment_status") == priority_status or js.get("verdict") == "incorrect":
                representative = run; break
        if representative: break
    if not representative and runs:
        representative = next((r for r in runs if isinstance(r, dict) and not r.get("error")), runs[-1])
    trace = _run_trace(representative) if representative and representative.get("trace") else None
    judge_result = _run_judge(representative) if representative and representative.get("judge") else None
    attribute_result = _run_attribute(runs[-1]) if runs and runs[-1].get("attribute") else None
    check_report = check(project_id, trace, judge_result, attribute_result, cluster_summary)
    failed_run_checks = [item for item in (_run_check(run) for run in runs if isinstance(run, dict) and run.get("check")) if item is not None and item.passed is False]
    if failed_run_checks:
        failed_issues = []
        for item in failed_run_checks:
            failed_issues.extend(str(issue) for issue in item.issues or [])
        check_report.passed = False
        check_report.issues = list(check_report.issues or []) + [issue for issue in failed_issues if issue not in (check_report.issues or [])]
        if "Batch contains case-level check failures." not in check_report.consistency_gaps:
            check_report.consistency_gaps.append("Batch contains case-level check failures.")
        if "Inspect failed case-level CheckReport before trusting aggregate batch output." not in check_report.recommended_fixes:
            check_report.recommended_fixes.append("Inspect failed case-level CheckReport before trusting aggregate batch output.")
    table = build_case_pool_table(project_id, [run.get("table_row") or build_trace_table_row_from_run(to_dict(run)) for run in runs])
    return BatchRunResult(
        project_id=project_id,
        total=len(runs),
        runs=runs,
        cluster=cluster_summary,
        check=check_report,
        table=table,
        fallbacks=fallbacks,
    )


def run_chain(project_id: str, input_data: Dict[str, Any], expected_intent: Optional[str] = None) -> Dict[str, Any]:
    spec = load_project(project_id)
    adapter = load_adapter(spec)

    def execute_trace(context: TraceExecutionContext) -> RunTrace:
        context.trace = live_run(project_id, input_data)
        return context.trace

    def collect_evidence(context: TraceExecutionContext) -> RunTrace:
        trace = context.trace
        project_evidence = adapter.collect_state_evidence("collect_evidence", context)
        trace.evidence_refs = list(getattr(trace, "evidence_refs", []) or []) + project_evidence
        return trace

    def collect_project_evidence(context: TraceExecutionContext) -> RunTrace:
        trace = context.trace
        trace.evidence_refs = list(getattr(trace, "evidence_refs", []) or []) + adapter.collect_state_evidence("project_collect_evidence", context)
        return trace

    def build_expectations(context: TraceExecutionContext) -> JudgeResult:
        trace = context.trace
        context.judge_result = judge(project_id, trace, expected_intent=expected_intent)
        return context.judge_result

    def evaluate_fulfillment(context: TraceExecutionContext) -> JudgeResult:
        return context.judge_result

    def probe_attribute(context: TraceExecutionContext) -> AttributeResult:
        trace = context.trace
        judge_result = context.judge_result
        context.attribute_result = attribute(project_id, trace, judge_result)
        return context.attribute_result

    def finalize(context: TraceExecutionContext) -> CheckReport:
        trace = context.trace
        judge_result = context.judge_result
        attribute_result = context.attribute_result or attribute(project_id, trace, judge_result)
        context.attribute_result = attribute_result
        context.cluster_summary = cluster(project_id, [attribute_result])
        context.check_report = check(project_id, trace, judge_result, attribute_result, context.cluster_summary)
        return context.check_report

    context = TraceExecutionContext(project_id=project_id, input_data=input_data, expected_intent=expected_intent)
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

    trace = context.trace
    trace.state_history = list(context.state_history or [])
    trace.gate_decisions = flatten_gate_decisions(trace.state_history)
    trace.transition_decisions = flatten_transition_decisions(trace.state_history)
    trace.stop_reason = str(context.stop_reason or trace.stop_reason or "completed")
    judge_result = context.judge_result
    if not judge_result:
        judge_result = JudgeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            verdict="uncertain",
            actual=trace_extracted_output(trace),
            reconstructed_intent=str(trace_normalized_request(trace).get("query") or trace_normalized_request(trace).get("user_intent") or ""),
            judge_basis="trace_execution_incomplete",
            judge_method="state_machine_human_review",
            verdict_derivation={"blocking_gaps": [trace.error or trace.stop_reason or "trace execution incomplete"], "why_verdict": "trace did not reach judge because execution failed or required human review"},
            boundary_decision={"within_evaluable_scope": False, "reasoning": trace.error or trace.stop_reason or "trace execution incomplete"},
            evaluation_boundary={"primary_boundary_id": "trace_execution_incomplete", "verdict_basis": "judge skipped because trace execution did not complete"},
            evidence=[trace.error or trace.stop_reason or "trace execution incomplete"],
            reasoning_summary=trace.error or "trace execution incomplete; human review required before judge",
            needs_human_review=True,
            quality_flags=["trace_execution_incomplete", "human_review_required"],
            fallbacks=[_fallback_decision(
                fallback_id=f"judge-incomplete-{trace.trace_id}",
                source_stage="judge",
                fallback_type="trace_execution_incomplete",
                status="needs_human_review",
                reason=trace.error or trace.stop_reason or "trace execution incomplete",
                missing_evidence=["completed_trace_execution", "judge_evidence"],
                recoverable=True,
                needs_human_review=True,
                quality_flags=["trace_execution_incomplete", "human_review_required"],
                evidence_refs=list(trace.evidence_refs or []),
                metadata={"trace_id": trace.trace_id},
            )],
        )
        context.judge_result = judge_result
    attribute_result = _resolve_attribute_fallback(context, judge_result, project_id, trace)
    cluster_summary = context.cluster_summary or (cluster(project_id, [attribute_result]) if attribute_result else cluster(project_id, []))
    check_report = context.check_report or check(project_id, trace, judge_result, attribute_result, cluster_summary)
    if trace.fallbacks or judge_result.fallbacks or (attribute_result and attribute_result.fallbacks):
        check_report.fallbacks = [*(trace.fallbacks or []), *(judge_result.fallbacks or []), *((attribute_result.fallbacks if attribute_result else []) or [])]

    judge_result.gate_decisions = trace.gate_decisions
    judge_result.transition_decisions = trace.transition_decisions
    if attribute_result:
        attribute_result.gate_decisions = trace.gate_decisions
        attribute_result.transition_decisions = trace.transition_decisions

    view = frontend_view(project_id, trace, judge_result, attribute_result, cluster_summary, check_report)
    table_row = view.table_row or build_trace_table_row(trace, judge_result, attribute_result, view, check_report)
    return _run_payload(trace, judge_result, attribute_result, cluster_summary, check_report, view, table_row)
