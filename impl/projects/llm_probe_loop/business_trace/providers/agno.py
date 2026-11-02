"""Agno AgentOS 业务 Trace provider。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from impl.core.config import ROOT
from impl.core.config_bootstrap import effective_environment_snapshot
from ..reader import KINDS

_ENV = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_TRACE_PAGE_SIZE = 20
_TRACE_MAX_PAGES = 10


class AgnoHttpError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def describe() -> dict[str, Any]:
    return {
        "provider": "agno",
        "title": "Agno AgentOS",
        "summary": "按 session_id + 本轮用户原话关联 Agno run（取最新一条），采集执行记录、会话及组件定义；可配置 sqlite_path 只读补充原始 span 属性。",
        "optional_config": {
            "sqlite_path": "provider 所在主机可读取的 Agno SQLite 文件绝对路径；仅只读查询本轮关联记录，不填则不采集数据库原始属性。",
        },
        "reader": {
            "operations": ["overview", "list_records", "read"],
            "record_kinds": list(KINDS),
            "source": "frozen_snapshot",
            "exact_model_request": "span input.value 未隐藏时可用，否则 unverified",
        },
        # 连接写在全局登记，绑定写在场景（spec/alg/axis_loop.md §8.2）：页面分别拿它们当模板
        "default_connection": {
            "base_url": "http://127.0.0.1:7777",
            "headers": {},
            "timeout_seconds": 15,
            "poll_attempts": 3,
            "poll_interval_seconds": 0.2,
        },
        "default_bindings": {
            "session_id": {"source": "request", "pointer": "/body/session_id"},
            "user_id": {"source": "request", "pointer": "/body/user_id"},
            "business_trace_id": {"source": "response", "pointer": "/trace_id"},
        },
    }


def _number(value: Any, field: str, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"business_trace.config.{field} 必须是数字") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"business_trace.config.{field} 必须在 {minimum:g}–{maximum:g} 之间")
    return number


def _binding(value: Any, name: str, *, required: bool) -> dict[str, str] | None:
    if value in (None, "") and not required:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"business_trace.config.bindings.{name} 必须是对象")
    source = str(value.get("source") or "").strip().lower()
    pointer = str(value.get("pointer") or "").strip()
    if source not in {"request", "response"}:
        raise ValueError(f"business_trace.config.bindings.{name}.source 只支持 request/response")
    if not pointer.startswith("/"):
        raise ValueError(f"business_trace.config.bindings.{name}.pointer 必须是 JSON Pointer")
    return {"source": source, "pointer": pointer}


def validate_config(value: Any) -> dict[str, Any]:
    """登记的连接 + 场景的绑定。"""
    if not isinstance(value, Mapping):
        raise ValueError("business_trace.config 必须是对象")
    return {**validate_connection(value), "bindings": _bindings(value.get("bindings"))}


def _bindings(raw_bindings: Any) -> dict[str, Any]:
    if not isinstance(raw_bindings, Mapping):
        raise ValueError("business_trace.config.bindings 必须是对象")
    bindings: dict[str, Any] = {
        "session_id": _binding(raw_bindings.get("session_id"), "session_id", required=True),
    }
    for name in ("user_id", "business_trace_id"):
        got = _binding(raw_bindings.get(name), name, required=False)
        if got is not None:
            bindings[name] = got
    expected_sources = {"session_id": "request", "user_id": "request", "business_trace_id": "response"}
    for name, source in expected_sources.items():
        binding = bindings.get(name)
        if binding is not None and binding["source"] != source:
            raise ValueError(f"business_trace.config.bindings.{name}.source 必须是 {source}")
    return bindings


def validate_connection(value: Any) -> dict[str, Any]:
    """只校连接（登记页保存、测试连接用），不含绑定。"""
    if not isinstance(value, Mapping):
        raise ValueError("business_trace.config 必须是对象")
    base_url = str(value.get("base_url") or "").strip().rstrip("/")
    if urlsplit(base_url).scheme.lower() not in {"http", "https"} or not urlsplit(base_url).netloc:
        raise ValueError("business_trace.config.base_url 必须是 http/https 地址")
    raw_headers = value.get("headers") or {}
    if not isinstance(raw_headers, Mapping):
        raise ValueError("business_trace.config.headers 必须是对象")
    headers: dict[str, str] = {}
    for key, item in raw_headers.items():
        header = str(key).strip()
        if not header:
            raise ValueError("business_trace.config.headers 的键不能为空")
        headers[header] = str(item)
    timeout = _number(value.get("timeout_seconds", 15), "timeout_seconds", minimum=0.1, maximum=300)
    attempts = int(_number(value.get("poll_attempts", 3), "poll_attempts", minimum=1, maximum=10))
    interval = _number(value.get("poll_interval_seconds", 0.2), "poll_interval_seconds", minimum=0, maximum=10)
    clean = {
        "base_url": base_url,
        "headers": headers,
        "timeout_seconds": timeout,
        "poll_attempts": attempts,
        "poll_interval_seconds": interval,
    }
    sqlite_path = value.get("sqlite_path")
    if sqlite_path is not None:
        if not isinstance(sqlite_path, str) or not Path(sqlite_path).is_absolute():
            raise ValueError("business_trace.config.sqlite_path 必须为本机 SQLite 文件的绝对路径")
        clean["sqlite_path"] = sqlite_path
    return clean


def _headers(config: Mapping[str, Any]) -> dict[str, str]:
    environment = effective_environment_snapshot(ROOT / ".env")

    def expand(value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            resolved = str(environment.get(name) or "")
            if not resolved:
                raise ValueError(f"业务 Trace 请求头引用的环境变量 {name} 未设置")
            return resolved
        return _ENV.sub(replace, value)

    return {str(key): expand(str(value)) for key, value in dict(config.get("headers") or {}).items()}


def _get_json(config: Mapping[str, Any], path: str, query: Mapping[str, Any] | None = None) -> Any:
    url = str(config["base_url"]) + path
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
    request = urllib.request.Request(url, headers=_headers(config), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=float(config["timeout_seconds"])) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise AgnoHttpError(exc.code, f"Agno GET {path} 返回 HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Agno GET {path} 失败: {exc}") from exc


def _pointer(value: Any, pointer: str) -> Any:
    current = value
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return None
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return None
    return current


def _bound(bindings: Mapping[str, Any], name: str, request: Mapping[str, Any], response: Any) -> Any:
    binding = bindings.get(name)
    if not isinstance(binding, Mapping):
        return None
    root = request if binding.get("source") == "request" else response
    return _pointer(root, str(binding.get("pointer") or ""))


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [item.get("text") if isinstance(item, Mapping) else item for item in value]
        return "".join(part for part in parts if isinstance(part, str)).strip()
    return ""


def _request_user_text(request: Mapping[str, Any]) -> str:
    """本轮用户原话：请求体 messages 里最后一条 user 消息，退而取 message/query/content。"""
    body = request.get("body") if isinstance(request, Mapping) else None
    if not isinstance(body, Mapping):
        return ""
    messages = body.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, Mapping) and message.get("role") == "user":
                return _text(message.get("content"))
    for key in ("message", "query", "content"):
        text = _text(body.get(key))
        if text:
            return text
    return ""


def _run_input(run: Mapping[str, Any]) -> str:
    value = run.get("run_input")
    if value is None:
        value = run.get("input")
    if isinstance(value, Mapping):
        value = value.get("input_content")
    return _text(value)


def _select_turn_run(runs: list[Any], user_id: Any, user_text: str) -> tuple[list[Mapping[str, Any]], int]:
    """session_id 已把范围限定在本用例；本轮 = 原话一致的 run 里 created_at 最新的一条。

    返回 (最新的候选, 原话一致的候选数)。最新时间并列时返回多条，由调用方判歧义。
    同一 session 内轮次串行，本轮响应返回时下一轮尚未发出，所以最新即本轮。
    """
    candidates = [
        run for run in runs
        if isinstance(run, Mapping)
        and (user_id in (None, "") or run.get("user_id") in (None, "", user_id))
        and (not user_text or _run_input(run) == user_text)
    ]
    stamps = [_timestamp(run.get("created_at")) for run in candidates]
    if len(candidates) <= 1 or any(stamp is None for stamp in stamps):
        return candidates, len(candidates)
    latest = max(stamps)
    return [run for run, stamp in zip(candidates, stamps) if stamp == latest], len(candidates)


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.timestamp() if dt.tzinfo is not None else None
        except ValueError:
            pass
    return None


def _session_trace_windows(config: Mapping[str, Any], session_id: Any) -> tuple[dict[str, tuple[float, float]], list[str]]:
    """Microsecond [start, end] of each run's root trace in the session, from /traces?session_id."""
    windows: dict[str, tuple[float, float]] = {}
    errors: list[str] = []
    page, pages = 1, 1
    while page <= pages:
        try:
            payload = _get_json(config, "/traces", {"session_id": str(session_id), "limit": _TRACE_PAGE_SIZE, "page": page})
            if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
                raise ValueError("traces page 缺少 data 列表")
        except Exception as exc:
            errors.append(f"session_trace_page_failed:{page}:{type(exc).__name__}: {exc}")
            break
        for item in payload["data"]:
            if not isinstance(item, Mapping):
                continue
            run_id, start, end = str(item.get("run_id") or ""), _timestamp(item.get("start_time")), _timestamp(item.get("end_time"))
            if run_id and start is not None and end is not None:
                prev = windows.get(run_id)
                windows[run_id] = (min(start, prev[0]), max(end, prev[1])) if prev else (start, end)
        pages = int((payload.get("meta") or {}).get("total_pages") or 1)
        if pages > _TRACE_MAX_PAGES:
            errors.append(f"session_trace_page_limit:{_TRACE_MAX_PAGES}/{pages}")
            pages = _TRACE_MAX_PAGES
        page += 1
    return windows, errors


