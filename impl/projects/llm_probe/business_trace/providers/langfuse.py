"""Langfuse OSS v3 public API collector; evaluation reads frozen data only."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from impl.core.config import ROOT
from impl.core.config_bootstrap import effective_environment_snapshot
from ..reader import KINDS

_ENV = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def describe():
    return {"provider": "langfuse", "title": "Langfuse OSS v3",
            "summary": "用业务 ID 精确关联 trace；轮询异步入库，冻结 trace 与完整 observation 后供案卷及过程六轴读取。",
            "reader": {"operations": ["overview", "list_records", "read"],
                       "record_kinds": list(KINDS), "source": "frozen_snapshot",
                       "exact_model_request": "SDK 记录的输入，不保证等于模型实际收到的完整请求"},
            "default_config": {"base_url": "http://127.0.0.1:3300",
                "public_key": "${LANGFUSE_PUBLIC_KEY}", "secret_key": "${LANGFUSE_SECRET_KEY}",
                "match_field": "metadata.business_trace_id",
                "bindings": {"business_trace_id": {"source": "response", "pointer": "/trace_id"}},
                "timeout_seconds": 15, "poll_timeout_seconds": 60,
                "poll_interval_seconds": 1, "quiet_seconds": 3,
                "max_pages": 20, "page_size": 50, "content_char_limit": None}}


def validate_config(value):
    if not isinstance(value, Mapping):
        raise ValueError("business_trace.config 必须是对象")
    clean = dict(describe()["default_config"])
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
    bindings = clean.get("bindings")
    binding = bindings.get("business_trace_id") if isinstance(bindings, Mapping) else None
    if (not isinstance(binding, Mapping) or binding.get("source") not in {"request", "response"}
            or not isinstance(binding.get("pointer"), str) or not binding["pointer"].startswith("/")
            or re.search(r"~(?![01])", binding["pointer"])):
        raise ValueError("bindings.business_trace_id 必须有 request/response source 和有效 JSON Pointer")
    clean["bindings"] = {"business_trace_id": dict(binding)}
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
    clean = validate_config(config)
    try:
        data = _get_json(clean, "/projects")
        return {"ok": True, "provider": "langfuse", "project_count": len(data.get("data", []))}
    except Exception as exc:
        return {"ok": False, "provider": "langfuse", "error": _error(exc)}


def _bound(config, request, response):
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
    snapshot = {"schema_version": 1, "provider": "langfuse",
        "captured_at": datetime.now(timezone.utc).isoformat(), "status": "failed",
        "association": {"method": clean["match_field"], "business_trace_id": business_id},
        "records": {}, "errors": [], "coverage": {}, "refs": [],
        "content_char_limit": clean["content_char_limit"]}
    if business_id is None:
        snapshot["errors"] = ["binding_missing: business_trace_id"]
        return snapshot
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
                observations, errors, observation_notes = _pages(attempt, "/observations", {"traceId": ident})
                details = []
                prior = {row["id"]: row for row in snapshot["records"].get("observations", [])}
                if snapshot["records"].get("trace", {}).get("id") != ident:
                    prior = {}
                for row in observations:
                    if time.monotonic() >= deadline:
                        errors.append("observation_detail_deadline")
                        details.append(row)
                        continue
                    if row.get("traceId") != ident:
                        errors.append("observation_trace_mismatch:" + row["id"])
                        continue
                    try:
                        detail = _get_json(attempt, "/observations/" + quote(row["id"], safe=""))
                        if detail.get("id") != row["id"] or detail.get("traceId") != ident:
                            raise ValueError("observation_detail_mismatch")
                        details.append(detail)
                    except Exception as exc:
                        details.append(prior.get(row["id"], row))
                        errors.append("observation_detail:" + row["id"] + ":" + _error(exc))
                listed_ids = {row["id"] for row in details}
                expected_ids = {row["id"] for row in trace.get("observations", [])
                                if isinstance(row, Mapping) and row.get("id")}
                if expected_ids - listed_ids:
                    errors.append("trace_observation_list_incomplete")
                if errors:
                    details.extend(row for key, row in prior.items() if key not in listed_ids)
                details.sort(key=lambda r: (_stamp(r.get("startTime")) or 0, r["id"]))
                snapshot["records"] = {"trace": trace, "observations": details}
                snapshot["association"].update(trace_id=ident, matched_trace_count=1, listing_notes=match_notes)
                snapshot["listing_notes"] = observation_notes
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


def open_reader(snapshot):
    from .langfuse_reader import LangfuseReader
    return LangfuseReader(snapshot)
