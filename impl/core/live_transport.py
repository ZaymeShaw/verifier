"""RealLive 受控传输边界。

项目只能通过 LiveTransport 发出真实请求；LiveExchange 由此处自动生成。
"""
from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .schema import LiveExchange, now_iso


_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key", "api-key"}

# sse_last_frame 有界读取上限：伪流式一帧全量远小于此；真流式会先撞上限而不是挂死。
SSE_MAX_BYTES = 4_000_000
_SSE_READ_CHUNK = 65_536


def _redact_headers(headers: Dict[str, Any] | None) -> Dict[str, Any]:
    return {
        str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_HEADERS else value
        for key, value in dict(headers or {}).items()
    }


def _decode_body(payload: bytes) -> Any:
    """JSON body 解析为结构；非 JSON 保留原始文本，不得改写成 dict 包装。"""
    text = payload.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _decode_http_error_body(exc: urllib.error.HTTPError) -> Any:
    """Best-effort decode without masking the original HTTP failure."""
    if exc.fp is None:
        return None
    try:
        return _decode_body(exc.read())
    except (AttributeError, KeyError, OSError):
        return None


@dataclass(frozen=True)
class LiveResponseView:
    """供项目继续编排下一次调用的只读真实响应视图。"""

    exchange_id: str
    status_code: Optional[int]
    response: Any
    error: Optional[str] = None


class LiveForbiddenContentTypeError(RuntimeError):
    """响应 Content-Type 命中禁用列表（如流式 SSE），在读取 body 前拒绝。"""

    def __init__(self, content_type: str):
        self.content_type = str(content_type)
        super().__init__(f"forbidden content-type: {self.content_type}")


class LiveSseReadError(RuntimeError):
    """声明了 sse_last_frame 但流读取超限或没有数据帧。"""


def _read_bounded(response: Any, timeout: float, max_bytes: int) -> bytes:
    """按字节与总时长上限读流；真流式（持续吐帧不结束）会撞上限报错而不是挂死。"""
    started = time.monotonic()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(_SSE_READ_CHUNK)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise LiveSseReadError(
                f"sse_last_frame 流超过 {max_bytes} 字节仍未结束；该接口更像增量流式，不适用最后一帧模式"
            )
        if time.monotonic() - started > float(timeout):
            raise LiveSseReadError(
                f"sse_last_frame 流超过 {timeout} 秒仍未结束；该接口更像增量流式，不适用最后一帧模式"
            )


def parse_sse_last_frame(text: str) -> Any:
    """SSE 文本取最后一个数据帧并 JSON 解析。

    帧以空行分隔；每帧内多条 `data:` 行按 SSE 规范以换行拼接；
    注释行（`:` 开头）与 `[DONE]` 哨兵跳过。没有数据帧则报错。
    """
    last_payload: Optional[str] = None
    for frame in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        data_lines: list[str] = []
        for line in frame.split("\n"):
            if line == "data":
                data_lines.append("")
            elif line.startswith("data:"):
                value = line[5:]
                data_lines.append(value[1:] if value.startswith(" ") else value)
        payload = "\n".join(data_lines).strip()
        if not payload or payload == "[DONE]":
            continue
        last_payload = payload
    if last_payload is None:
        raise LiveSseReadError("sse_last_frame 响应里没有可用的 data 帧")
    return _decode_body(last_payload.encode("utf-8"))


class LiveHTTPStatusError(urllib.error.URLError):
    """业务服务已响应，但以非 2xx 状态拒绝请求。"""

    def __init__(self, status_code: int, response: Any):
        self.status_code = int(status_code)
        self.response = copy.deepcopy(response)
        detail = json.dumps(response, ensure_ascii=False) if response is not None else ""
        super().__init__(f"HTTP {self.status_code}: {detail}".rstrip())

    def __str__(self) -> str:
        return str(self.reason)


