from __future__ import annotations

from typing import Any, Callable, Dict
from html import escape
import subprocess

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from ..core.schema import to_public_dict
from ..core.run_store import WorkspaceBusy, WorkspaceConflict
from . import axes_clustering_jobs, batch_jobs, service, tracing_reports
from ..core import run_store
from .models import (
    AttributeRequest,
    AxesClusteringStateRequest,
    AxesClusteringCriteriaRequest,
    AxesClusteringStartRequest,
    LedgerAddRequest,
    LedgerQueryRequest,
    ExplorationGetRequest,
    ExplorationListRequest,
    ExplorationReportRequest,
    ExplorationSaveRequest,
    SessionCloseRequest,
    SessionGetRequest,
    SessionIntentRequest,
    SessionJudgeRequest,
    SessionListRequest,
    SessionOpenRequest,
    SessionSendRequest,
    BatchRunRequest,
    BatchStartRequest,
    BatchStatusRequest,
    BusinessTraceCheckRequest,
    KnowledgeSourceNameRequest,
    KnowledgeSourceSaveRequest,
    KnowledgeSourcesRequest,
    BusinessTraceProvidersRequest,
    CapabilityDeleteRequest,
    CapabilityListRequest,
    CapabilitySaveRequest,
    MaterialAssetFileRequest,
    MaterialAssetViewRequest,
    MaterialDeleteRequest,
    MaterialGetRequest,
    MaterialsListRequest,
    MaterialUploadRequest,
    CasePoolDeleteRequest,
    CasePoolLoadRequest,
    CasePoolSaveRequest,
    CasePoolsRequest,
    CheckRequest,
    ClusterRequest,
    ContextAnalyzeRequest,
    EvalAxesRunRequest,
    EvalAxesTypesRequest,
    FrontendViewRequest,
    JudgeRequest,
    LiveRunRequest,
    MockCasesRequest,
    MockBuildIntentRequest,
    MockDatasetsRequest,
    ProjectRequest,
    RunChainRequest,
    RunWorkspaceReplaceRequest,
    RunWorkspaceClearRequest,
    RunWorkspaceAttributeRequest,
    TableRequest,
    TraceRequest,
)

router = APIRouter()

# 通用 ToolLoop 试验台独立于评测 / 聚类路由，运行其原生 Python 示例。
from ..tool_loop_lab.api import router as tool_loop_lab_router
router.include_router(tool_loop_lab_router)


@router.get('/api/tracing/report', response_class=HTMLResponse)
def batch_tracing_report(project: str, job_id: str) -> HTMLResponse:
    batch = run_store.STORE.load(project)['batch']
    status, message = 200, ''
    if not batch or batch['job_id'] != job_id:
        status, message = 404, '当前项目没有这批运行记录，请回到评测页面刷新后再查看。'
    else:
        try:
            return HTMLResponse(tracing_reports.render_report(project), headers={'Cache-Control': 'no-store'})
        except FileNotFoundError as exc:
            status, message = 404, str(exc)
        except subprocess.TimeoutExpired:
            status, message = 504, 'LLM Trace 报告生成超时，请稍后重试。'
        except (RuntimeError, OSError) as exc:
            status, message = 500, 'LLM Trace 报告生成失败，请检查 tracing 配置和采集日志。'
    return HTMLResponse(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>LLM Trace</title>'
        '<body style="font-family:system-ui;max-width:760px;margin:64px auto;padding:24px">'
        '<h1>LLM Trace</h1><p>' + escape(message) + '</p><p>批次：' + escape(job_id) + '</p></body></html>',
        status_code=status, headers={'Cache-Control': 'no-store'},
    )


def json_result(value: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=to_public_dict(value), status_code=status_code)


def payload_dict(payload: Any) -> Dict[str, Any]:
    return payload.as_dict()


def route(handler: Callable[[Dict[str, Any]], Any], payload: Any) -> JSONResponse:
    try:
        return json_result(handler(payload_dict(payload)))
    except (WorkspaceBusy, WorkspaceConflict) as exc:
        return json_result({"error": str(exc)}, status_code=409)
    except Exception as exc:
        return json_result({"error": str(exc)}, status_code=500)


@router.get("/health")
def health() -> JSONResponse:
    return json_result(service.health())


@router.get("/projects")
def projects() -> JSONResponse:
    return json_result(service.projects())


@router.post("/api/analysis")
def analysis(payload: ProjectRequest) -> JSONResponse:
    return route(service.analysis, payload)


@router.post("/api/live_run")
def live_run(payload: LiveRunRequest) -> JSONResponse:
    return route(service.live_run, payload)


@router.post("/api/mock_cases")
def mock_cases(payload: MockCasesRequest) -> JSONResponse:
    return route(service.mock_cases, payload)


@router.post("/api/mock_datasets")
def mock_datasets(payload: MockDatasetsRequest) -> JSONResponse:
    return route(service.mock_datasets, payload)


