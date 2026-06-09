from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from .analysis import analyze_project
from .attribute import attribute_failure
from .check import check_chain
from .cluster import cluster_attributes
from .frontend_view import build_frontend_view
from .judge import judge_trace
from .project_loader import load_adapter, load_project
from .schema import AttributeResult, BatchRunResult, CheckReport, ClusterSummary, FrontendViewModel, JudgeResult, ProjectAnalysis, RunTrace

IMPL_ROOT = Path(__file__).resolve().parents[1]


def analysis(project_id: str) -> ProjectAnalysis:
    return analyze_project(project_id)


def live_run(project_id: str, input_data: Dict[str, Any], mock: bool = False) -> RunTrace:
    spec = load_project(project_id)
    adapter = load_adapter(spec)
    request = adapter.build_request(input_data)
    if mock:
        raw = adapter.mock_response(request)
    elif adapter.has_provided_output(input_data, request):
        raw = adapter.provided_output_raw(input_data, request)
    else:
        try:
            raw = adapter.call_or_prepare(request)
        except Exception as exc:
            raw = adapter.mock_response(request)
            trace = adapter.to_run_trace(input_data, request, raw)
            trace.status = "error"
            trace.error = str(exc)
            trace.runtime_logs.append("business service call failed; mock response recorded")
            return trace
    return adapter.to_run_trace(input_data, request, raw)


def judge(project_id: str, trace: RunTrace, expected_intent: Optional[str] = None) -> JudgeResult:
    spec = load_project(project_id)
    result = judge_trace(spec, trace, expected_intent=expected_intent)
    return load_adapter(spec).normalize_judge_result(trace, result)


def attribute(project_id: str, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
    return attribute_failure(load_project(project_id), trace, judge_result)


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


def _batch_case(index: int, case: Dict[str, Any], project_id: str, mock: bool, expected_intent: Optional[str]) -> Dict[str, Any]:
    from .schema import to_dict

    if isinstance(case, dict) and any(key in case for key in ("output", "reference", "metadata", "scenario")):
        case_input = {key: case[key] for key in ("input", "output", "reference", "metadata", "scenario") if key in case}
    else:
        case_input = case.get("input", case) if isinstance(case, dict) else case
    if not isinstance(case_input, dict):
        case_input = {"value": case_input}
    if isinstance(case, dict) and case.get("id"):
        case_id = str(case.get("id"))
    else:
        case_id = f"case-{index + 1}"
    case_input = {**case_input, "case_id": case_id}
    case_expected = case.get("expected_intent") if isinstance(case, dict) else None
    try:
        run = run_chain(project_id, case_input, mock=mock, expected_intent=case_expected or expected_intent)
        run["case_id"] = case_id
        return run
    except Exception as exc:
        trace = RunTrace(
            trace_id=f"batch-error-{case_id}",
            project_id=project_id,
            input=case_input,
            normalized_request={},
            status="error",
            error=str(exc),
            runtime_logs=["batch case failed before completing run_chain"],
        )
        judge_result = JudgeResult(
            trace_id=trace.trace_id,
            project_id=project_id,
            verdict="error",
            score=0,
            confidence=1,
            reasoning_summary=str(exc),
            quality_flags=["batch_case_failed"],
        )
        attribute_result = AttributeResult(
            trace_id=trace.trace_id,
            project_id=project_id,
            case_id=case_id,
            failure_category="执行失败",
            failure_stage="batch_run",
            root_cause_hypothesis=str(exc),
            quality_flags=["batch_case_failed"],
        )
        return {"case_id": case_id, "trace": to_dict(trace), "judge": to_dict(judge_result), "attribute": to_dict(attribute_result), "error": str(exc)}


def batch_run(
    project_id: str,
    cases: Iterable[Dict[str, Any]],
    mock: bool = False,
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
            executor.submit(_batch_case, index, case, project_id, mock, expected_intent): index
            for index, case in enumerate(case_list)
        }
        for future in as_completed(futures):
            index = futures[future]
            run = future.result()
            runs_by_index[index] = run
            if on_case_done:
                on_case_done(index, run)

    runs = [runs_by_index[index] for index in range(len(case_list))]
    attributes = [AttributeResult(**run["attribute"]) for run in runs if run.get("attribute")]
    cluster_summary = cluster(project_id, attributes)
    trace = RunTrace(**runs[-1]["trace"]) if runs and runs[-1].get("trace") else None
    judge_result = JudgeResult(**runs[-1]["judge"]) if runs and runs[-1].get("judge") else None
    attribute_result = AttributeResult(**runs[-1]["attribute"]) if runs and runs[-1].get("attribute") else None
    check_report = check(project_id, trace, judge_result, attribute_result, cluster_summary)
    return BatchRunResult(
        project_id=project_id,
        total=len(runs),
        runs=runs,
        cluster=to_dict(cluster_summary),
        check=to_dict(check_report),
    )


def run_chain(project_id: str, input_data: Dict[str, Any], mock: bool = False, expected_intent: Optional[str] = None) -> Dict[str, Any]:
    from .schema import to_dict

    trace = live_run(project_id, input_data, mock=mock)
    judge_result = judge(project_id, trace, expected_intent=expected_intent)
    attribute_result = attribute(project_id, trace, judge_result)
    cluster_summary = cluster(project_id, [attribute_result]) if judge_result.verdict in {"incorrect", "uncertain"} else cluster(project_id, [])
    check_report = check(project_id, trace, judge_result, attribute_result, cluster_summary)
    view = frontend_view(project_id, trace, judge_result, attribute_result, cluster_summary, check_report)
    return {
        "trace": to_dict(trace),
        "judge": to_dict(judge_result),
        "attribute": to_dict(attribute_result) if attribute_result else None,
        "cluster": to_dict(cluster_summary),
        "check": to_dict(check_report),
        "frontend_view": to_dict(view),
    }