def _history(
    runs: list[Any], current: Mapping[str, Any], user_id: Any,
    windows: Optional[Mapping[str, tuple[float, float]]] = None,
) -> tuple[list[Any], dict[str, Any]]:
    cutoff = _timestamp(current.get("created_at"))
    if cutoff is None:
        return [], {"status": "not_collected", "reason": "本轮缺可比较的 created_at，未猜测历史顺序"}
    windows = windows or {}
    current_window = windows.get(str(current.get("run_id") or ""))
    history, unknown, by_trace = [], 0, 0
    for run in runs:
        if not isinstance(run, Mapping) or run.get("run_id") == current.get("run_id"):
            continue
        if user_id not in (None, "") and run.get("user_id") not in (None, "", user_id):
            continue
        if str(run.get("status") or "").upper() not in {"COMPLETED", "ERROR", "CANCELLED"}:
            unknown += 1
            continue
        created = _timestamp(run.get("created_at"))
        # Agno run.created_at is second-precision start time, not completion. Two
        # back-to-back turns therefore cannot be ordered from it alone; the root trace
        # spans carry microsecond start/end and settle the order when both are present.
        window = windows.get(str(run.get("run_id") or ""))
        if current_window and window:
            if window[1] < current_window[0]:
                history.append(dict(run) | {"ordering": "trace_timestamps"})
                by_trace += 1
            elif window[0] > current_window[1]:
                continue
            else:
                unknown += 1
            continue
        if created is None or created >= cutoff:
            unknown += created is None or created == cutoff
            continue
        # Without trace windows, use the persisted duration with a full second
        # rounding margin; an overlapping or unbounded run cannot be evidence
        # available before this turn.
        duration = (run.get("metrics") or {}).get("duration")
        if (not isinstance(duration, (float, int)) or not math.isfinite(duration)
                or duration < 0 or created + duration + 1 > cutoff):
            unknown += 1
            continue
        history.append(dict(run) | {"ordering": "created_at_plus_duration"})
    history.sort(key=lambda r: (windows.get(str(r.get("run_id") or ""), (0.0,))[0], _timestamp(r["created_at"]) or 0.0))
    return history, {
        "status": "partial" if unknown else "available" if history else "empty",
        "count": len(history), "excluded_unordered_runs": unknown, "ordered_by_trace_timestamps": by_trace,
        "reason": "仅保存同 session 已终止且确定早于本轮的 run：优先用根 trace 的微秒级 start/end 定序，否则要求 created_at + duration + 1秒精度余量早于本轮 created_at；缺时间、重叠和不明顺序的 run 不纳入。历史状态仍是运行末态，不是逐次状态快照。",
    }