@router.post("/api/mock/build_intent")
def mock_build_intent(payload: MockBuildIntentRequest) -> JSONResponse:
    return route(service.mock_build_intent, payload)


@router.post("/api/case_pools")
def case_pools(payload: CasePoolsRequest) -> JSONResponse:
    return route(service.list_case_pools, payload)


@router.post("/api/case_pool/save")
def case_pool_save(payload: CasePoolSaveRequest) -> JSONResponse:
    return route(service.save_case_pool, payload)


@router.post("/api/case_pool/load")
def case_pool_load(payload: CasePoolLoadRequest) -> JSONResponse:
    return route(service.load_case_pool, payload)


@router.post("/api/case_pool/delete")
def case_pool_delete(payload: CasePoolDeleteRequest) -> JSONResponse:
    return route(service.delete_case_pool, payload)


@router.post("/api/materials")
def materials(payload: MaterialsListRequest) -> JSONResponse:
    return route(service.materials_overview, payload)


@router.post("/api/material/asset_view")
def material_asset_view(payload: MaterialAssetViewRequest) -> JSONResponse:
    return route(service.material_asset_view, payload)


@router.post("/api/material/asset_file")
def material_asset_file(payload: MaterialAssetFileRequest) -> JSONResponse:
    return route(service.material_asset_file, payload)


@router.post("/api/material/get")
def material_get(payload: MaterialGetRequest) -> JSONResponse:
    return route(service.get_material, payload)


@router.post("/api/material/upload")
def material_upload(payload: MaterialUploadRequest) -> JSONResponse:
    return route(service.upload_material, payload)


@router.post("/api/material/delete")
def material_delete(payload: MaterialDeleteRequest) -> JSONResponse:
    return route(service.delete_material, payload)


@router.post("/api/capabilities")
def capabilities(payload: CapabilityListRequest) -> JSONResponse:
    return route(service.list_capabilities, payload)


@router.post("/api/capability/save")
def capability_save(payload: CapabilitySaveRequest) -> JSONResponse:
    return route(service.save_capability, payload)


@router.post("/api/capability/delete")
def capability_delete(payload: CapabilityDeleteRequest) -> JSONResponse:
    return route(service.delete_capability, payload)


@router.post("/api/eval_axes/types")
def eval_axes_types(payload: EvalAxesTypesRequest) -> JSONResponse:
    return route(service.eval_axes_types, payload)


@router.post("/api/eval_axes/run")
def eval_axes_run(payload: EvalAxesRunRequest) -> JSONResponse:
    return route(service.eval_axes_run, payload)


@router.post("/api/business_trace/providers")
def business_trace_providers(payload: BusinessTraceProvidersRequest) -> JSONResponse:
    return route(service.business_trace_providers, payload)


@router.post("/api/business_trace/check")
def business_trace_check(payload: BusinessTraceCheckRequest) -> JSONResponse:
    return route(service.business_trace_check, payload)


@router.post("/api/knowledge_sources")
def knowledge_sources(payload: KnowledgeSourcesRequest) -> JSONResponse:
    return route(service.knowledge_sources, payload)


@router.post("/api/knowledge_source/save")
def knowledge_source_save(payload: KnowledgeSourceSaveRequest) -> JSONResponse:
    return route(service.knowledge_source_save, payload)


@router.post("/api/knowledge_source/delete")
def knowledge_source_delete(payload: KnowledgeSourceNameRequest) -> JSONResponse:
    return route(service.knowledge_source_delete, payload)


@router.post("/api/knowledge_source/check")
def knowledge_source_check(payload: KnowledgeSourceNameRequest) -> JSONResponse:
    return route(service.knowledge_source_check, payload)


@router.post("/api/judge")
def judge(payload: JudgeRequest) -> JSONResponse:
    return route(service.judge, payload)


@router.post("/api/attribute")
def attribute(payload: AttributeRequest) -> JSONResponse:
    return route(service.attribute, payload)


# --- Session 工具（spec/mock/protocol.md 5.1）---

@router.post("/api/session/open")
def session_open(payload: SessionOpenRequest) -> JSONResponse:
    return route(service.session_open, payload)


@router.post("/api/session/send")
def session_send(payload: SessionSendRequest) -> JSONResponse:
    return route(service.session_send, payload)


@router.post("/api/session/intent")
def session_intent(payload: SessionIntentRequest) -> JSONResponse:
    return route(service.session_intent, payload)


@router.post("/api/session/close")
def session_close(payload: SessionCloseRequest) -> JSONResponse:
    return route(service.session_close, payload)


@router.post("/api/session/list")
def session_list(payload: SessionListRequest) -> JSONResponse:
    return route(service.session_list, payload)


@router.post("/api/session/get")
def session_get(payload: SessionGetRequest) -> JSONResponse:
    return route(service.session_get, payload)


