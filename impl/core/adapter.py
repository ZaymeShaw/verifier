from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict

from .schema import ProjectSpec, RunTrace


class ProjectAdapter(ABC):
    def __init__(self, spec: ProjectSpec):
        self.spec = spec

    @abstractmethod
    def build_request(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def call_or_prepare(self, request: Dict[str, Any]) -> Any:
        from .http_client import call_project_api

        return call_project_api(self.spec, request)

    def has_provided_output(self, input_data: Dict[str, Any], request: Dict[str, Any]) -> bool:
        return any(key in input_data for key in ("raw_response", "response", "output"))

    def provided_output_raw(self, input_data: Dict[str, Any], request: Dict[str, Any]) -> Any:
        for key in ("raw_response", "response", "output"):
            if key in input_data:
                return input_data[key]
        return {}

    @abstractmethod
    def extract_output(self, raw_response: Any) -> Dict[str, Any]:
        raise NotImplementedError

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def build_frontend_extensions(self, trace: RunTrace) -> Dict[str, Any]:
        return {"project_fields": trace.project_fields}

    def build_execution_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any, extracted_output: Dict[str, Any]) -> list[Dict[str, Any]]:
        return [
            {"stage": "adapter.build_request", "status": "ok", "evidence": "normalized request built"},
            {"stage": "project.call", "status": "ok", "evidence": "raw response captured"},
            {"stage": "adapter.extract_output", "status": "ok", "evidence": "generic extracted_output built"},
        ]

    def to_run_trace(self, input_data: Dict[str, Any], request: Dict[str, Any], raw_response: Any) -> RunTrace:
        extracted_output = self.extract_output(raw_response)
        return RunTrace(
            trace_id=str(uuid.uuid4()),
            project_id=self.spec.project_id,
            input=input_data,
            normalized_request=request,
            raw_response=raw_response,
            extracted_output=extracted_output,
            project_fields=self.project_fields(raw_response, extracted_output),
            runtime_logs=[],
            evidence_refs=[],
            execution_trace=self.build_execution_trace(input_data, request, raw_response, extracted_output),
            status="ok",
        )

    def normalize_judge_result(self, trace: RunTrace, judge_result):
        return judge_result

    def mock_response(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "mock": True,
            "request": request,
            "message": "Project service unavailable or mock mode requested.",
        }

    def build_mock_cases(self) -> list[Dict[str, Any]]:
        return []

    def build_mock_datasets(self) -> list[Dict[str, Any]]:
        return []


def ensure_jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)
