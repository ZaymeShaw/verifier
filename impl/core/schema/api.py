from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .attribute import AttributeResult
from .batch import BatchRunResult
from .check import CheckReport
from .cluster import ClusterSummary
from .frontend import FrontendViewModel
from .judge import JudgeResult
from .mock import MockDataset, SingleTurnCase
from .project import ProjectAnalysis
from .table import CasePoolTable, TraceTableRow
from .trace import RunTrace


@dataclass
class ApiEnvelope:
    endpoint: str
    input_schema: str
    output_schema: str
    data: Any


@dataclass
class MockCasesResponse:
    project_id: str
    cases: List[SingleTurnCase]


@dataclass
class MockDatasetsResponse:
    project_id: str
    datasets: List[MockDataset]


@dataclass
class MockBuildResponse:
    # Mock 层：mock agent build_intent/build_interaction 的统一响应。
    project_id: str
    case: Dict[str, Any]


@dataclass
class RunChainResponse:
    trace: RunTrace
    judge: JudgeResult
    attribute: Optional[AttributeResult] = None
    cluster: Optional[ClusterSummary] = None
    check: Optional[CheckReport] = None
    frontend_view: Optional[FrontendViewModel] = None
    table_row: Optional[TraceTableRow] = None


@dataclass
class CasePoolsResponse:
    project_id: str
    pools: List[Dict[str, Any]]


@dataclass
class CasePoolSaveResponse:
    id: str
    name: str
    cases: List[Dict[str, Any]]


API_ENDPOINT_SCHEMAS = {
    "/api/analysis": {"input": "ProjectRequest", "output": "impl.core.schema.project.ProjectAnalysis"},
    "/api/live_run": {"input": "LiveRunRequest", "output": "impl.core.schema.trace.RunTrace"},
    "/api/mock_cases": {"input": "ProjectRequest", "output": "impl.core.schema.api.MockCasesResponse"},
    "/api/mock_datasets": {"input": "ProjectRequest", "output": "impl.core.schema.api.MockDatasetsResponse"},
    "/api/mock/build_intent": {"input": "MockBuildIntentRequest", "output": "impl.core.schema.api.MockBuildResponse"},
    "/api/mock/build_interaction": {"input": "MockBuildInteractionRequest", "output": "impl.core.schema.api.MockBuildResponse"},
    "/api/judge": {"input": "JudgeRequest", "output": "impl.core.schema.judge.JudgeResult"},
    "/api/attribute": {"input": "AttributeRequest", "output": "impl.core.schema.attribute.AttributeResult"},
    "/api/cluster": {"input": "ClusterRequest", "output": "impl.core.schema.cluster.ClusterSummary"},
    "/api/check": {"input": "CheckRequest", "output": "impl.core.schema.check.CheckReport"},
    "/api/frontend_view": {"input": "FrontendViewRequest", "output": "impl.core.schema.frontend.FrontendViewModel"},
    "/api/run_chain": {"input": "RunChainRequest", "output": "impl.core.schema.api.RunChainResponse"},
    "/api/batch_run": {"input": "BatchRunRequest", "output": "impl.core.schema.batch.BatchRunResult"},
    "/api/trace": {"input": "TraceRequest", "output": "impl.core.schema.trace.RunTrace"},
    "/api/table": {"input": "TableRequest", "output": "impl.core.schema.table.TraceTableRow | impl.core.schema.table.CasePoolTable"},
    "/api/case_pools": {"input": "ProjectRequest", "output": "impl.core.schema.api.CasePoolsResponse"},
    "/api/case_pool/save": {"input": "CasePoolSaveRequest", "output": "impl.core.schema.api.CasePoolSaveResponse"},
}
