"""llm_probe live schema：curl 信封请求 + 字符串化响应。"""
from __future__ import annotations

from typing import Any

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from impl.projects.llm_probe_loop.capability import resolve_capability
from impl.projects.llm_probe_loop.schema import LlmProbeExtractOutput, LlmProbeRequest

REQUIRED_INPUT_FIELDS = ["body"]

REQUEST_SCHEMA = LlmProbeRequest
EXTRACT_OUTPUT_SCHEMA = LlmProbeExtractOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)


def _from_trace_errors(ref: str) -> list[str]:
    """场景必须选了 trace 源，且这个 trace 源能按 trace 复评。"""
    from impl.projects.llm_probe_loop.business_trace import supports_from_trace
    from impl.projects.llm_probe_loop.capability import capability_business_trace_selection

    selection = capability_business_trace_selection(ref)
    if not selection:
        return [f"场景 {ref} 没有选 trace 源，不能按 trace 复评"]
    if not supports_from_trace(selection):
        return [f"场景 {ref} 的 trace 源 {selection['source']} 不支持按 trace 复评"]
    return []


class _ProbeLiveSchemaCheck(LiveSchemaCheck):
    def request_errors(self, data: Any) -> list[str]:
        errors = list(super().request_errors(data))
        if not isinstance(data, dict):
            return errors or ["request 不是 object"]
        from_trace = data.get("from_trace")
        body = data.get("body")
        if from_trace:
            # 按 trace 复评（spec/alg/trace-replay.md §2）：与 body 二选一，只写 trace_id
            if body:
                errors.append("body 与 from_trace 只能二选一")
            if not isinstance(from_trace, dict) or set(from_trace) != {"trace_id"} or not str(from_trace.get("trace_id") or "").strip():
                errors.append("from_trace 只写 {\"trace_id\": \"<非空 trace id>\"}")
        elif not isinstance(body, dict) or not body:
            errors.append("body 必须是非空 JSON object（或改用 from_trace 按 trace 复评）")
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
        if from_trace and ref and not errors:
            errors.extend(_from_trace_errors(ref))
        return errors

    def request(self, data: Any) -> bool:
        return not self.request_errors(data)


check = _ProbeLiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA)