def _trace_pages(config: Mapping[str, Any], run_id: str, first: Mapping[str, Any]) -> tuple[list[Any], list[str]]:
    """Follow AgentOS pagination, retaining explicit partial-collection failures."""
    summaries = list(first.get("data") or [])
    errors: list[str] = []
    meta = first.get("meta") or {}
    pages = int(meta.get("total_pages") or 1)
    for page in range(2, min(pages, _TRACE_MAX_PAGES) + 1):
        try:
            payload = _get_json(config, "/traces", {"run_id": run_id, "limit": _TRACE_PAGE_SIZE, "page": page})
            if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
                raise ValueError("traces page 缺少 data 列表")
            summaries.extend(payload["data"])
        except Exception as exc:
            errors.append(f"trace_page_failed:{page}:{type(exc).__name__}: {exc}")
            break
    if pages > _TRACE_MAX_PAGES:
        errors.append(f"trace_page_limit:{_TRACE_MAX_PAGES}/{pages}")
    # A changing database can repeat a row between pages; never count duplicates as coverage.
    unique = {str(s.get("trace_id")): s for s in summaries if isinstance(s, Mapping) and s.get("trace_id")}
    if len(unique) != len(summaries):
        errors.append("trace_page_duplicate_or_missing_id")
    total = int(meta.get("total_count") or len(unique))
    if len(unique) < total:
        errors.append(f"trace_list_incomplete:{len(unique)}/{total}")
    return list(unique.values()), errors


