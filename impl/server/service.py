from __future__ import annotations

import importlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..core import (
    capability_store,
    case_pool,
    context_store,
    exploration_store,
    findings_ledger,
    materials_store,
    pipeline,
    run_store,
    session_store,
)
from ..core.config import get_runtime_config
from ..core.instances import INSTANCE_ENV
from ..core.project_loader import list_projects
from ..core.schema import (
    BatchRunResult,
    CasePoolSaveResponse,
    CasePoolsResponse,
    MockBuildResponse,
    MockCasesResponse,
    MockDataset,
    MockDatasetsResponse,
    RunChainResponse,
    SingleTurnCase,
    normalize_attribute_result,
    normalize_attribute_results,
    normalize_case_pool_table,
    normalize_check_report,
    normalize_cluster_summary,
    normalize_frontend_view,
    normalize_judge_result,
    normalize_run_trace,
    to_dict,
)
from ..core.table_view import build_case_pool_table_from_runs, build_trace_table_row, build_trace_table_row_from_run
SERVER_STARTED_AT = time.time()


@dataclass(frozen=True)
class _ContextAnalysisOutput:
    analysis: str


def _config_hash() -> str:
    return get_runtime_config().fingerprint()


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def project_from(data: Dict[str, Any]) -> str:
    return str(data.get("project") or data.get("project_id") or "")