@router.post("/api/session/judge")
def session_judge(payload: SessionJudgeRequest) -> JSONResponse:
    return route(service.session_judge, payload)


@router.post("/api/ledger/add")
def ledger_add(payload: LedgerAddRequest) -> JSONResponse:
    return route(service.ledger_add, payload)


@router.post("/api/ledger/query")
def ledger_query(payload: LedgerQueryRequest) -> JSONResponse:
    return route(service.ledger_query, payload)


@router.post("/api/exploration/save")
def exploration_save(payload: ExplorationSaveRequest) -> JSONResponse:
    return route(service.exploration_save, payload)


@router.post("/api/exploration/report")
def exploration_report(payload: ExplorationReportRequest) -> JSONResponse:
    return route(service.exploration_report, payload)


@router.post("/api/exploration/get")
def exploration_get(payload: ExplorationGetRequest) -> JSONResponse:
    return route(service.exploration_get, payload)


@router.post("/api/exploration/list")
def exploration_list(payload: ExplorationListRequest) -> JSONResponse:
    return route(service.exploration_list, payload)


@router.post("/api/cluster")
def cluster(payload: ClusterRequest) -> JSONResponse:
    return route(service.cluster, payload)


@router.post("/api/check")
def check(payload: CheckRequest) -> JSONResponse:
    return route(service.check, payload)


@router.post("/api/run_chain")
def run_chain(payload: RunChainRequest) -> JSONResponse:
    return route(service.run_chain, payload)


@router.post("/api/axes_clustering/state")
def axes_clustering_state(payload: AxesClusteringStateRequest) -> JSONResponse:
    return route(axes_clustering_jobs.state, payload)


@router.post("/api/axes_clustering/criteria")
def axes_clustering_criteria(payload: AxesClusteringCriteriaRequest) -> JSONResponse:
    return route(axes_clustering_jobs.save_criteria, payload)


@router.post("/api/axes_clustering/start")
def axes_clustering_start(payload: AxesClusteringStartRequest) -> JSONResponse:
    return route(axes_clustering_jobs.start, payload)


@router.post("/api/run_workspace")
def run_workspace(payload: ProjectRequest) -> JSONResponse:
    return route(service.run_workspace, payload)


@router.post("/api/run_workspace/replace")
def replace_run_workspace(payload: RunWorkspaceReplaceRequest) -> JSONResponse:
    return route(service.replace_run_workspace, payload)


@router.post("/api/run_workspace/clear")
def clear_run_workspace(payload: RunWorkspaceClearRequest) -> JSONResponse:
    return route(service.clear_run_workspace, payload)


@router.post("/api/run_workspace/attribute")
def attribute_run_workspace(payload: RunWorkspaceAttributeRequest) -> JSONResponse:
    return route(service.attribute_run_workspace, payload)


@router.post("/api/batch_run")
def batch_run(payload: BatchRunRequest) -> JSONResponse:
    return route(service.batch_run, payload)


@router.post("/api/batch_start")
def batch_start(payload: BatchStartRequest) -> JSONResponse:
    try:
        return json_result(batch_jobs.start_batch(payload_dict(payload)))
    except WorkspaceBusy as exc:
        return json_result({"error": str(exc)}, status_code=409)
    except (TypeError, ValueError) as exc:
        return json_result({"error": str(exc)}, status_code=422)
    except Exception as exc:
        return json_result({"error": str(exc)}, status_code=500)


@router.post("/api/batch_status")
def batch_status(payload: BatchStatusRequest) -> JSONResponse:
    try:
        result = batch_jobs.batch_status(payload_dict(payload))
        if not result:
            return json_result({"error": "batch job not found"}, status_code=404)
        return json_result(result)
    except Exception as exc:
        return json_result({"error": str(exc)}, status_code=500)


@router.post("/api/frontend_view")
def frontend_view(payload: FrontendViewRequest) -> JSONResponse:
    return route(service.frontend_view, payload)


@router.post("/api/trace")
def trace(payload: TraceRequest) -> JSONResponse:
    return route(service.trace_view, payload)


@router.post("/api/table")
def table(payload: TableRequest) -> JSONResponse:
    return route(service.table_view, payload)


@router.get("/api/context/summary")
def context_summary(project_id: str, caller: str = "", limit: int = 20) -> JSONResponse:
    return json_result(service.list_context_summaries(project_id, caller=caller, limit=limit))


@router.get("/api/context/{trace_id}")
def context_by_trace(trace_id: str, project_id: str) -> JSONResponse:
    return json_result(service.list_contexts_by_trace(project_id, trace_id))


@router.get("/api/context/{trace_id}/{caller}")
def context_by_caller(trace_id: str, caller: str, project_id: str) -> JSONResponse:
    return json_result(service.get_context(project_id, trace_id, caller))


@router.post("/api/context/analyze")
def context_analyze(payload: ContextAnalyzeRequest) -> JSONResponse:
    return json_result(service.analyze_contexts(payload_dict(payload)))
