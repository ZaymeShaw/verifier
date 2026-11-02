from __future__ import annotations

import copy
import importlib
import inspect
import json
import os
import uuid
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from impl.core.live_transport import (
    LiveForbiddenContentTypeError,
    LiveHTTPStatusError,
    LiveResponseView,
    LiveSseReadError,
    LiveTransport,
    _redact_headers,
)
from impl.core.schema import LiveExchange, now_iso


def _encode_error(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, LiveHTTPStatusError):
        args = (exc.status_code, exc.response)
    elif isinstance(exc, LiveForbiddenContentTypeError):
        args = (exc.content_type,)
    else:
        args = exc.__reduce__()[1]
    return {
        "module": type(exc).__module__,
        "type": type(exc).__qualname__,
        "message": str(exc),
        "args": [
            (
                {"exception": _encode_error(arg)}
                if isinstance(arg, BaseException)
                else {"value": arg}
            )
            for arg in args
        ],
    }


def _decode_error(data: dict[str, Any]) -> BaseException:
    cls = importlib.import_module(data["module"])
    for name in data["type"].split("."):
        cls = getattr(cls, name)
    if not isinstance(cls, type) or not issubclass(cls, BaseException):
        raise TypeError(f"Invalid cassette exception: {data['type']}")
    args = [
        _decode_error(arg["exception"]) if "exception" in arg else arg["value"]
        for arg in data["args"]
    ]
    return cls(*args)