class LiveTransport:
    """一轮 RealLive 独占的受控 transport；seal 后不可追加 Exchange。"""

    def __init__(self) -> None:
        self._exchanges: list[LiveExchange] = []
        self._sealed = False

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def exchanges(self) -> list[LiveExchange]:
        return copy.deepcopy(self._exchanges)

    def seal(self) -> None:
        self._sealed = True

    def raw_responses(self) -> list[Any]:
        if not self._sealed:
            raise RuntimeError("LiveTransport must be sealed before raw_response generation")
        return [
            copy.deepcopy(exchange.response)
            for exchange in self._exchanges
            if exchange.contributes_raw_response and exchange.error is None and exchange.response is not None
        ]

    def get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
        carries_live_request: bool = False,
        contributes_raw_response: bool = False,
        forbid_content_types: Optional[Iterable[str]] = None,
    ) -> LiveResponseView:
        return self.request(
            "GET", url, headers=headers, timeout=timeout,
            carries_live_request=carries_live_request,
            contributes_raw_response=contributes_raw_response,
            forbid_content_types=forbid_content_types,
        )

    def post(
        self,
        url: str,
        *,
        json_body: Any = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
        carries_live_request: bool = False,
        contributes_raw_response: bool = False,
        forbid_content_types: Optional[Iterable[str]] = None,
    ) -> LiveResponseView:
        return self.request(
            "POST", url, json_body=json_body, headers=headers, timeout=timeout,
            carries_live_request=carries_live_request,
            contributes_raw_response=contributes_raw_response,
            forbid_content_types=forbid_content_types,
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
        carries_live_request: bool = False,
        contributes_raw_response: bool = False,
        forbid_content_types: Optional[Iterable[str]] = None,
        sse_last_frame: bool = False,
    ) -> LiveResponseView:
        if self._sealed:
            raise RuntimeError("LiveTransport is sealed")
        method = str(method or "GET").upper()
        actual_headers = {"Content-Type": "application/json"} if json_body is not None else {}
        actual_headers.update(dict(headers or {}))
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8") if json_body is not None and method != "GET" else None
        started_at = now_iso()
        exchange_id = f"live-exchange-{uuid.uuid4()}"
        status_code: Optional[int] = None
        response_headers: Dict[str, Any] = {}
        response_payload: Any = None
        error: Optional[str] = None
        rejected_content_type: Optional[str] = None
        sse_read_error: Optional[str] = None
        forbidden_markers = [str(marker).lower() for marker in (forbid_content_types or ()) if str(marker).strip()]
        try:
            request = urllib.request.Request(url, data=body, headers=actual_headers, method=method)
            with urllib.request.urlopen(request, timeout=float(timeout)) as response:
                status_code = int(getattr(response, "status", response.getcode()))
                response_headers = dict(response.headers.items()) if getattr(response, "headers", None) else {}
                content_type = next(
                    (str(value).lower() for key, value in response_headers.items() if str(key).lower() == "content-type"),
                    "",
                )
                if sse_last_frame and "text/event-stream" in content_type:
                    # 声明了伪流式（最后一帧全量）：有界读完整个流，取最后一个 data 帧当响应。
                    try:
                        raw = _read_bounded(response, timeout, SSE_MAX_BYTES)
                        response_payload = parse_sse_last_frame(raw.decode("utf-8", errors="replace"))
                    except LiveSseReadError as exc:
                        sse_read_error = str(exc)
                        error = sse_read_error
                elif any(marker in content_type for marker in forbidden_markers):
                    # 在读取 body 之前拒绝流式/禁用类型，避免挂在无限 SSE 流上。
                    rejected_content_type = content_type
                    error = f"forbidden content-type (rejected before body read): {content_type}"
                else:
                    response_payload = _decode_body(response.read())
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            response_headers = dict(exc.headers.items()) if exc.headers else {}
            response_payload = _decode_http_error_body(exc)
            error = str(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = str(exc)
        exchange = LiveExchange(
            exchange_id=exchange_id,
            sequence=len(self._exchanges),
            transport="http",
            method=method,
            url=str(url),
            carries_live_request=bool(carries_live_request),
            contributes_raw_response=bool(contributes_raw_response),
            request_headers=_redact_headers(actual_headers),
            request=copy.deepcopy(json_body),
            status_code=status_code,
            response_headers=_redact_headers(response_headers),
            response=copy.deepcopy(response_payload),
            error=error,
            started_at=started_at,
            finished_at=now_iso(),
        )
        self._exchanges.append(exchange)
        view = LiveResponseView(exchange_id, status_code, copy.deepcopy(response_payload), error)
        if rejected_content_type is not None:
            raise LiveForbiddenContentTypeError(rejected_content_type)
        if sse_read_error is not None:
            raise LiveSseReadError(sse_read_error)
        if error:
            if status_code is not None:
                raise LiveHTTPStatusError(status_code, response_payload)
            raise urllib.error.URLError(error)
        return view


def declared_wire_body(request: Any) -> Any:
    """HTTP JSON body that RealLive must put on the wire.

    Flat REQUEST_SCHEMA projects send the whole payload. Envelope requests
    (url / headers / capability plus nested body) send only `body`.
    """
    if not isinstance(request, dict):
        return request
    nested = request.get("body")
    if not isinstance(nested, dict):
        return request
    markers = ("url", "method", "headers", "capability_ref", "capability", "show_schema", "response_mode")
    if any(key in request for key in markers):
        return nested
    return request


def validate_real_transport(transport: LiveTransport, request: Any) -> None:
    """校验成功 RealLive 的最小真实性不变量。"""
    exchanges = transport.exchanges
    request_exchanges = [item for item in exchanges if item.carries_live_request]
    if not request_exchanges:
        raise RuntimeError("RealLive missing carries_live_request exchange")
    declared = declared_wire_body(request)
    if not any(item.request == request or item.request == declared for item in request_exchanges):
        raise RuntimeError("RealLive wire request does not match REQUEST_SCHEMA payload")
    response_exchanges = [
        item for item in exchanges
        if item.contributes_raw_response and item.error is None and item.response is not None
    ]
    if not response_exchanges:
        raise RuntimeError("RealLive missing contributes_raw_response exchange")
