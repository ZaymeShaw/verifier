from __future__ import annotations

import json
import re
import urllib.error
from typing import Any, Dict
from urllib.parse import urlsplit

from impl.core.capability_store import ALLOWED_RESPONSE_MODES
from impl.core.config import ROOT
from impl.core.config_bootstrap import effective_environment_snapshot
from impl.core.live_protocol import LiveServiceUnavailableError, RealServiceLive
from contextvars import ContextVar

from impl.core.live_transport import LiveForbiddenContentTypeError, LiveHTTPStatusError, LiveRecordedFailure, LiveTransport
from impl.core.schema import ExecutionTraceEvent, LiveRequest, ProjectSpec
from impl.projects.llm_probe_loop import from_trace as from_trace_turn
from impl.projects.llm_probe_loop.capability import (
    capability_business_trace,
    capability_service,
    fresh_delivery_placeholders,
    resolve_capability,
)

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
# 每次投递重新生成的业务 Trace 关联（schema 字段，写回请求记录供采集与审计）
ASSOCIATION_KEY = "business_trace_association"
# 按 trace 复评：投递时取回的快照交给同一次投递的 project_fields，不写进请求记录、不采第二遍
_FROM_TRACE_SNAPSHOT: ContextVar[Any] = ContextVar("llm_probe_loop_from_trace_snapshot", default=None)


def _expand_header_value(value: str) -> str:
    """展开请求头里的 ${ENV}，值来自 .env + 进程环境（进程覆盖 .env）。"""

    snapshot = effective_environment_snapshot(ROOT / ".env")

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        got = snapshot.get(name)
        if not str(got or "").strip():
            raise ValueError(f"请求头引用的环境变量 {name} 未设置")
        return str(got)

    return _ENV_PLACEHOLDER.sub(_replace, value)


def _merge_headers(request: Dict[str, Any], service: Dict[str, Any] | None) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    if isinstance(service, dict):
        for key, value in dict(service.get("headers") or {}).items():
            merged[str(key)] = str(value)
    for key, value in dict(request.get("headers") or {}).items():
        merged[str(key)] = str(value)
    return {key: _expand_header_value(value) for key, value in merged.items()}


def application_boundary_for(response_mode: str) -> Dict[str, Any]:
    """json：纯非流式。sse_last_frame：伪流式（最后一帧全量），只评最后一帧。"""
    if response_mode == "sse_last_frame":
        return {"scope": "sse_last_frame_http_llm_probe", "streaming": "sse_last_frame"}
    return {"scope": "non_streaming_http_llm_probe", "streaming": False}


def _stringify(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)


def resolve_http(request: Dict[str, Any], spec: ProjectSpec) -> tuple[str, str, Dict[str, str], Dict[str, Any], float, str]:
    if not isinstance(request, dict):
        raise ValueError("llm_probe request must be an object")
    body = request.get("body")
    if not isinstance(body, dict):
        raise ValueError("llm_probe request.body must be a JSON object")
    url = str(request.get("url") or "").strip()
    raw_method = request.get("method")
    method = str(raw_method).strip().upper() if raw_method else ""
    primary = spec.require_service("primary")
    timeout = float(primary["timeout_seconds"])
    # 信封显式 response_mode 优先；否则由 capability service 声明；默认非流式 JSON。
    response_mode = str(request.get("response_mode") or "").strip().lower()
    ref = str(request.get("capability_ref") or "").strip()
    service: Dict[str, Any] | None = None
    if ref:
        # capability 预设自包含端点配置（资料管理页维护的 service 块），与项目注册表解耦；
        # url 显式与否不改变 timeout/method 来源。
        service = capability_service(ref)
        if not url:
            url = str(service["url"]).strip()
        if not method:
            method = str(service.get("method") or "").upper()
        timeout = float(service.get("timeout_seconds") or timeout)
        if not response_mode:
            response_mode = str(service.get("response_mode") or "").strip().lower()
        trace_config = capability_business_trace(ref)
        if trace_config:
            # 配置错误必须在发业务请求前失败；运行期关联 / 采集错误则固化进快照（评测时取不到即运行失败）。
            from impl.projects.llm_probe_loop.business_trace import validate_selection

            validate_selection(trace_config)
    response_mode = response_mode or "json"
    if response_mode not in ALLOWED_RESPONSE_MODES:
        raise ValueError(f"llm_probe response_mode 只支持 {'/'.join(ALLOWED_RESPONSE_MODES)}，收到 {response_mode}")
    if not url:
        raise ValueError("llm_probe request 需要 url 或 capability_ref")
    if not method:
        method = str(primary["method"]).upper()
    headers = _merge_headers(request, service)
    scheme = urlsplit(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"llm_probe 只允许 http/https URL，收到 scheme {scheme or '(空)'}")
    if method not in {"POST", "PUT", "PATCH"}:
        raise ValueError(f"llm_probe 只发 JSON 写方法，收到 {method}")
    resolve_capability(request)
    return url, method, headers, body, timeout, response_mode


