"""llm_probe live schema：curl 信封请求 + 字符串化响应。"""
from __future__ import annotations

from typing import Any

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from impl.projects.llm_probe.capability import resolve_capability
from impl.projects.llm_probe.schema import LlmProbeExtractOutput, LlmProbeRequest

REQUIRED_INPUT_FIELDS = ["body"]

REQUEST_SCHEMA = LlmProbeRequest
EXTRACT_OUTPUT_SCHEMA = LlmProbeExtractOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)


class _ProbeLiveSchemaCheck(LiveSchemaCheck):
    def request_errors(self, data: Any) -> list[str]:
        errors = list(super().request_errors(data))
        if not isinstance(data, dict):
            return errors or ["request 不是 object"]
        if not isinstance(data.get("body"), dict):
            errors.append("body 必须是 JSON object")
        capability = str(data.get("capability") or "").strip()
        ref = str(data.get("capability_ref") or "").strip()
        url = str(data.get("url") or "").strip()
        if not capability and not ref:
            errors.append("需要 capability 或 capability_ref")
        if not url and not ref:
            errors.append("需要 url 或 capability_ref")
        if not capability and ref:
            try:
                resolve_capability(data)
            except ValueError as exc:
                errors.append(str(exc))
        return errors

    def request(self, data: Any) -> bool:
        return not self.request_errors(data)


check = _ProbeLiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA)