def _url_path(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _no_context(*args: Any, **kwargs: Any) -> str:
    return ""


class Cassette:
    def __init__(
        self,
        mode: str | None = None,
        directory: str | Path | None = None,
    ) -> None:
        self.mode = (
            mode if mode is not None else os.getenv("VERIFIER_CASSETTE", "off")
        )
        if self.mode not in {"off", "record", "replay"}:
            raise ValueError(f"Invalid VERIFIER_CASSETTE: {self.mode}")
        location = directory or os.getenv("VERIFIER_CASSETTE_DIR")
        if self.mode != "off" and not location:
            raise ValueError("VERIFIER_CASSETTE_DIR is required")
        self.directory = Path(location) if location else None
        self._originals: list[tuple[Any, str, Any]] = []
        self._rows: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(
            list
        )
        self._positions: dict[tuple[str, ...], int] = defaultdict(int)
        self._counts: dict[str, int] = defaultdict(int)
        self._failures: list[str] = []

    def _replace(self, owner: Any, name: str, value: Any) -> None:
        self._originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def install(self) -> Cassette:
        if self.mode == "off" or self._originals:
            return self
        self._rows.clear()
        self._positions.clear()
        self._counts.clear()
        self._failures.clear()
        for kind in ("llm", "live"):
            path = self.directory / f"{kind}.jsonl"
            if self.mode == "record":
                self.directory.mkdir(parents=True, exist_ok=True)
                path.touch(exist_ok=True)
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self._counts[kind] = max(self._counts[kind], row["seq"])
                fields = (
                    ("role", "stage")
                    if kind == "llm"
                    else ("method", "url_path")
                )
                self._rows[(kind, *(row[field] for field in fields))].append(
                    row
                )
        from impl.core import context_store
        from impl.core.llm_client import LlmClient

        self._replace(
            LlmClient,
            "complete_json",
            self._llm_wrapper(LlmClient.complete_json),
        )
        self._replace(
            LiveTransport,
            "request",
            self._live_wrapper(LiveTransport.request),
        )
        if self.mode == "replay":
            self._replace(context_store, "save_context", _no_context)
        return self

    def uninstall(self) -> None:
        for owner, name, value in reversed(self._originals):
            setattr(owner, name, value)
        self._originals.clear()

    def assert_exhausted(self) -> None:
        if self.mode != "replay":
            return
        remaining = {
            key: len(rows) - self._positions[key]
            for key, rows in self._rows.items()
            if len(rows) != self._positions[key]
        }
        if self._failures or remaining:
            raise RuntimeError(
                f"Cassette mismatch: failures={self._failures}; "
                f"remaining={remaining}"
            )

    def _take(self, key: tuple[str, ...]) -> dict[str, Any]:
        index = self._positions[key]
        rows = self._rows.get(key, [])
        if index >= len(rows):
            message = f"Cassette exhausted for {key}, call {index + 1}"
            self._failures.append(message)
            raise RuntimeError(message)
        self._positions[key] += 1
        return copy.deepcopy(rows[index])

    def _append(self, kind: str, row: dict[str, Any]) -> None:
        self._counts[kind] += 1
        row["seq"] = self._counts[kind]
        with (self.directory / f"{kind}.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            )

    def _llm_wrapper(self, original: Callable[..., Any]) -> Callable[..., Any]:
        cassette = self
        signature = inspect.signature(original)

        def wrapper(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
            values = signature.bind(self, *args, **kwargs).arguments
            role = getattr(self, "_caller", "")
            stage = values.get("stage", "")
            if cassette.mode == "replay":
                row = cassette._take(("llm", role, stage))
                if row["error"] is not None:
                    raise _decode_error(row["error"])
                return row["response"]
            row = {
                "role": role,
                "stage": stage,
                "system": values["system"],
                "user": values["user"],
                "response": None,
                "error": None,
            }
            try:
                response = original(self, *args, **kwargs)
            except Exception as exc:
                row["error"] = _encode_error(exc)
                cassette._append("llm", row)
                raise
            row["response"] = response
            cassette._append("llm", row)
            return response

        return wrapper

    def _live_wrapper(
        self, original: Callable[..., Any]
    ) -> Callable[..., Any]:
        cassette = self
        signature = inspect.signature(original)

        def wrapper(
            self: LiveTransport, *args: Any, **kwargs: Any
        ) -> LiveResponseView:
            values = signature.bind(self, *args, **kwargs).arguments
            method = str(values["method"] or "GET").upper()
            url = str(values["url"])
            key = ("live", method, _url_path(url))
            if cassette.mode == "replay":
                if self.sealed:
                    raise RuntimeError("LiveTransport is sealed")
                row = cassette._take(key)
                if row["exchange"] is not None:
                    data = row["exchange"]
                    headers = {}
                    if values.get("json_body") is not None:
                        headers["Content-Type"] = "application/json"
                    headers.update(values.get("headers") or {})
                    data.update(
                        exchange_id=f"live-exchange-{uuid.uuid4()}",
                        sequence=len(self._exchanges),
                        method=method,
                        url=url,
                        request=copy.deepcopy(values.get("json_body")),
                        request_headers=_redact_headers(headers),
                        carries_live_request=bool(
                            values.get("carries_live_request", False)
                        ),
                        contributes_raw_response=bool(
                            values.get("contributes_raw_response", False)
                        ),
                        started_at=now_iso(),
                        finished_at=now_iso(),
                    )
                    exchange = LiveExchange(**data)
                    self._exchanges.append(exchange)
                if row["raised"] != "none":
                    raise _decode_error(row["exception"])
                return LiveResponseView(
                    exchange.exchange_id,
                    row["status_code"],
                    row["response"],
                    row["error"],
                )
            row = {
                "method": method,
                "url_path": key[2],
                "request": copy.deepcopy(values.get("json_body")),
                "status_code": None,
                "response": None,
                "error": None,
                "raised": "none",
                "exception": None,
                "exchange": None,
            }
            count = len(self._exchanges)
            try:
                return original(self, *args, **kwargs)
            except Exception as exc:
                import urllib.error

                kinds = (
                    (LiveHTTPStatusError, "http_status"),
                    (LiveForbiddenContentTypeError, "forbidden_content_type"),
                    (LiveSseReadError, "sse_read_error"),
                    (urllib.error.URLError, "url_error"),
                )
                row["raised"] = next(
                    (name for cls, name in kinds if isinstance(exc, cls)),
                    "exception",
                )
                row["exception"] = _encode_error(exc)
                raise
            finally:
                if len(self._exchanges) > count:
                    row["exchange"] = asdict(self._exchanges[-1])
                    for field in ("status_code", "response", "error"):
                        row[field] = row["exchange"][field]
                cassette._append("live", row)

        return wrapper


_current: Cassette | None = None


def install() -> Cassette:
    global _current
    if _current is None:
        _current = Cassette().install()
    return _current


def uninstall() -> None:
    global _current
    if _current is not None:
        _current.uninstall()
        _current = None


def assert_exhausted() -> None:
    if _current is not None:
        _current.assert_exhausted()