def _reject_streaming(transport: LiveTransport) -> None:
    for exchange in transport.exchanges:
        headers = {
            str(key).lower(): str(value)
            for key, value in dict(exchange.response_headers or {}).items()
        }
        content_type = headers.get("content-type") or ""
        if "text/event-stream" in content_type:
            raise RuntimeError("llm_probe 拒绝流式响应 text/event-stream")


class LlmProbeLive(RealServiceLive):
    """按 case 信封发 HTTP，响应收成字符串；sse_last_frame 模式取流的最后一帧。"""

    @staticmethod
    def _propagate(payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, str]:
        """trace 源要求随请求发的头（Langfuse W3C 方式的 traceparent）每次投递重新生成，记进 business_trace_association
        供采集取用；多轮沿用信封时上一次的关联被覆盖，不混进 case 自己的请求头（spec/alg/business-trace-langfuse.md §2.2）。"""
        payload.pop(ASSOCIATION_KEY, None)
        ref = str(payload.get("capability_ref") or "").strip()
        trace_config = capability_business_trace(ref) if ref else None
        if not trace_config:
            return headers
        from impl.projects.llm_probe_loop.business_trace import propagation_headers

        sent = propagation_headers(trace_config)
        clash = sorted(key for key in sent if key.lower() in {k.lower() for k in headers})
        if clash:
            raise ValueError(f"请求头 {', '.join(clash)} 由评测方按 trace 源自动生成，service 和 case 里不要写")
        if sent:
            payload[ASSOCIATION_KEY] = {"headers": sent}
        return {**headers, **sent}

    def case_provides_output(self, request: Any) -> bool:
        """带 from_trace 的 case 按 trace 复评：不调业务（spec/alg/trace-replay.md §2）。"""
        return isinstance(request, dict) and bool(from_trace_turn.trace_id_of(request))

    def deliver_provided(self, request: LiveRequest) -> Any:
        """按 trace 复评：按 trace id 取回这一轮，拼成与现场同形的运行记录（spec/alg/trace-replay.md §4、§5）。"""
        payload = request.normalized_request if isinstance(request.normalized_request, dict) else {}
        got = from_trace_turn.take(payload)
        failure = str(got.get("failure") or "")
        if failure:
            # 与现场非 2xx 同属被测系统调用失败
            code = failure.removeprefix("HTTP ").strip()
            raise LiveHTTPStatusError(int(code), None) if failure.startswith("HTTP ") and code.isdigit() else LiveRecordedFailure(failure)
        if got.get("error"):
            raise RuntimeError(f"按 trace 复评取不到这一轮：{got['error']}")
        payload["body"] = from_trace_turn.request_body(got["request"])
        payload[ASSOCIATION_KEY] = {"from_trace": {"trace_id": from_trace_turn.trace_id_of(payload),
                                                   "delivered_from": got.get("delivered_from") or ""}}
        _FROM_TRACE_SNAPSHOT.set(got.get("snapshot"))
        return [got["delivered"]]

    def deliver_real(self, request: Any, transport: LiveTransport) -> LiveTransport:
        payload = request if isinstance(request, dict) else {}
        if isinstance(payload.get("body"), (dict, list)):
            # 用例里写 "{session_id}" 表示"每次执行都是新的业务会话"，发送时才落成真实 id；
            # 多轮走 Session 路径时翻译函数已填具体会话身份，这里不会再碰到占位符。
            payload["body"] = fresh_delivery_placeholders(payload["body"])
        url, method, headers, body, timeout, response_mode = resolve_http(payload, self.spec)
        headers = self._propagate(payload, headers)
        if isinstance(request, dict):
            # 回写解析结果，让 execution trace 和 judge 拿到真实 URL/method/响应模式。
            request["url"] = url
            request["method"] = method
            request["response_mode"] = response_mode
        last_frame = response_mode == "sse_last_frame"
        try:
            transport.request(
                method,
                url,
                json_body=body,
                headers=headers,
                timeout=timeout,
                carries_live_request=True,
                contributes_raw_response=True,
                forbid_content_types=() if last_frame else ("text/event-stream",),
                sse_last_frame=last_frame,
            )
        except LiveHTTPStatusError:
            raise
        except LiveForbiddenContentTypeError as exc:
            raise RuntimeError(f"llm_probe 拒绝流式响应 {exc.content_type}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            ref = str(payload.get("capability_ref") or "").strip()
            hint = str(capability_service(ref).get("start_hint") or "").strip() if ref else ""
            raise LiveServiceUnavailableError(f"llm_probe target unavailable: {exc}" + (f"；{hint}" if hint else "")) from exc
        if not last_frame:
            _reject_streaming(transport)
        return transport

    def extract_output(self, raw_response: list[Any]) -> Dict[str, Any]:
        payload = raw_response[0] if raw_response else None
        return {"output_text": _stringify(payload)}

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        payload = request.normalized_request if isinstance(request, LiveRequest) else request
        payload = payload if isinstance(payload, dict) else {}
        recorded = (payload.get(ASSOCIATION_KEY) or {}).get("from_trace") if isinstance(payload.get(ASSOCIATION_KEY), dict) else None
        if recorded:
            # 交付取自业务 trace 的记录，不是评测方实际收到的
            return {"scope": "trace_record", "streaming": False, "delivered_from": recorded.get("delivered_from") or ""}
        return application_boundary_for(str(payload.get("response_mode") or "json"))

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        payload = request.normalized_request if isinstance(request, LiveRequest) else request
        payload = payload if isinstance(payload, dict) else {}
        fields = {
            "capability_ref": payload.get("capability_ref") or "",
            "capability": payload.get("capability") or "",
            "show_schema": payload.get("show_schema"),
        }
        ref = str(payload.get("capability_ref") or "").strip()
        trace_config = capability_business_trace(ref) if ref else None
        if self.case_provides_output(payload):
            snapshot = _FROM_TRACE_SNAPSHOT.get()
            _FROM_TRACE_SNAPSHOT.set(None)
            if trace_config and snapshot is not None:
                fields["business_trace"] = snapshot
            return fields
        if trace_config:
            from impl.projects.llm_probe_loop.business_trace import collect

            response = raw_response[0] if isinstance(raw_response, list) and raw_response else raw_response
            fields["business_trace"] = collect(trace_config, request=payload, response=response)
        return fields

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> list:
        payload = request.normalized_request if isinstance(request, LiveRequest) else request
        payload = payload if isinstance(payload, dict) else {}
        return [
            ExecutionTraceEvent(
                stage="request_normalization",
                status="ok" if isinstance(payload.get("body"), dict) else "failed",
                evidence={"capability_ref": payload.get("capability_ref") or ""},
            ),
            ExecutionTraceEvent(
                stage="http_call",
                status="ok" if raw_response else "failed",
                evidence={"url": payload.get("url") or "", "method": payload.get("method")},
            ),
            ExecutionTraceEvent(
                stage="output_stringify",
                status="ok" if str((extracted_output or {}).get("output_text") or "") else "suspicious",
                evidence={"output_chars": len(str((extracted_output or {}).get("output_text") or ""))},
            ),
        ]