def compact_mapping(value: Any) -> Any:
    if isinstance(value, list):
        return [compact_mapping(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: compact_mapping(item)
        for key, item in value.items()
        if key not in {"raw_text", "raw_response", "downstream_payload", "raw_sections", "raw_sse", "raw_cards", "raw_model_text", "frontend_view"}
    }


def compact_run(run: Dict[str, Any]) -> Dict[str, Any]:
    trace_obj = normalize_run_trace(run.get("trace"))
    judge_obj = normalize_judge_result(run.get("judge"))
    attribute_obj = normalize_attribute_result(run.get("attribute"))
    check_obj = normalize_check_report(run.get("check"))
    frontend_view_obj = normalize_frontend_view(run.get("frontend_view"))
    cluster_obj = normalize_cluster_summary(run.get("cluster"))
    trace = to_dict(trace_obj) if trace_obj else {}
    judge = compact_mapping(to_dict(judge_obj) if judge_obj else {})
    attribute = compact_mapping(to_dict(attribute_obj) if attribute_obj else {})
    frontend_view = to_dict(frontend_view_obj) if frontend_view_obj else {}
    frontend_view.pop("raw_sections", None)
    compact_trace = dict(trace)
    compact_trace.pop("raw_response", None)
    compact_trace["schema_protocol_extensions"] = compact_mapping(compact_trace.pop("project_fields", {}) or {})
    live_result = trace.get("live_result") if isinstance(trace.get("live_result"), dict) else {}
    compact = {
        "case_id": trace.get("case_id") or run.get("case_id"),
        "execution_mode": trace.get("execution_mode") or run.get("execution_mode"),
        "output_source": trace.get("output_source") or run.get("output_source") or live_result.get("output_source"),
        "trace_id": trace.get("trace_id"),
        "trace": compact_trace,
        "judge": judge,
        "attribute": attribute,
        "cluster": to_dict(cluster_obj) if cluster_obj else None,
        "check": to_dict(check_obj) if check_obj else None,
        "frontend_view": frontend_view,
        "error": run.get("error"),
    }
    if run.get("llmtracing") is not None:
        compact["llmtracing"] = run["llmtracing"]
    if run.get("capability_carrier") is not None:
        compact["capability_carrier"] = run.get("capability_carrier")
    if run.get("eval_axes") is not None:
        compact["eval_axes"] = run.get("eval_axes")
    if run.get("stage_timings"):
        compact["stage_timings"] = run.get("stage_timings")
    table_row = build_trace_table_row_from_run(compact)
    compact["table_row"] = to_dict(table_row)
    compact["status"] = table_row.status
    return compact


def compact_batch_result(batch_result: Any, identities: list[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    data = to_dict(batch_result)
    data["runs"] = [compact_run(run) for run in data.get("runs", [])]
    for index, run in enumerate(data["runs"]):
        if identities and index < len(identities):
            run.update(identities[index])
    if data.get("table"):
        data["table"] = to_dict(normalize_case_pool_table(data.get("table")))
    else:
        data["table"] = to_dict(build_case_pool_table_from_runs(data.get("project_id", ""), data["runs"]))
    return data


def case_event(index: int, run: Dict[str, Any], identity: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return case_event_from_compact(index, compact_run(run), identity)


def case_event_from_compact(index: int, compact: Dict[str, Any], identity: Dict[str, Any] | None = None) -> Dict[str, Any]:
    table_row = compact.get("table_row") or {}
    judge_summary = table_row.get("judge_summary") or {}
    attribution_summary = table_row.get("attribution_summary") or {}
    reason = attribution_summary.get("summary_text") or judge_summary.get("reason") or compact.get("error") or ""
    return {
        **(identity or {}),
        "index": index,
        "case_id": compact.get("case_id"),
        "status": table_row.get("fulfillment_status") or table_row.get("status") or compact.get("status") or "",
        "error": compact.get("error") or (compact.get("trace") or {}).get("error") or "",
        "reason": reason,
        "reason_source": attribution_summary.get("attribution_status") or judge_summary.get("reason_source") or "",
        "reason_stage": table_row.get("divergence_stage") or judge_summary.get("reason_stage") or "",
        "is_formal_attribution": bool(attribution_summary.get("is_formal_attribution", False)),
        "judge_reason": judge_summary.get("reason") or "",
        "judge_reason_source": judge_summary.get("reason_source") or "",
        "judge_reason_stage": judge_summary.get("reason_stage") or "",
        "run": compact,
    }


def health() -> Dict[str, Any]:
    runtime_config = get_runtime_config()
    return {
        "status": "ok",
        "pid": os.getpid(),
        "instance_id": os.environ.get(INSTANCE_ENV),
        "started_at": datetime.fromtimestamp(SERVER_STARTED_AT, tz=timezone.utc).isoformat(),
        "config_hash": _config_hash(),
        "code_version": _git_commit(),
        "server": {
            "host": runtime_config.server.host,
            "port": runtime_config.server.port,
        },
        "uat": {
            "host": runtime_config.uat.host,
            "port": runtime_config.uat.port,
        },
    }


def projects() -> Dict[str, Any]:
    return {"projects": list_projects()}


def analysis(data: Dict[str, Any]) -> Any:
    return pipeline.analysis(project_from(data))


def _runtime_case_from_live_payload(data: Dict[str, Any]) -> SingleTurnCase:
    """Resolve the explicit transport boundary into one runtime case.

    ``input`` always carries a project REQUEST_SCHEMA payload. ``case`` always
    carries the canonical transport MockCase. Keeping the two fields distinct
    avoids inspecting project-owned keys such as DeerFlow's top-level ``input``.
    """
    has_input = "input" in data
    has_case = "case" in data
    if has_input == has_case:
        raise ValueError("live request must provide exactly one of 'input' or 'case'")

    if has_case:
        from ..core.mock import mock_case_to_single_turn, parse_mock_case

        stored_case = parse_mock_case(data.get("case"), project_id=project_from(data))
        return mock_case_to_single_turn(stored_case)

    request = data.get("input")
    if not isinstance(request, dict):
        raise ValueError("live request 'input' must be an object")
    return SingleTurnCase(
        id="",
        input=dict(request),
    )


def live_run(data: Dict[str, Any]) -> Any:
    return pipeline.live_run(project_from(data), _runtime_case_from_live_payload(data))


def mock_cases(data: Dict[str, Any]) -> MockCasesResponse:
    project = project_from(data)
    from ..core.mock import parse_mock_case
    count = int(data.get("count") or 1)
    return MockCasesResponse(project_id=project, cases=[parse_mock_case(case, project_id=project) for case in pipeline.mock_cases(project, count=count)])


def mock_datasets(data: Dict[str, Any]) -> MockDatasetsResponse:
    project = project_from(data)
    from ..core.mock import parse_mock_case

    count = int(data.get("count") or 1)
    datasets = []
    for raw_dataset in pipeline.persisted_mock_datasets(project, count=count):
        dataset = to_dict(raw_dataset)
        if not isinstance(dataset, dict):
            raise TypeError("pipeline.persisted_mock_datasets must return dataset objects")
        cases = [
            parse_mock_case(case, project_id=project)
            for case in dataset.get("cases") or []
        ]
        datasets.append(MockDataset(
            dataset_id=str(dataset.get("dataset_id") or dataset.get("id") or ""),
            name=str(dataset.get("name") or ""),
            dimension_type=str(dataset.get("dimension_type") or dataset.get("type") or ""),
            description=str(dataset.get("description") or ""),
            cases=cases,
            case_count=len(cases),
        ))
    return MockDatasetsResponse(project_id=project, datasets=datasets)


def mock_build_intent(data: Dict[str, Any]) -> MockBuildResponse:
    project = project_from(data)
    case = pipeline.mock_build_intent(
        project,
        scenario=data.get("scenario") or "",
        requested_intent=data.get("requested_intent") or "",
        intent_labels=data.get("intent_labels") or [],
        template=data.get("template"),
        required_input_fields=data.get("required_input_fields") or [],
    )
    return MockBuildResponse(project_id=project, case=case)


def list_case_pools(data: Dict[str, Any]) -> CasePoolsResponse:
    project = project_from(data)
    return CasePoolsResponse(project_id=project, pools=case_pool.list_case_pools(project))


def save_case_pool(data: Dict[str, Any]) -> CasePoolSaveResponse:
    saved = case_pool.save_case_pool(project_from(data), data.get("name") or "", data.get("cases") or [])
    return CasePoolSaveResponse(id=saved.get("id", ""), name=saved.get("name", ""), cases=saved.get("cases", []))


def load_case_pool(data: Dict[str, Any]) -> Any:
    return case_pool.load_case_pool(project_from(data), data.get("id") or "")


def delete_case_pool(data: Dict[str, Any]) -> Any:
    return case_pool.delete_case_pool(project_from(data), data.get("id") or "")


def materials_overview(data: Dict[str, Any]) -> Any:
    from ..core import materials_overview as overview

    return overview.project_overview(project_from(data))


def material_asset_view(data: Dict[str, Any]) -> Any:
    from ..core import materials_overview as overview

    return overview.asset_view(project_from(data), str(data.get("asset_id") or ""))


def material_asset_file(data: Dict[str, Any]) -> Any:
    from ..core import materials_overview as overview

    return overview.asset_file(
        project_from(data),
        str(data.get("asset_id") or ""),
        str(data.get("scope") or ""),
        str(data.get("path") or ""),
    )


def get_material(data: Dict[str, Any]) -> Any:
    return materials_store.get_material(project_from(data), str(data.get("id") or ""))


def upload_material(data: Dict[str, Any]) -> Any:
    import uuid

    material_id = str(data.get("id") or "") or f"m-{uuid.uuid4().hex[:8]}"
    return materials_store.save_material(
        project_from(data),
        material_id,
        content=str(data.get("content") or ""),
        title=str(data.get("title") or ""),
        description=str(data.get("description") or ""),
    )


def delete_material(data: Dict[str, Any]) -> Any:
    return materials_store.delete_material(project_from(data), str(data.get("id") or ""))


def list_capabilities(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    return {"project_id": project, "capabilities": capability_store.load_capability_map(project)}


def save_capability(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    name = str(data.get("name") or "")
    entry = capability_store.validate_entry(name, data.get("entry") or {})
    checked = None
    if project in EVAL_AXES_PROJECTS:
        # llm_probe 只校验（返回 None）；llm_probe_loop 另返回不挡保存的警告，页面显示在保存结果里
        checked = _project_module(project, "eval_axes.validate").validate_scenario_entry(entry, owner=name)
    return {**capability_store.save_capability(project, name, entry), "warnings": list(checked.warnings) if checked else []}


def delete_capability(data: Dict[str, Any]) -> Any:
    return capability_store.delete_capability(project_from(data), str(data.get("name") or ""))


# 扩展评估轴：llm_probe（工作流路线）与 llm_probe_loop（axis loop 路线，spec/alg/axis_loop.md §2）。
EVAL_AXES_PROJECTS = ("llm_probe", "llm_probe_loop")


def _require_eval_axes_project(project: str) -> str:
    if project not in EVAL_AXES_PROJECTS:
        raise ValueError(f"扩展评估轴目前只支持项目 {', '.join(EVAL_AXES_PROJECTS)}，收到 {project!r}")
    return project


def _project_module(project: str, name: str):
    return importlib.import_module(f"impl.projects.{project}.{name}")


def eval_axes_types(data: Dict[str, Any]) -> Any:
    project = _require_eval_axes_project(project_from(data))
    return {"project_id": project, "types": _project_module(project, "eval_axes.registry").describe_axis_types()}


def eval_axes_run(data: Dict[str, Any]) -> Any:
    """试验入口：对页面上已有的同一个 trace 跑新链路，不落盘、不经过生产 judge。"""
    project = _require_eval_axes_project(project_from(data))
    trace = normalize_run_trace(data.get("trace"))
    if trace is None:
        raise ValueError("缺 trace：先发一次 live 得到 RunTrace，再运行扩展轴试验")
    from ..core.project_loader import load_project

    report = _project_module(project, "eval_axes").build_report(load_project(project), trace, run_id=str(data.get("run_id") or ""))
    return {"project_id": project, **report}


def business_trace_providers(data: Dict[str, Any]) -> Any:
    project = _require_eval_axes_project(project_from(data))
    return {"project_id": project, "providers": _project_module(project, "business_trace").provider_descriptions()}


def business_trace_check(data: Dict[str, Any]) -> Any:
    project = _require_eval_axes_project(project_from(data))
    return {"project_id": project, **_project_module(project, "business_trace").check_connection(data.get("business_trace"))}


def knowledge_sources(data: Dict[str, Any]) -> Any:
    project = _require_eval_axes_project(project_from(data))
    return {"project_id": project, **_project_module(project, "eval_axes.sources").list_sources()}


def knowledge_source_save(data: Dict[str, Any]) -> Any:
    project = _require_eval_axes_project(project_from(data))
    return {"project_id": project, **_project_module(project, "eval_axes.sources").save_source(str(data.get("name") or ""), data.get("entry"))}


def knowledge_source_delete(data: Dict[str, Any]) -> Any:
    project = _require_eval_axes_project(project_from(data))
    return {"project_id": project, **_project_module(project, "eval_axes.sources").delete_source(str(data.get("name") or ""))}


def knowledge_source_check(data: Dict[str, Any]) -> Any:
    project = _require_eval_axes_project(project_from(data))
    return {"project_id": project, **_project_module(project, "eval_axes.sources").check_source(str(data.get("name") or ""))}


def judge(data: Dict[str, Any]) -> Any:
    return pipeline.judge(project_from(data), normalize_run_trace(data.get("trace")))


# --- Session 工具（spec/mock/protocol.md 5.1）---

def session_open(data: Dict[str, Any]) -> Any:
    return session_store.STORE.open(
        project_from(data),
        mode=str(data.get("mode") or "text"),
        budget=data.get("budget") or {},
        seed_prefix=data.get("seed_prefix") or [],
        seed_mode=data.get("seed_mode"),
        pool=str(data.get("pool") or ""),
        run_id=str(data.get("run_id") or ""),
        scenario=str(data.get("scenario") or ""),
    )


def session_send(data: Dict[str, Any]) -> Any:
    return session_store.STORE.send(str(data.get("session_id") or ""), dict(data.get("message") or {}), tokens=int(data.get("tokens") or 0))


def session_intent(data: Dict[str, Any]) -> Any:
    return session_store.STORE.intent(
        str(data.get("session_id") or ""),
        user_intent=str(data.get("user_intent") or ""),
        user_context=data.get("user_context") or {},
        source=str(data.get("source") or "seeded"),
    )


def session_close(data: Dict[str, Any]) -> Any:
    return session_store.STORE.close(str(data.get("session_id") or ""), str(data.get("stop_reason") or ""))


def session_list(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    payload = session_store.STORE.list(project or None)
    if data.get("include_exports", True) and project:
        payload["exports"] = session_store.STORE.list_exports(project, run_id=str(data.get("run_id") or ""))
    return payload


def session_get(data: Dict[str, Any]) -> Any:
    return session_store.STORE.export_of(project_from(data), str(data.get("session_id") or ""))


def _judge_signatures(judge_result: Any) -> List[str]:
    """失败签名建议：blocking expectation_id + 失败状态（5.4）。"""
    blocking = {
        item.expectation_id for item in (judge_result.business_expectations or []) if getattr(item, "blocking", False)
    }
    signatures = []
    for item in judge_result.fulfillment_assessments or []:
        status = str(item.status or "").lower()
        if status and status != "fulfilled" and (not blocking or item.expectation_id in blocking):
            signatures.append(f"{item.expectation_id}:{status}")
    return signatures


def session_judge(data: Dict[str, Any]) -> Any:
    """对已导出的会话 trace 跑 judge，并把结论写回导出文件。不阻断 harness。"""
    project = project_from(data)
    session_id = str(data.get("session_id") or "")
    export = session_store.STORE.export_of(project, session_id)
    trace = normalize_run_trace(export.get("trace"))
    result = pipeline.judge(project, trace)
    verdict = str((result.overall_fulfillment or {}).get("status") or "") or None
    summary = str(result.reasoning_summary or "")
    session_store.STORE.update_export(
        project, session_id, judge=to_dict(result), judge_verdict=verdict, judge_summary=summary,
    )
    return {
        "session_id": session_id,
        "judge_verdict": verdict,
        "diverged_at_turn": trace.diverged_at_turn if trace else None,
        "signatures": _judge_signatures(result),
        "reasoning_summary": summary,
        "assessments": [
            {"expectation_id": item.expectation_id, "status": item.status, "downstream_impact": item.downstream_impact}
            for item in (result.fulfillment_assessments or [])
        ],
    }


def ledger_add(data: Dict[str, Any]) -> Any:
    return findings_ledger.add(
        project_from(data),
        signature=str(data.get("signature") or ""),
        session_id=str(data.get("session_id") or ""),
        trigger_summary=str(data.get("trigger_summary") or ""),
        realism=str(data.get("realism") or "medium"),
        harness_verdict=str(data.get("harness_verdict") or ""),
        judge_verdict=data.get("judge_verdict"),
        protocol_fuzz=bool(data.get("protocol_fuzz")),
        run_id=str(data.get("run_id") or ""),
        notes=str(data.get("notes") or ""),
    )


def ledger_query(data: Dict[str, Any]) -> Any:
    return findings_ledger.query(
        project_from(data),
        category=data.get("category"),
        signature=data.get("signature"),
        session_id=data.get("session_id"),
        run_id=data.get("run_id"),
    )


def exploration_save(data: Dict[str, Any]) -> Any:
    return exploration_store.save_direction(project_from(data), str(data.get("run_id") or ""), data.get("direction"))


def exploration_report(data: Dict[str, Any]) -> Any:
    return exploration_store.save_report(project_from(data), str(data.get("run_id") or ""), data.get("report"))


def exploration_get(data: Dict[str, Any]) -> Any:
    """一个批次的全貌：方向 + 报告 + 该 run_id 下的会话导出摘要 + 台账。探索页与 harness 共用。"""
    project = project_from(data)
    run_id = str(data.get("run_id") or "")
    record = exploration_store.get(project, run_id)
    return {
        **record,
        "sessions": session_store.STORE.list_exports(project, run_id=run_id),
        "ledger": findings_ledger.query(project, run_id=run_id),
    }


def exploration_list(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    runs = exploration_store.list_runs(project)
    exports = session_store.STORE.list_exports(project)
    ledger = findings_ledger.query(project)["records"]
    for run in runs:
        run_id = run.get("run_id")
        run["session_count"] = sum(1 for item in exports if item.get("run_id") == run_id)
        run["ledger_by_category"] = {}
        for item in ledger:
            if item.get("run_id") == run_id:
                run["ledger_by_category"][item["category"]] = run["ledger_by_category"].get(item["category"], 0) + 1
    return {"project_id": project, "runs": runs}


def attribute(data: Dict[str, Any]) -> Any:
    return pipeline.attribute(
        project_from(data),
        normalize_run_trace(data.get("trace")),
        normalize_judge_result(data.get("judge")),
        manual_override=bool(data.get("manual_override")),
    )


def cluster(data: Dict[str, Any]) -> Any:
    return pipeline.cluster(project_from(data), normalize_attribute_results(data.get("attributes", [])))


def check(data: Dict[str, Any]) -> Any:
    return pipeline.check(
        project_from(data),
        normalize_run_trace(data.get("trace")) if data.get("trace") else None,
        normalize_judge_result(data.get("judge")) if data.get("judge") else None,
        normalize_attribute_result(data.get("attribute")) if data.get("attribute") else None,
        normalize_cluster_summary(data.get("cluster")) if data.get("cluster") else None,
    )


def run_chain(data: Dict[str, Any]) -> RunChainResponse:
    runtime_case = _runtime_case_from_live_payload(data)
    run = pipeline.run_chain(project_from(data), runtime_case)
    return RunChainResponse(
        trace=normalize_run_trace(run.get("trace")),
        judge=normalize_judge_result(run.get("judge")),
        attribute=normalize_attribute_result(run.get("attribute")) if run.get("attribute") else None,
        cluster=normalize_cluster_summary(run.get("cluster")) if run.get("cluster") else None,
        check=normalize_check_report(run.get("check")) if run.get("check") else None,
        frontend_view=normalize_frontend_view(run.get("frontend_view")) if run.get("frontend_view") else None,
        table_row=build_trace_table_row_from_run(run) if not run.get("table_row") else run.get("table_row"),
    )


def _workspace_response(project: str) -> Any:
    from ..core.mock import parse_mock_case

    data = run_store.STORE.load(project)
    # 用例仍走 MockCase 边界，不能与运行元数据混成普通 dict 后丢掉 output/reference 的 null。
    for entry in data["cases"]:
        entry["case"] = parse_mock_case(entry["case"], project_id=project)
    return data


def run_workspace(data: Dict[str, Any]) -> Any:
    return _workspace_response(project_from(data))


def replace_run_workspace(data: Dict[str, Any]) -> Any:
    from ..core.mock import parse_mock_case

    project = project_from(data)
    cases = [to_dict(parse_mock_case(case, project_id=project)) for case in data["cases"]]
    run_store.STORE.replace(project, cases, data.get("source") or "uploaded_or_manual")
    return _workspace_response(project)


def clear_run_workspace(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    run_store.STORE.clear(project, keep_cases=data["keep_cases"])
    return _workspace_response(project)


def attribute_run_workspace(data: Dict[str, Any]) -> Any:
    project, key = project_from(data), data["request_key"]
    run = run_store.STORE.get_run(project, key)
    trace, judged = normalize_run_trace(run.get("trace")), normalize_judge_result(run.get("judge"))
    if trace is None or judged is None:
        raise ValueError("当前用例缺少 Trace/Judge，不能归因")
    attr = pipeline.attribute(project, trace, judged, manual_override=True)
    updated = {**run, "attribute": to_dict(attr)}
    updated["frontend_view"] = to_dict(frontend_view({"project": project, **updated}))
    updated["table_row"] = to_dict(build_trace_table_row_from_run(updated))
    run_store.STORE.update_run(project, key, updated)
    return updated


def batch_run(data: Dict[str, Any]) -> BatchRunResult:
    from ..core.mock import parse_mock_case

    concurrency = data.get("concurrency")
    project = project_from(data)
    cases = [to_dict(parse_mock_case(case, project_id=project)) for case in (data.get("cases") or [])]
    result = pipeline.batch_run(project, cases, concurrency=concurrency)
    return BatchRunResult(
        project_id=result.project_id,
        total=result.total,
        runs=result.runs,
        cluster=normalize_cluster_summary(result.cluster) if result.cluster else None,
        check=normalize_check_report(result.check) if result.check else None,
        table=normalize_case_pool_table(result.table) if result.table else None,
        fallbacks=result.fallbacks,
        run_status=result.run_status,
    )


def frontend_view(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    return pipeline.frontend_view(
        project,
        normalize_run_trace(data.get("trace")) if data.get("trace") else None,
        normalize_judge_result(data.get("judge")) if data.get("judge") else None,
        normalize_attribute_result(data.get("attribute")) if data.get("attribute") else None,
        normalize_cluster_summary(data.get("cluster")) if data.get("cluster") else (pipeline.cluster(project, normalize_attribute_results(data.get("attributes", []))) if data.get("attributes") else None),
        normalize_check_report(data.get("check")) if data.get("check") else None,
    )


def trace_view(data: Dict[str, Any]) -> Any:
    if data.get("trace"):
        return normalize_run_trace(data.get("trace"))
    if data.get("run") and isinstance(data.get("run"), dict):
        return normalize_run_trace((data.get("run") or {}).get("trace"))
    request = data.get("input") or {}
    return pipeline.live_run(project_from(data), SingleTurnCase(id="", input=dict(request)))


def table_view(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    if data.get("runs"):
        return build_case_pool_table_from_runs(project, data.get("runs") or [])
    if data.get("run"):
        return build_trace_table_row_from_run(data.get("run") or {})
    trace = normalize_run_trace(data.get("trace")) if data.get("trace") else None
    if not trace:
        return build_case_pool_table_from_runs(project, [])
    return build_trace_table_row(
        trace,
        normalize_judge_result(data.get("judge")) if data.get("judge") else None,
        normalize_attribute_result(data.get("attribute")) if data.get("attribute") else None,
        normalize_frontend_view(data.get("frontend_view") or data.get("view")) if (data.get("frontend_view") or data.get("view")) else None,
        normalize_check_report(data.get("check")) if data.get("check") else None,
        case_context=data.get("case_context") if isinstance(data.get("case_context"), dict) else None,
    )


def list_context_summaries(project_id: str, *, caller: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """列出某项目最近的 LLM 上下文调用摘要（不含 prompt 全量）。"""
    summaries = context_store.list_recent_contexts(project_id, caller=caller, limit=limit)
    return [to_dict(s) for s in summaries]


def list_contexts_by_trace(project_id: str, trace_id: str) -> List[Dict[str, Any]]:
    """某次 trace 的完整 LLM 上下文链（按时间排序，含 prompt 全量）。"""
    records = context_store.load_contexts_by_trace(project_id, trace_id)
    return [to_dict(r) for r in records]


def get_context(project_id: str, trace_id: str, caller: str) -> Dict[str, Any]:
    """某次 trace 中某个 agent 的上下文记录（含 prompt 全量）。"""
    record = context_store.load_context(project_id, trace_id, caller)
    return to_dict(record) if record else {}


def analyze_contexts(data: Dict[str, Any]) -> Dict[str, Any]:
    """L3 LLM 内容分析：取若干条 ContextRecord 拼成分析 prompt 调 LLM。

    防递归：分析调用本身会经过 LlmClient，会被 _track_context 记录成一条
    caller="context_analyzer" 的 ContextRecord。分析 prompt 里明确标注这些是
    待分析样本，避免与正常 agent 调用混淆。
    """
    project_id = str(data.get("project_id") or data.get("project") or "default")
    caller = str(data.get("caller") or "")
    analysis_type = str(data.get("analysis_type") or "redundancy")
    sample_size = max(1, min(10, int(data.get("sample_size") or 3)))
    if not caller:
        return {"error": "caller is required"}
    summaries = context_store.list_recent_contexts(project_id, caller=caller, limit=sample_size * 3)
    if not summaries:
        return {"error": f"no context records for caller={caller} project={project_id}"}
    # 取最近 N 条，按时间倒序
    summaries.sort(key=lambda r: r.created_at, reverse=True)
    picked = summaries[:sample_size]
    # 加载完整记录（含 prompt/response）
    samples = []
    for s in picked:
        full = context_store.load_context(project_id, s.trace_id, s.caller)
        if full:
            samples.append(full)
    if not samples:
        return {"error": "failed to load full context records"}
    system, user = _build_analyze_prompt(analysis_type, caller, samples)
    from .llm_bridge import llm_client_for_analysis
    from ..core.structured_output import StructuredOutputSpec
    client = llm_client_for_analysis(project_id)
    trace_id = f"context-analyze-{caller}"
    output_spec = StructuredOutputSpec.from_dataclass(
        _ContextAnalysisOutput,
        required_nonempty=["analysis"],
        description="上下文样本分析结论",
    )
    from ..core.context_governance import configure_context_governance
    configure_context_governance(
        client,
        config={
            "enabled": True,
            "mode": "production",
            "role": "context_analyzer",
            "stage": analysis_type,
            "trace_id": trace_id,
            "compiler_source": "impl/server/service.py#analyze_contexts",
            "user_source": "context-store://sampled-records",
        },
        project_id=project_id,
        system=system,
        user=user,
        output_spec=output_spec,
        tools=[],
    )
    result = client.complete_json(system, user, trace_id=trace_id, output_spec=output_spec)
    analysis_text = ""
    if isinstance(result, dict):
        if result.get("error"):
            return {"error": result.get("error"), "raw_text": result.get("raw_text", "")}
        analysis_text = str(result.get("analysis") or result.get("summary") or result.get("reasoning_summary") or "")
        if not analysis_text:
            analysis_text = json.dumps(result, ensure_ascii=False)
    else:
        analysis_text = str(result)
    return {"analysis": analysis_text, "caller": caller, "analysis_type": analysis_type, "sample_count": len(samples)}


def _build_analyze_prompt(analysis_type: str, caller: str, samples: List[Any]) -> tuple:
    type_desc = {
        "redundancy": "检测这些 system_prompt 里常驻部分是否过大、是否有可压缩的冗余内容，给出具体可删减的段落",
        "quality": "对 response 做语义抽样，判断 LLM 输出是否有退化迹象（如空泛、重复、不遵循 schema）",
        "consistency": "对比同一 caller 不同 trace 的 prompt 结构差异，指出哪些部分应该固定却变了",
    }.get(analysis_type, "分析这些上下文记录")
    system = (
        "你是通用评估系统的上下文分析器。下面是某个 agent 的若干条 LLM 上下文记录样本。\n"
        f"分析任务：{type_desc}。\n"
        "每条记录包含 system_prompt / user_prompt / response / prompt_size / elapsed_ms / error。\n"
        "只基于样本内容分析，不要编造未提供的信息。分析结论必须使用中文。\n"
    )
    user_parts = [f"caller={caller} analysis_type={analysis_type} sample_count={len(samples)}"]
    for i, s in enumerate(samples, 1):
        msgs = s.messages or []
        sys_msg = next((m for m in msgs if m.get("role") == "system"), {})
        usr_msg = next((m for m in msgs if m.get("role") == "user"), {})
        user_parts.append(
            f"\n--- 样本 {i} (trace_id={s.trace_id} prompt_size={s.prompt_size} elapsed_ms={s.elapsed_ms} error={s.error or 'none'}) ---\n"
            f"system_prompt:\n{str(sys_msg.get('content') or '')[:8000]}\n\n"
            f"user_prompt:\n{str(usr_msg.get('content') or '')[:4000]}\n\n"
            f"response:\n{json.dumps(s.response, ensure_ascii=False)[:4000]}\n"
        )
    return system, "\n".join(user_parts)
