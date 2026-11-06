"""Langfuse OSS v3 public API collector; evaluation reads frozen data only."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import secrets
import time
import uuid
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from impl.core.config import ROOT
from impl.core.config_bootstrap import effective_environment_snapshot
from ..reader import KINDS

_ENV = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
# W3C Trace Context：version 00，trace-id 32 位、parent-id 16 位小写十六进制（spec/alg/business-trace-langfuse.md §2）。
TRACEPARENT = "traceparent"
_TRACEPARENT = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}")


def describe():
    return {"provider": "langfuse", "title": "Langfuse OSS v3",
            "summary": "默认按 W3C traceparent（评测方每次请求自动发）精确关联 trace，也可按 metadata 字段关联；轮询异步入库，冻结 trace 与完整 observation 后供案卷及过程六轴读取。",
            "reader": {"operations": ["overview", "list_records", "read"],
                       "record_kinds": list(KINDS), "source": "frozen_snapshot",
                       "exact_model_request": "SDK 记录的输入，不保证等于模型实际收到的完整请求"},
            # 连接写在全局登记，绑定写在场景（spec/alg/axis_loop.md §8.2）
            "default_connection": {"base_url": "http://127.0.0.1:3300",
                "public_key": "${LANGFUSE_PUBLIC_KEY}", "secret_key": "${LANGFUSE_SECRET_KEY}",
                "match_field": "id",
                "timeout_seconds": 15, "poll_timeout_seconds": 60,
                "poll_interval_seconds": 1, "quiet_seconds": 3,
                "max_pages": 20, "page_size": 50, "content_char_limit": None},
            "default_bindings": {},
            # 登记为 metadata.<键> 时场景要写的绑定模板：标识从请求 / 响应的哪里取
            "metadata_bindings": {"business_trace_id": {"source": "request", "pointer": "/body/trace_id"}}}


def validate_config(value):
    """登记的连接 + 场景的绑定。id（W3C）方式不配绑定；metadata 方式必须绑定 business_trace_id。"""
    if not isinstance(value, Mapping):
        raise ValueError("business_trace.config 必须是对象")
    connection = validate_connection(value)
    bindings = value.get("bindings")
    if connection["match_field"] == "id":
        if bindings not in (None, {}):
            raise ValueError("该 Langfuse 源按 W3C 关联：评测方每次请求自动发 traceparent，bindings 写成 {}")
        return {**connection, "bindings": {}}
    binding = bindings.get("business_trace_id") if isinstance(bindings, Mapping) else None
    if (not isinstance(binding, Mapping) or binding.get("source") not in {"request", "response"}
            or not isinstance(binding.get("pointer"), str) or not binding["pointer"].startswith("/")
            or re.search(r"~(?![01])", binding["pointer"])):
        raise ValueError("bindings.business_trace_id 必须有 request/response source 和有效 JSON Pointer")
    return {**connection, "bindings": {"business_trace_id": dict(binding)}}


def prepare(config):
    """每次投递前调用：id（W3C）方式返回本次要发的 traceparent 头，metadata 方式不发。"""
    if validate_config(config)["match_field"] != "id":
        return {}
    parent = secrets.token_hex(8)
    while parent == "0" * 16:
        parent = secrets.token_hex(8)
    return {TRACEPARENT: f"00-{uuid.uuid4().hex}-{parent}-01"}


def _traceparent(request):
    """本次投递发出的 traceparent（记在请求记录的 business_trace_association）→ trace-id；没有或格式不对为 None。
    parent-id 只是 W3C 格式要求带的一段，不用于关联。"""
    association = request.get("business_trace_association") if isinstance(request, Mapping) else None
    headers = association.get("headers") if isinstance(association, Mapping) else None
    values = [v for k, v in (headers or {}).items() if str(k).lower() == TRACEPARENT] if isinstance(headers, Mapping) else []
    match = _TRACEPARENT.fullmatch(str(values[0]).strip()) if len(values) == 1 else None
    return match.group(1) if match else None


def validate_connection(value):
    """只校连接（登记页保存、测试连接用），不含绑定。"""
    if not isinstance(value, Mapping):
        raise ValueError("business_trace.config 必须是对象")
    clean = dict(describe()["default_connection"])
    clean.update({key: value[key] for key in clean if key in value})
    url = urlsplit(str(clean["base_url"]))
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("Langfuse base_url 必须是无凭据、无 query 的 http/https 地址")
    clean["base_url"] = str(clean["base_url"]).rstrip("/")
    for key in ("public_key", "secret_key"):
        if not isinstance(clean[key], str) or not _ENV.fullmatch(clean[key]):
            raise ValueError(f"Langfuse {key} 必须是 ${{ENV_NAME}} 引用，不能保存明文密钥")
    match = clean["match_field"]
    if not isinstance(match, str) or (match != "id" and not re.fullmatch(r"metadata\.[A-Za-z0-9_-]+", match)):
        raise ValueError("match_field 只支持 id 或 metadata.<key>")
    limits = {"timeout_seconds": (.1, 60), "poll_timeout_seconds": (.1, 300),
              "poll_interval_seconds": (.01, 10), "quiet_seconds": (0, 60),
              "max_pages": (1, 100), "page_size": (1, 100), "content_char_limit": (1, 1000000)}
    for key, (low, high) in limits.items():
        raw = clean[key]
        if key == "content_char_limit" and raw is None:
            continue
        if isinstance(raw, bool):
            raise ValueError(f"{key} 必须为有效数字")
        try:
            num = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} 必须为有效数字") from exc
        if not math.isfinite(num) or not low <= num <= high:
            raise ValueError(f"{key} 必须在 {low}–{high} 范围内")
        if key in {"max_pages", "page_size", "content_char_limit"}:
            if not num.is_integer():
                raise ValueError(f"{key} 必须为整数")
            num = int(num)
        clean[key] = num
    if clean["quiet_seconds"] >= clean["poll_timeout_seconds"]:
        raise ValueError("quiet_seconds 必须小于 poll_timeout_seconds")
    return clean


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get_json(config, path, query=None):
    env = effective_environment_snapshot(ROOT / ".env")
    values = []
    for key in ("public_key", "secret_key"):
        name = _ENV.fullmatch(config[key]).group(1)
        value = env.get(name)
        if not value:
            raise ValueError(f"Langfuse 环境变量 {name} 未设置")
        values.append(str(value))
    auth = base64.b64encode(":".join(values).encode()).decode()
    url = config["base_url"] + "/api/public" + path
    if query:
        url += "?" + urlencode(query)
    req = Request(url, headers={"Authorization": "Basic " + auth, "Accept": "application/json"})
    remaining = config.get("_deadline", float("inf")) - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("collection deadline")
    # Never forward project credentials to another destination via a redirect.
    with build_opener(_NoRedirect()).open(req, timeout=min(config["timeout_seconds"], remaining)) as response:
        return json.load(response)


def _error(exc):
    # Server bodies and transport URLs can contain private input; keep errors structural.
    return f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__


def check_connection(config):
    clean = validate_connection(config)
    try:
        data = _get_json(clean, "/projects")
        return {"ok": True, "provider": "langfuse", "project_count": len(data.get("data", []))}
    except Exception as exc:
        return {"ok": False, "provider": "langfuse", "error": _error(exc)}


def _bound(config, request, response):
    if config["match_field"] == "id":
        return _traceparent(request)
    binding = config["bindings"]["business_trace_id"]
    current = request if binding["source"] == "request" else response
    for token in binding["pointer"].split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            current = current.get(token)
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(current):
            current = current[int(token)]
        else:
            return None
    return current if isinstance(current, str) and current.strip() else None


def _pages(config, path, query):
    """翻完全部页才算列全；唯一性按实际返回的行判断。

    Langfuse v3.184.1 的 meta.totalItems 会把并不返回的行算进去（实测按 metadata 过滤：totalItems=3，
    第 1 页 1 条、第 2–3 页为空）。翻到 totalPages 且无读取错误时以实际行为准，计数差异记为 notes，不当作未列全。
    """
    rows, errors, notes, seen = [], [], [], set()
    for page in range(1, config["max_pages"] + 1):
        try:
            data = _get_json(config, path, {**query, "page": page, "limit": config["page_size"]})
            batch = data["data"]
            if not isinstance(batch, list):
                raise ValueError("invalid list")
            for row in batch:
                if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
                    raise ValueError("invalid row")
                if row["id"] in seen:
                    errors.append(path + ": duplicate_id_across_pages")
                    continue
                seen.add(row["id"])
                rows.append(dict(row))
            total = data.get("meta", {}).get("totalPages")
            if total is not None and page >= int(total):
                expected = data.get("meta", {}).get("totalItems")
                if expected is not None and len(rows) != int(expected):
                    notes.append(f"{path}: total_items_reported={int(expected)} returned={len(rows)}")
                return rows, errors, notes
            if total is None and len(batch) < config["page_size"]:
                return rows, errors, notes
        except Exception as exc:
            return rows, errors + [path + ": " + _error(exc)], notes
    return rows, errors + [path + ": page_limit_reached"], notes


def root_id(observations):
    """只看 trace 本身认根（spec/alg/business-trace-langfuse.md §2.4）：上一级为空的步骤恰好一个时就是它；
    一个都没有、而上一级不在本 trace 里的步骤恰好一个时就是它（上一级是 trace 外的调用方）；否则认不出，返回 None。"""
    ids = {row["id"] for row in observations}
    empty = [row["id"] for row in observations if not row.get("parentObservationId")]
    outside = [row["id"] for row in observations if row.get("parentObservationId") and row["parentObservationId"] not in ids]
    if len(empty) == 1:
        return empty[0]
    return outside[0] if not empty and len(outside) == 1 else None


def _matched(config, business_id):
    if config["match_field"] == "id":
        try:
            trace = _get_json(config, "/traces/" + quote(business_id, safe=""))
        except HTTPError as exc:
            if exc.code == 404:
                return [], [], []
            raise
        if trace.get("id") != business_id:
            raise ValueError("trace_id_mismatch")
        return [trace], [], []
    key = config["match_field"].split(".", 1)[1]
    return _pages(config, "/traces", {"filter": json.dumps([
        {"type": "stringObject", "column": "metadata", "key": key, "operator": "=", "value": business_id}])})


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo and 1900 <= parsed.year <= 2299 else None
    except (TypeError, ValueError):
        return None


def _history(config, trace):
    session = trace.get("sessionId")
    current_time = _stamp(trace.get("timestamp"))
    if not session or current_time is None:
        return [], {"status": "not_collected", "reason": "缺少 sessionId 或带时区的本轮时间，不猜测历史"}
    rows, errors, notes = _pages(config, "/traces", {"sessionId": session,
        "toTimestamp": trace["timestamp"], "orderBy": "timestamp.asc"})
    history = []
    for row in rows:
        if row["id"] == trace["id"]:
            continue
        stamp = _stamp(row.get("timestamp"))
        if row.get("sessionId") != session or stamp is None or stamp >= current_time or row["id"] == trace["id"]:
            errors.append("history_scope_not_proven:" + row["id"])
            continue
        try:
            detail = _get_json(config, "/traces/" + quote(row["id"], safe=""))
            stamp = _stamp(detail.get("timestamp"))
            if detail.get("id") != row["id"] or detail.get("sessionId") != session or stamp is None or stamp >= current_time:
                errors.append("history_detail_scope_mismatch:" + row["id"])
                continue
            history.append(detail)
        except Exception as exc:
            history.append(row)
            errors.append("history_detail:" + _error(exc))
    return history, {"status": "partial" if errors else "available", "errors": errors, "listing_notes": notes,
                     "reason": "仅保存同 session、时间严格早于本轮的 trace；不采集历史 observation"}


def collect(config, *, request, response):
    clean = validate_config(config)
    business_id = _bound(clean, request, response)
    snapshot = _snapshot(clean, "w3c" if clean["match_field"] == "id" else clean["match_field"], business_id)
    if business_id is None:
        snapshot["errors"] = ["binding_missing: " + (TRACEPARENT if clean["match_field"] == "id" else "business_trace_id")]
        return snapshot
    return _settle(clean, business_id, snapshot)


def _snapshot(clean, method, business_id):
    return {"schema_version": 1, "provider": "langfuse",
            "captured_at": datetime.now(timezone.utc).isoformat(), "status": "failed",
            "association": {"method": method, "business_trace_id": business_id},
            "records": {}, "errors": [], "coverage": {}, "refs": [],
            "content_char_limit": clean["content_char_limit"]}


def _settle(clean, business_id, snapshot):
    """按标识找到唯一 trace，轮询到稳定后冻结 trace、全部 observation 与同 session 历史（现场采集与按 trace 复评共用）。"""
    deadline = time.monotonic() + clean["poll_timeout_seconds"]
    previous = None
    stable_since = None
    last_errors = []
    polls = 0
    while time.monotonic() < deadline:
        polls += 1
        attempt = dict(clean, _deadline=deadline, timeout_seconds=min(clean["timeout_seconds"], max(.1, deadline - time.monotonic())))
        try:
            matches, errors, match_notes = _matched(attempt, business_id)
            if len(matches) > 1:
                snapshot["errors"] = ["association_ambiguous"]
                snapshot["association"]["matched_trace_count"] = len(matches)
                snapshot["records"] = {}
                return snapshot
            if not matches or errors:
                last_errors = errors or ["trace_not_visible"]
                stable_since = None
            else:
                ident = matches[0]["id"]
                trace = _get_json(attempt, "/traces/" + quote(ident, safe=""))
                key = clean["match_field"].split(".", 1)[-1]
                if trace.get("id") != ident or (clean["match_field"] != "id" and
                        (not isinstance(trace.get("metadata"), Mapping) or trace["metadata"].get(key) != business_id)):
                    raise ValueError("association_detail_mismatch")
                # 步骤取自 trace 详情自带的完整对象：/observations 列表接口在大库上会超时（2026-11-06 公司库实测）
                details = trace.get("observations")
                if not isinstance(details, list) or not all(
                        isinstance(row, Mapping) and isinstance(row.get("id"), str) for row in details):
                    last_errors = ["trace_observations_not_objects"]
                    break
                errors = ["observation_trace_mismatch:" + row["id"] for row in details if row.get("traceId") != ident]
                details = sorted((dict(row) for row in details if row.get("traceId") == ident),
                                 key=lambda r: (_stamp(r.get("startTime")) or 0, r["id"]))
                snapshot["records"] = {"trace": trace, "observations": details}
                snapshot["association"].update(trace_id=ident, matched_trace_count=1, listing_notes=match_notes)
                signature = hashlib.sha256(json.dumps(snapshot["records"], sort_keys=True, default=str).encode()).hexdigest()
                unfinished = [r["id"] for r in details if r.get("type") != "EVENT" and not r.get("endTime")]
                invalid_times = (["trace"] if _stamp(trace.get("timestamp")) is None else []) + [
                    r["id"] for r in details if _stamp(r.get("startTime")) is None or
                    (r.get("endTime") and (_stamp(r["endTime"]) is None or
                     (_stamp(r.get("startTime")) is not None and _stamp(r["endTime"]) < _stamp(r["startTime"]))))]
                if invalid_times:
                    errors.append("invalid_timestamps:" + ",".join(invalid_times))
                last_errors = errors + (["unfinished_observations:" + ",".join(unfinished)] if unfinished else [])
                if not details:
                    last_errors.append("observations_not_visible")
                if signature != previous or last_errors or stable_since is None:
                    stable_since = time.monotonic()
                    previous = signature
                if not last_errors and polls >= 2 and time.monotonic() - stable_since >= clean["quiet_seconds"]:
                    snapshot["status"] = "succeeded"
                    break
        except Exception as exc:
            last_errors = ["collection:" + _error(exc)]
            stable_since = None
            if isinstance(exc, HTTPError) and exc.code in {401, 403}:
                break
        time.sleep(min(clean["poll_interval_seconds"], max(0, deadline - time.monotonic())))
    if snapshot["status"] != "succeeded":
        snapshot["status"] = "partial" if snapshot["records"] else "failed"
        snapshot["errors"] = list(dict.fromkeys(last_errors + ["collection_not_settled"]))
    if snapshot["records"]:
        trace = snapshot["records"]["trace"]
        history, coverage = _history(dict(clean, _deadline=time.monotonic() + clean["poll_timeout_seconds"]), trace)
        snapshot["records"]["history_traces"] = history
        snapshot["history_coverage"] = coverage
        snapshot["refs"] = [{"kind": "trace", "id": trace["id"],
                              "url": clean["base_url"] + "/api/public/traces/" + quote(trace["id"], safe="")}]
    snapshot["fingerprint"] = hashlib.sha256(json.dumps(snapshot["records"], sort_keys=True,
                                                         ensure_ascii=False).encode()).hexdigest()
    overview = open_reader(snapshot).overview()
    snapshot["coverage"] = {"categories": overview["categories"], "limitations": overview["limitations"]}
    return snapshot


def from_trace(config, trace_id):
    """按 trace 复评（spec/alg/trace-replay.md §3.1、§5）：按 trace id 取回这一轮。
    返回 {snapshot, failure, request, delivered, delivered_from}；取不到时 error 写原因，不猜。"""
    clean = validate_connection(config)
    trace_id = str(trace_id or "").strip()
    if not trace_id:
        raise ValueError("from_trace.trace_id 不能为空")
    snapshot = _settle(dict(clean, match_field="id"), trace_id, _snapshot(clean, "trace_id", trace_id))
    out = {"snapshot": snapshot, "failure": "", "request": None, "delivered": None, "delivered_from": "", "error": ""}
    if snapshot["status"] == "failed":
        out["error"] = "trace 没采到：" + ("；".join(snapshot.get("errors") or []) or "无记录")
        return out
    trace = snapshot["records"].get("trace") or {}
    rows = snapshot["records"].get("observations") or []
    if not rows:
        out["error"] = "trace 有记录但没读到步骤"
        return out
    top = root_id(rows)
    if top is None:
        out["error"] = "找不到唯一的根步骤"
        return out
    root = next(row for row in rows if row["id"] == top)

    def recorded(field):
        """本轮的请求 / 答复：根步骤优先，没有再取 trace 级（Langfuse v4 起以根步骤为准）。"""
        if root.get(field) not in (None, "", [], {}):
            return root[field], "root_observation"
        if trace.get(field) not in (None, "", [], {}):
            return trace[field], "trace"
        return None, ""

    # 业务失败了，用户这一轮说了什么照样要记；所以请求先取，取不到也先不报
    out["request"], _ = recorded("input")
    attributes = (root.get("metadata") or {}).get("attributes") if isinstance(root.get("metadata"), Mapping) else None
    status = attributes.get("http.response.status_code") if isinstance(attributes, Mapping) else None
    if status not in (None, ""):
        if not str(status).startswith("2"):
            out["failure"] = f"HTTP {status}"
    elif root.get("level") == "ERROR":
        out["failure"] = str(root.get("statusMessage") or "level=ERROR")
    if out["failure"]:
        return out
    out["delivered"], out["delivered_from"] = recorded("output")
    if out["request"] is None or out["delivered"] is None:
        out["error"] = "这条 trace 没有记本轮的" + ("请求" if out["request"] is None else "答复")
    return out


def open_reader(snapshot):
    from .langfuse_reader import LangfuseReader
    return LangfuseReader(snapshot)
