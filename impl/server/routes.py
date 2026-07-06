from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core.schema import to_public_dict
from . import batch_jobs, service
from .models import (
    AttributeRequest,
    BatchRunRequest,
    BatchStartRequest,
    BatchStatusRequest,
    CasePoolDeleteRequest,
    CasePoolLoadRequest,
    CasePoolSaveRequest,
    CasePoolsRequest,
    CheckRequest,
    ClusterRequest,
    ContextAnalyzeRequest,
    FrontendViewRequest,
    JudgeRequest,
    LiveRunRequest,
    MockCasesRequest,
    MockBuildInteractionRequest,
    MockBuildIntentRequest,
    MockDatasetsRequest,
    ProjectRequest,
    RunChainRequest,
    TableRequest,
    TraceRequest,
)

router = APIRouter()


def json_result(value: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=to_public_dict(value), status_code=status_code)


def payload_dict(payload: Any) -> Dict[str, Any]:
    return payload.as_dict()


def route(handler: Callable[[Dict[str, Any]], Any], payload: Any) -> JSONResponse:
    try:
        return json_result(handler(payload_dict(payload)))
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


@router.post("/api/mock/build_interaction")
def mock_build_interaction(payload: MockBuildInteractionRequest) -> JSONResponse:
    return route(service.mock_build_interaction, payload)


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


@router.post("/api/judge")
def judge(payload: JudgeRequest) -> JSONResponse:
    return route(service.judge, payload)


@router.post("/api/attribute")
def attribute(payload: AttributeRequest) -> JSONResponse:
    return route(service.attribute, payload)


@router.post("/api/cluster")
def cluster(payload: ClusterRequest) -> JSONResponse:
    return route(service.cluster, payload)


@router.post("/api/check")
def check(payload: CheckRequest) -> JSONResponse:
    return route(service.check, payload)


@router.post("/api/run_chain")
def run_chain(payload: RunChainRequest) -> JSONResponse:
    return route(service.run_chain, payload)


@router.post("/api/batch_run")
def batch_run(payload: BatchRunRequest) -> JSONResponse:
    return route(service.batch_run, payload)


@router.post("/api/batch_start")
def batch_start(payload: BatchStartRequest) -> JSONResponse:
    return route(batch_jobs.start_batch, payload)


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
