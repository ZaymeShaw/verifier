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


class CasePoolSaveRequest(ApiRequest):
    name: Optional[str] = None
    cases: List[Dict[str, Any]] = Field(default_factory=list)


class CasePoolLoadRequest(ApiRequest):
    id: Optional[str] = None


class CasePoolDeleteRequest(ApiRequest):
    id: Optional[str] = None


class JudgeRequest(ApiRequest):
    trace: Any = None
    user_intent: Optional[str] = None


class AttributeRequest(ApiRequest):
    trace: Any = None
    judge: Any = None


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
    user_intent: Optional[str] = None


class BatchRunRequest(ApiRequest):
    cases: List[Dict[str, Any]] = Field(default_factory=list)
    user_intent: Optional[str] = None
    concurrency: Optional[int] = None


class BatchStartRequest(BatchRunRequest):
    pass


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


class ContextAnalyzeRequest(ApiRequest):
    caller: str = ""
    analysis_type: str = "redundancy"
    sample_size: int = 3


ApiPayload = ApiRequest
