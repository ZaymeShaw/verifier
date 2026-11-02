from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: Optional[str] = None
    project_id: Optional[str] = None

    @property
    def project_name(self) -> str:
        return self.project or self.project_id or ""

    def as_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class ProjectRequest(ApiRequest):
    pass


class LiveRunRequest(ApiRequest):
    input: Any = None
    case: Optional[Dict[str, Any]] = None


class MockCasesRequest(ProjectRequest):
    count: int = Field(default=1, ge=1, le=500)


class MockDatasetsRequest(ProjectRequest):
    count: int = Field(default=1, ge=1, le=500)


class MockBuildIntentRequest(ApiRequest):
    scenario: Optional[str] = None
    requested_intent: Optional[str] = None
    intent_labels: List[str] = Field(default_factory=list)
    template: Optional[Dict[str, Any]] = None
    required_input_fields: List[str] = Field(default_factory=list)


class CasePoolsRequest(ProjectRequest):
    pass


class CapabilityListRequest(ProjectRequest):
    pass


class EvalAxesTypesRequest(ProjectRequest):
    pass


class EvalAxesRunRequest(ApiRequest):
    trace: Any = None
    run_id: Optional[str] = None


class BusinessTraceProvidersRequest(ProjectRequest):
    pass


class BusinessTraceCheckRequest(ApiRequest):
    business_trace: Optional[Dict[str, Any]] = None


class KnowledgeSourcesRequest(ProjectRequest):
    pass


class KnowledgeSourceSaveRequest(ApiRequest):
    name: Optional[str] = None
    entry: Optional[Dict[str, Any]] = None


class KnowledgeSourceNameRequest(ApiRequest):
    name: Optional[str] = None


class MaterialsListRequest(ProjectRequest):
    pass


class MaterialUploadRequest(ApiRequest):
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None


class MaterialGetRequest(ApiRequest):
    id: Optional[str] = None


class MaterialAssetViewRequest(ApiRequest):
    asset_id: Optional[str] = None


class MaterialAssetFileRequest(ApiRequest):
    asset_id: Optional[str] = None
    scope: Optional[str] = None
    path: Optional[str] = None


class MaterialDeleteRequest(ApiRequest):
    id: Optional[str] = None


class CapabilitySaveRequest(ApiRequest):
    name: Optional[str] = None
    entry: Optional[Dict[str, Any]] = None


class CapabilityDeleteRequest(ApiRequest):
    name: Optional[str] = None


class CasePoolSaveRequest(ApiRequest):
    name: Optional[str] = None
    cases: List[Dict[str, Any]] = Field(default_factory=list)


class CasePoolLoadRequest(ApiRequest):
    id: Optional[str] = None


class CasePoolDeleteRequest(ApiRequest):
    id: Optional[str] = None


class JudgeRequest(ApiRequest):
    trace: Any = None


class AttributeRequest(ApiRequest):
    trace: Any = None
    judge: Any = None
    manual_override: Optional[bool] = None


class ClusterRequest(ApiRequest):
    attributes: List[Any] = Field(default_factory=list)


class CheckRequest(ApiRequest):
    trace: Any = None
    judge: Any = None
    attribute: Any = None
    cluster: Any = None


class FrontendViewRequest(ApiRequest):
    trace: Any = None
    judge: Any = None
    attribute: Any = None
    attributes: List[Any] = Field(default_factory=list)
    cluster: Any = None
    check: Any = None


class RunChainRequest(ApiRequest):
    input: Any = None
    case: Optional[Dict[str, Any]] = None


class BatchRunRequest(ApiRequest):
    cases: List[Dict[str, Any]] = Field(default_factory=list)
    concurrency: Optional[int] = None


class BatchStartRequest(BatchRunRequest):
    pool_indexes: Optional[List[int]] = None


class RunWorkspaceReplaceRequest(ProjectRequest):
    cases: List[Dict[str, Any]]
    source: str = "uploaded_or_manual"


class RunWorkspaceClearRequest(ProjectRequest):
    keep_cases: bool


class RunWorkspaceAttributeRequest(ProjectRequest):
    request_key: str


class ClusteringSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pool_index: int = Field(ge=0)
    request_key: Optional[str] = None


class AxesClusteringStateRequest(ProjectRequest):
    selections: List[ClusteringSelection] = Field(min_length=1)


class AxesClusteringCriteriaRequest(ProjectRequest):
    criteria: str = Field(min_length=1, max_length=8000)
    expected_version: int = Field(ge=1)


class AxesClusteringStartRequest(AxesClusteringCriteriaRequest):
    selections: List[ClusteringSelection] = Field(min_length=1)


class BatchStatusRequest(ApiRequest):
    model_config = ConfigDict(extra="forbid")

    job_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class TraceRequest(ApiRequest):
    trace: Any = None
    run: Optional[Dict[str, Any]] = None
    input: Any = None


class TableRequest(ApiRequest):
    run: Optional[Dict[str, Any]] = None
    runs: List[Dict[str, Any]] = Field(default_factory=list)
    trace: Any = None
    judge: Any = None
    attribute: Any = None
    frontend_view: Any = None
    view: Any = None
    check: Any = None
    case_context: Optional[Dict[str, Any]] = None


class SessionOpenRequest(ApiRequest):
    """spec/mock/protocol.md 5.1 `session open`。"""

    mode: str = "text"
    budget: Dict[str, Any] = Field(default_factory=dict)
    seed_prefix: List[Dict[str, Any]] = Field(default_factory=list)
    seed_mode: Optional[str] = None
    pool: str = ""
    run_id: str = ""
    scenario: str = ""


class SessionSendRequest(ApiRequest):
    session_id: str
    message: Dict[str, Any]
    tokens: int = 0


class SessionIntentRequest(ApiRequest):
    session_id: str
    user_intent: str
    user_context: Dict[str, Any] = Field(default_factory=dict)
    source: str = "seeded"


class SessionCloseRequest(ApiRequest):
    session_id: str
    stop_reason: str


class SessionListRequest(ApiRequest):
    run_id: str = ""
    include_exports: bool = True


class SessionGetRequest(ApiRequest):
    session_id: str


class SessionJudgeRequest(ApiRequest):
    session_id: str


class LedgerAddRequest(ApiRequest):
    signature: str
    session_id: str = ""
    trigger_summary: str = ""
    realism: str = "medium"
    harness_verdict: str
    judge_verdict: Optional[str] = None
    protocol_fuzz: bool = False
    run_id: str = ""
    notes: str = ""


class LedgerQueryRequest(ApiRequest):
    category: Optional[str] = None
    signature: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None


class ExplorationSaveRequest(ApiRequest):
    run_id: str
    direction: Dict[str, Any]


class ExplorationReportRequest(ApiRequest):
    run_id: str
    report: Dict[str, Any]


class ExplorationGetRequest(ApiRequest):
    run_id: str


class ExplorationListRequest(ApiRequest):
    pass


class ContextAnalyzeRequest(ApiRequest):
    caller: str = ""
    analysis_type: str = "redundancy"
    sample_size: int = 3


ApiPayload = ApiRequest