def check_connection(config: Mapping[str, Any]) -> dict[str, Any]:
    clean = validate_connection(config)
    payload = _get_json(clean, "/traces", {"limit": 1})
    return {
        "ok": True,
        "provider": "agno",
        "base_url": clean["base_url"],
        "traces_endpoint_shape": "object" if isinstance(payload, Mapping) else type(payload).__name__,
    }


def collect(config: Mapping[str, Any], *, request: Mapping[str, Any], response: Any) -> dict[str, Any]:
    clean = validate_config(config)
    bindings = clean["bindings"]
    session_id = _bound(bindings, "session_id", request, response)
    user_id = _bound(bindings, "user_id", request, response)
    business_trace_id = _bound(bindings, "business_trace_id", request, response)
    user_text = _request_user_text(request)
    base = {
        "schema_version": 1,
        "provider": "agno",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "association": {
            "method": "session_id + 本轮用户原话 + 最新 run",
            "session_id": session_id,
            "user_id": user_id,
            "user_text": user_text,
            "business_trace_id": business_trace_id,
        },
        "coverage": {},
        "records": {},
        "refs": [],
        "errors": [],
    }
    if session_id in (None, ""):
        return base | {"status": "failed", "errors": ["binding_missing: session_id"]}
    matches: list[Mapping[str, Any]] = []
    input_matched = 0
    runs: list[Any] = []
    try:
        for attempt in range(int(clean["poll_attempts"])):
            payload = _get_json(
                clean,
                f"/sessions/{urllib.parse.quote(str(session_id), safe='')}/runs",
                {"user_id": user_id},
            )
            runs = payload if isinstance(payload, list) else list(payload.get("data") or []) if isinstance(payload, Mapping) else []
            matches, input_matched = _select_turn_run(runs, user_id, user_text)
            if matches or attempt + 1 >= int(clean["poll_attempts"]):
                break
            time.sleep(float(clean["poll_interval_seconds"]))
        if len(matches) != 1:
            reason = "association_not_found" if not matches else f"association_ambiguous:{len(matches)}"
            return base | {
                "status": "failed",
                "association": base["association"] | {
                    "candidate_run_count": len(runs),
                    "input_matched_run_count": input_matched,
                    "matched_run_count": len(matches),
                },
                "errors": [reason],
            }
        run_summary = dict(matches[0])
        if user_id not in (None, "") and run_summary.get("user_id") not in (None, "", user_id):
            return base | {"status": "failed", "errors": ["run_summary_user_mismatch"]}
        run_id = str(run_summary.get("run_id") or "")
        if not run_id:
            return base | {
                "status": "failed",
                "association": base["association"] | {
                    "candidate_run_count": len(runs),
                    "matched_run_count": 1,
                    "run_id": "",
                },
                "errors": ["association_missing_run_id"],
            }
        run: dict[str, Any] = {}
        run_detail_error = ""
        try:
            detail = _get_json(
                clean,
                f"/sessions/{urllib.parse.quote(str(session_id), safe='')}/runs/{urllib.parse.quote(run_id, safe='')}",
                {"user_id": user_id},
            )
            if isinstance(detail, Mapping):
                detail_run_id = str(detail.get("run_id") or "")
                if detail_run_id and detail_run_id != run_id:
                    return base | {
                        "status": "failed",
                        "association": base["association"] | {
                            "candidate_run_count": len(runs),
                            "matched_run_count": 1,
                            "run_id": run_id,
                        },
                        "errors": [f"run_detail_mismatch:{detail_run_id}"],
                    }
                if not detail_run_id:
                    raise ValueError("run detail 缺少 run_id")
                if user_id not in (None, "") and detail.get("user_id") not in (None, "", user_id):
                    return base | {"status": "failed", "errors": ["run_detail_user_mismatch"]}
                run = dict(detail)
            else:
                raise ValueError("run detail 必须为对象")
        except Exception as exc:
            run_detail_error = f"run_detail_failed:{type(exc).__name__}: {exc}"
        summaries: list[Any] = []
        for attempt in range(int(clean["poll_attempts"])):
            trace_list = _get_json(clean, "/traces", {"run_id": run_id, "limit": _TRACE_PAGE_SIZE})
            if not isinstance(trace_list, Mapping) or not isinstance(trace_list.get("data"), list):
                raise ValueError("traces 响应必须包含 data 列表")
            summaries = list(trace_list["data"])
            if summaries or attempt + 1 >= int(clean["poll_attempts"]):
                break
            time.sleep(float(clean["poll_interval_seconds"]))
        summaries, page_errors = _trace_pages(clean, run_id, trace_list)
        mismatched_summaries = [
            item for item in summaries
            if isinstance(item, Mapping)
            and item.get("run_id") not in (None, "")
            and str(item.get("run_id")) != run_id
        ]
        if mismatched_summaries:
            mismatches = ",".join(
                f"{item.get('trace_id') or '?'}@{item.get('run_id')}"
                for item in mismatched_summaries[:5]
            )
            return base | {
                "status": "failed",
                "association": base["association"] | {
                    "candidate_run_count": len(runs),
                    "matched_run_count": 1,
                    "run_id": run_id,
                },
                "errors": [f"trace_summary_run_mismatch:{mismatches}"],
            }
        details = []
        trace_errors: list[str] = ([run_detail_error] if run_detail_error else []) + page_errors
        for item in summaries:
            trace_id = str(item.get("trace_id") or "") if isinstance(item, Mapping) else ""
            if trace_id:
                try:
                    detail = _get_json(clean, f"/traces/{urllib.parse.quote(trace_id, safe='')}", None)
                    if not isinstance(detail, Mapping) or str(detail.get("trace_id") or "") != trace_id:
                        raise ValueError("trace detail 的 trace_id 与请求不一致")
                    detail_run_id = str(detail.get("run_id") or "") if isinstance(detail, Mapping) else ""
                    if detail_run_id and detail_run_id != run_id:
                        return base | {
                            "status": "failed",
                            "association": base["association"] | {
                                "candidate_run_count": len(runs),
                                "matched_run_count": 1,
                                "run_id": run_id,
                            },
                            "errors": [f"trace_detail_run_mismatch:{trace_id}@{detail_run_id}"],
                        }
                    details.append(detail)
                except Exception as exc:
                    trace_errors.append(f"trace_detail_failed:{trace_id}:{type(exc).__name__}: {exc}")
        windows, window_errors = _session_trace_windows(clean, session_id)
        history, history_coverage = _history(runs, run, user_id, windows)
        if window_errors:
            history_coverage["errors"] = window_errors
        records = {"history_runs": history, "trace_summaries": summaries, "traces": details}
        if run:
            records["run"] = run
        base_url = str(clean["base_url"])
        refs = [{
            "kind": "run",
            "id": run_id,
            "url": f"{base_url}/sessions/{urllib.parse.quote(str(session_id), safe='')}/runs/{urllib.parse.quote(run_id, safe='')}",
        }]
        refs.extend({
            "kind": "trace",
            "id": str(item.get("trace_id") or ""),
            "url": f"{base_url}/traces/{urllib.parse.quote(str(item.get('trace_id') or ''), safe='')}",
        } for item in summaries if isinstance(item, Mapping) and item.get("trace_id"))
        snapshot = base | {
            "status": "succeeded" if details and not trace_errors else "partial",
            "association": base["association"] | {"candidate_run_count": len(runs), "matched_run_count": 1, "run_id": run_id},
            "history_coverage": history_coverage,
            "records": records,
            "refs": refs,
            "errors": trace_errors or ([] if details else ["trace_detail_missing"]),
        }
        from .agno_sources import collect_sources

        collect_sources(clean, snapshot, _get_json)
        snapshot["fingerprint"] = hashlib.sha256(json.dumps(snapshot["records"], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        overview = open_reader(snapshot).overview()
        snapshot["coverage"] = {"categories": overview["categories"], "limitations": overview["limitations"]}
        return snapshot
    except Exception as exc:
        return base | {"status": "failed", "errors": [f"{type(exc).__name__}: {exc}"]}


def open_reader(snapshot: Mapping[str, Any]):
    from .agno_reader import AgnoReader

    return AgnoReader(snapshot)
