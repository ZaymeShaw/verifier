"""RealLive 受控传输边界。

项目只能通过 LiveTransport 发出真实请求；LiveExchange 由此处自动生成。
"""
from __future__ import annotations

import copy
import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .schema import LiveExchange, now_iso


_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key", "api-key"}


def _redact_headers(headers: Dict[str, Any] | None) -> Dict[str, Any]:
    return {
        str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_HEADERS else value
        for key, value in dict(headers or {}).items()
    }


def _decode_body(payload: bytes) -> Any:
    text = payload.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


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
    ) -> LiveResponseView:
        return self.request(
            "GET", url, headers=headers, timeout=timeout,
            carries_live_request=carries_live_request,
            contributes_raw_response=contributes_raw_response,
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
    ) -> LiveResponseView:
        return self.request(
            "POST", url, json_body=json_body, headers=headers, timeout=timeout,
            carries_live_request=carries_live_request,
            contributes_raw_response=contributes_raw_response,
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
        try:
            request = urllib.request.Request(url, data=body, headers=actual_headers, method=method)
            with urllib.request.urlopen(request, timeout=float(timeout)) as response:
                status_code = int(getattr(response, "status", response.getcode()))
                response_headers = dict(response.headers.items()) if getattr(response, "headers", None) else {}
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
        if error:
            raise urllib.error.URLError(error)
        return view


def validate_real_transport(transport: LiveTransport, request: Any) -> None:
    """校验成功 RealLive 的最小真实性不变量。"""
    exchanges = transport.exchanges
    request_exchanges = [item for item in exchanges if item.carries_live_request]
    if not request_exchanges:
        raise RuntimeError("RealLive missing carries_live_request exchange")
    if not any(item.request == request for item in request_exchanges):
        raise RuntimeError("RealLive wire request does not match REQUEST_SCHEMA payload")
    response_exchanges = [
        item for item in exchanges
        if item.contributes_raw_response and item.error is None and item.response is not None
    ]
    if not response_exchanges:
        raise RuntimeError("RealLive missing contributes_raw_response exchange")
