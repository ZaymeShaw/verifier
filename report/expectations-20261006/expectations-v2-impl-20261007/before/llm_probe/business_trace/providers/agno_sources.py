"""Collect additional Agno sources without invoking business agents or tools.

Every source has a receipt. Configuration/memory/session reads are observations at
collection time; they are not silently promoted to run-time context evidence.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote


def embedded_runs(run: Mapping[str, Any]):
    yield run
    for key in ("step_executor_runs", "member_responses"):
        for child in run.get(key) or []:
            if isinstance(child, Mapping):
                yield from embedded_runs(child)


class Sources:
    MAX_REQUESTS = 40

    def __init__(self, config: Mapping[str, Any], snapshot: dict[str, Any], get: Callable):
        self.config, self.snapshot, self.get = config, snapshot, get
        self.receipts: list[dict[str, Any]] = []
        self.paths: set[str] = set()
        self.requests = 0

    def fetch(self, name: str, path: str, *, route: str = "", query: dict | None = None,
              timing: str = "observed_at_collection") -> Any:
        receipt = {"name": name, "path": path, "query": query or {}, "timing": timing,
                   "captured_at": datetime.now(timezone.utc).isoformat()}
        self.receipts.append(receipt)
        if route and route not in self.paths:
            receipt.update(status="unsupported", reason="当前 OpenAPI 未声明此读取接口")
            return None
        if self.requests >= self.MAX_REQUESTS:
            receipt.update(status="not_collected", reason="补充取证请求达到 40 次上限")
            return None
        self.requests += 1
        try:
            value = self.get(self.config, path, query)
            if not isinstance(value, Mapping):
                raise ValueError("Agno 补充读取接口应返回 JSON 对象")
            receipt.update(status="available", sha256=hashlib.sha256(
                json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest())
            return value
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            receipt.update(status="forbidden" if status_code in (401, 403) else "not_recorded" if status_code == 404 else "failed",
                           reason=f"{type(exc).__name__}: {exc}")
            return None

    def collect(self) -> None:
        records = self.snapshot["records"]
        run = records.get("run") or {}
        sid = str(self.snapshot["association"]["session_id"])
        uid = self.snapshot["association"].get("user_id") or run.get("user_id")
        schema = self.fetch("api_schema", "/openapi.json")
        if isinstance(schema, Mapping):
            self.paths = {p for p, operations in schema.get("paths", {}).items() if "get" in operations}
            records["api_schema"] = {"info": schema.get("info"), "get_paths": sorted(self.paths)}
        config = self.fetch("agentos_config", "/config", route="/config")
        if isinstance(config, Mapping):
            records["agentos_config"] = config
        session = self.fetch("session", f"/sessions/{quote(sid, safe='')}", route="/sessions/{session_id}", query={"user_id": uid})
        if isinstance(session, Mapping):
            if str(session.get("session_id") or "") != sid or (uid and session.get("user_id") not in (None, "", uid)):
                self.receipts[-1].update(status="rejected", reason="session 身份与本次关联不一致")
            else:
                records["session"] = session
        definitions = []
        component_ids: set[tuple[str, str]] = set()
        runs = list(embedded_runs(run))
        for item in runs:
            for kind, key in (("workflows", "workflow_id"), ("agents", "agent_id"), ("teams", "team_id")):
                if item.get(key):
                    component_ids.add((kind, str(item[key])))
        for kind, component_id in sorted(component_ids):
            key = {"agents": "agent_id", "teams": "team_id", "workflows": "workflow_id"}[kind]
            route = f"/{kind}/{{{key}}}"
            value = self.fetch(f"definition:{kind}:{component_id}", f"/{kind}/{quote(component_id, safe='')}", route=route)
            if isinstance(value, Mapping):
                if value.get("id") not in (None, "", component_id):
                    self.receipts[-1].update(status="rejected", reason="组件 ID 不一致")
                else:
                    definitions.append({"component_type": kind, "component_id": component_id,
                                        "timing": "observed_at_collection_not_verified_run_version", "data": value})
        records["definitions"] = definitions

        # Only registered agents support the checkpoints router; embedded workflow
        # agents may have a run but no registered agent endpoint.
        registered = {a.get("id") for a in (config or {}).get("agents", []) if isinstance(a, Mapping)} if isinstance(config, Mapping) else set()
        checkpoints = []
        for item in runs:
            aid, rid = item.get("agent_id"), item.get("run_id")
            if not aid or not rid:
                continue
            if aid not in registered:
                self.receipts.append({"name": f"checkpoints:{rid}", "status": "unsupported",
                                      "reason": "此 Agent 未单独注册；检查点端点不能访问该内嵌 Agent"})
                continue
            path = f"/agents/{quote(str(aid), safe='')}/runs/{quote(str(rid), safe='')}/checkpoints"
            value = self.fetch(f"checkpoints:{rid}", path,
                               route="/agents/{agent_id}/runs/{run_id}/checkpoints", query={"session_id": sid},
                               timing="derived_from_persisted_run")
            if not isinstance(value, Mapping):
                continue
            if value.get("run_id") != rid or value.get("session_id") != sid:
                self.receipts[-1].update(status="rejected", reason="checkpoint 关联不一致")
                continue
            checkpoints.append({"run_id": rid, "data": value, "snapshots": []})
            for checkpoint in value.get("checkpoints") or []:
                index = checkpoint.get("message_index") if isinstance(checkpoint, Mapping) else None
                if not isinstance(index, int) or index < 0:
                    continue
                detail = self.fetch(f"checkpoint:{rid}:{index}", f"{path}/{index}",
                                    route="/agents/{agent_id}/runs/{run_id}/checkpoints/{message_index}",
                                    query={"session_id": sid}, timing="derived_from_persisted_run")
                if isinstance(detail, Mapping):
                    if detail.get("run_id") not in (None, rid) or detail.get("session_id") not in (None, sid):
                        self.receipts[-1].update(status="rejected", reason="checkpoint snapshot 关联不一致")
                    else:
                        checkpoints[-1]["snapshots"].append(detail)
        records["checkpoints"] = checkpoints
        memories = []
        if uid:
            for page in range(1, 11):
                value = self.fetch(f"memories:{page}", "/memories", route="/memories", query={"user_id": uid, "page": page, "limit": 20})
                if not isinstance(value, Mapping) or not isinstance(value.get("data"), list):
                    if isinstance(value, Mapping):
                        self.receipts[-1].update(status="failed", reason="memory 响应缺少 data 列表")
                    break
                accepted = [m for m in value["data"] if isinstance(m, Mapping) and m.get("user_id") == uid]
                if len(accepted) != len(value["data"]):
                    self.receipts[-1].update(status="rejected", reason="memory 响应包含无法确认属于本用户的记录")
                    break
                memories.extend(accepted)
                pages = int((value.get("meta") or {}).get("total_pages") or 1)
                if page >= pages:
                    if not memories:
                        self.receipts[-1]["status"] = "empty"
                    break
                if page == 10:
                    self.receipts[-1].update(status="partial", reason="memory 分页达到 10 页上限")
        else:
            self.receipts.append({"name": "memories", "status": "not_collected", "reason": "无明确 user_id，不查询全局记忆"})
        records["memories"] = memories
        self._sqlite(run, sid, uid)
        self.snapshot["sources"] = self.receipts

    def _sqlite(self, run: Mapping[str, Any], sid: str, uid: Any) -> None:
        path = self.config.get("sqlite_path")
        receipt = {"name": "sqlite", "timing": "persisted_run_and_span_records"}
        self.receipts.append(receipt)
        if not path:
            receipt.update(status="not_configured", reason="未配置本机只读 sqlite_path；HTTP API 不返回全部原始 span 属性")
            return
        try:
            with sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                root_id = str(self.snapshot["association"]["run_id"])
                row = connection.execute("SELECT * FROM agno_runs WHERE run_id=? AND session_id=?", (root_id, sid)).fetchone()
                if row is None or (uid and row["user_id"] != uid):
                    raise ValueError("SQLite 中本轮 run/session/user 与 HTTP 关联不一致")
                body = json.loads(row["run_data"])
                if not isinstance(body, Mapping):
                    raise ValueError("SQLite run_data 必须为 JSON 对象")
                if run and body.get("content") != run.get("content"):
                    raise ValueError("SQLite 与 HTTP 本轮 content 不一致，拒绝混合快照")
                raw_runs = [dict(row) | {"run_data": body}]
                known = {root_id}
                pending = list(embedded_runs(body))
                for item in pending:
                    ids = [item.get("run_id")]
                    ids += [t.get("child_run_id") for t in item.get("tools") or [] if isinstance(t, Mapping)]
                    for rid in ids:
                        if not rid or rid in known:
                            continue
                        known.add(rid)
                        if len(known) > 100:
                            raise ValueError("关联运行超过 100 条取证上限")
                        child = connection.execute("SELECT * FROM agno_runs WHERE run_id=? AND session_id=?", (rid, sid)).fetchone()
                        if child is None or (uid and child["user_id"] != uid):
                            continue
                        decoded = json.loads(child["run_data"])
                        if not isinstance(decoded, Mapping):
                            raise ValueError("SQLite child run_data 必须为 JSON 对象")
                        raw_runs.append(dict(child) | {"run_data": decoded})
                        pending.extend(embedded_runs(decoded))
                raw_spans = []
                for trace in self.snapshot["records"].get("trace_summaries") or []:
                    tid = trace.get("trace_id")
                    owner = connection.execute("SELECT run_id,session_id,user_id FROM agno_traces WHERE trace_id=?", (tid,)).fetchone()
                    if owner is None or owner["run_id"] != root_id or owner["session_id"] != sid or (uid and owner["user_id"] != uid):
                        raise ValueError("SQLite span 的 trace/run/session/user 关联不一致")
                    for span in connection.execute("SELECT * FROM agno_spans WHERE trace_id=? ORDER BY start_time,span_id", (tid,)):
                        attributes = json.loads(span["attributes"] or "{}")
                        if not isinstance(attributes, Mapping):
                            raise ValueError("SQLite span attributes 必须为 JSON 对象")
                        raw_spans.append(dict(span) | {"attributes": attributes})
                self.snapshot["records"]["raw_runs"] = raw_runs
                self.snapshot["records"]["raw_spans"] = raw_spans
                receipt.update(status="available", run_count=len(raw_runs), span_count=len(raw_spans),
                               captured_at=datetime.now(timezone.utc).isoformat())
        except (OSError, ValueError, sqlite3.Error, KeyError, TypeError) as exc:
            receipt.update(status="failed", reason=f"{type(exc).__name__}: {exc}")


def collect_sources(config: Mapping[str, Any], snapshot: dict[str, Any], get: Callable) -> None:
    source = Sources(config, snapshot, get)
    try:
        source.collect()
    except (ValueError, TypeError, KeyError) as exc:
        source.receipts.append({"name": "supplemental_collection", "status": "failed", "reason": f"{type(exc).__name__}: {exc}"})
    finally:
        snapshot["sources"] = source.receipts
