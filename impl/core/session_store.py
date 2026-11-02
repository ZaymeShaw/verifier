"""Session 工具的进程内仓库（spec/mock/protocol.md 5.1）。

harness（外部进程）经 CLI/HTTP 调 open / send / intent / close；本模块负责：
- session_id 只由 open 产生，无 open 直接 send 报错；
- 4.6 预算由 Session 强制，另有 reaper 线程把挂住的用户方在预算内关闭；
- close 后按 4.10 自动导出：完整多轮 RunTrace 落 sessions/；transcript seed 以 MockCase 形态
  追加进候选文件 impl/data/<project>/mock_cases-<run_id>.json，用户审后手动拷入 mock_cases.json。
"""
from __future__ import annotations

from .instances import data_root

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import stop_reasons
from .portable_artifact import write_active_artifact
from .schema import MockIntentOutput, to_dict
from .session import (
    INTENT_SOURCES,
    Session,
    SessionAdapterError,
    SessionBudget,
    SessionBudgetExceeded,
    SessionProtocolError,
    SessionTranslator,
    UserMessage,
)
from .trace import TraceContext, trace_from_context

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TURN_WAIT_TIMEOUT_MS = 5 * 60 * 1000
DEFAULT_SESSION_TIMEOUT_MS = 30 * 60 * 1000
REAPER_INTERVAL_S = 5.0
CLOSED_HISTORY_LIMIT = 200


def sessions_dir(project_id: str) -> Path:
    return data_root(ROOT.parent) / project_id / "sessions"


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_file_path(project_id: str, run_id: str) -> Path:
    """候选 case 文件位置：`impl/data/<project>/mock_cases-<run_id>.json`，无 run_id 则 adhoc。"""
    return sessions_dir(project_id).parent / f"mock_cases-{run_id or 'adhoc'}.json"


def _repository_relative(path: Path) -> str:
    """仓库相对路径；沙箱（测试把 sessions_dir 换到仓库外）时退化为绝对路径。"""
    try:
        return str(path.relative_to(ROOT.parent))
    except ValueError:
        return str(path)


def _append_candidate_case(project_id: str, run_id: str, seed_case: Dict[str, Any]) -> str:
    """close 导出的 seed case 追加进项目数据目录的候选文件（同 id 覆盖，不存在则新建）。

    返回仓库相对路径，可直接作 `batch-run --inputs`；run_id 缺失时落 mock_cases-adhoc.json。
    """
    path = _candidate_file_path(project_id, run_id)
    cases: List[Dict[str, Any]] = []
    if path.exists():
        loaded = _read_json(path)
        if isinstance(loaded, list):
            cases = [case for case in loaded if isinstance(case, dict)]
    cases = [case for case in cases if case.get("id") != seed_case.get("id")]
    cases.append(seed_case)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    return _repository_relative(path)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_active_artifact("session_export", path, payload, repository_root=ROOT.parent)


def _health_of(session: Session) -> Dict[str, Any]:
    """harness 会话没有进程内控制器：未出错即 ok，不沿用 legacy 的 not_run。"""
    status = session.ctx.interaction_controller_status
    return stop_reasons.driver_health(
        session.stop_reason,
        "ok" if status == "not_run" else status,
        session.ctx.interaction_controller_error,
        session.budget_usage(),
    ).to_dict()


class _Record:
    def __init__(self, project_id: str, session: Session, live: Any, *, pool: str, run_id: str, scenario: str) -> None:
        self.project_id = project_id
        self.session = session
        self.live = live
        self.pool = pool
        self.run_id = run_id
        self.scenario = scenario
        self.candidate_file = ""
        self.lock = threading.Lock()
        self.opened_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.export_path: Optional[Path] = None


class SessionStore:
    def __init__(self) -> None:
        self._open: Dict[str, _Record] = {}
        self._closed: Dict[str, _Record] = {}
        self._lock = threading.Lock()
        self._reaper: Optional[threading.Thread] = None

    # --- 生命周期 ---

    def open(
        self,
        project_id: str,
        *,
        mode: str = "text",
        budget: Optional[Dict[str, Any]] = None,
        seed_prefix: Optional[List[Dict[str, Any]]] = None,
        seed_mode: Optional[str] = None,
        pool: str = "",
        run_id: str = "",
        scenario: str = "",
    ) -> Dict[str, Any]:
        from .live_protocol import ProjectLive
        from .materials_store import require_materials
        from .project_loader import load_adapter, load_project

        require_materials(project_id)
        spec = load_project(project_id)
        if spec.local_deployment_enabled:
            from .local_service import ensure_project_service

            ensure_project_service(spec)
        adapter = load_adapter(spec)
        live = adapter.live()
        if not isinstance(live, ProjectLive):
            raise TypeError(f"{project_id} adapter.live() must return ProjectLive")
        mock = adapter.mock()
        translator = mock if isinstance(mock, SessionTranslator) else None

        budget = dict(budget or {})
        default_turns = int(spec.session_max_turns)
        session_budget = SessionBudget(
            max_turns=max(1, int(budget.get("max_turns") or default_turns)),
            turn_wait_timeout_ms=int(budget.get("turn_wait_timeout_ms") or DEFAULT_TURN_WAIT_TIMEOUT_MS),
            session_timeout_ms=int(budget.get("session_timeout_ms") or DEFAULT_SESSION_TIMEOUT_MS),
            token_limit=int(budget["token_limit"]) if budget.get("token_limit") is not None else None,
        )
        session_id = f"harness-{project_id}-{uuid.uuid4().hex[:12]}"
        ctx = TraceContext(project_id=project_id, case_id=session_id, scenario=scenario)
        record = _Record(project_id, None, live, pool=pool or (f"harness-{run_id}" if run_id else "harness"), run_id=run_id, scenario=scenario)  # type: ignore[arg-type]
        session = Session(
            live,
            ctx,
            session_id=session_id,
            budget=session_budget,
            user_message_extractor=getattr(mock, "extract_mock_message", None),
            translator=translator,
            mode=mode,
            on_close=lambda closed: self._export(record, closed),
        )
        record.session = session
        prefix_results: List[Dict[str, Any]] = []
        if seed_prefix:
            for result in session.apply_seed(seed_prefix, seed_mode or "replay"):
                prefix_results.append(self._turn_event(result))
        with self._lock:
            self._open[session_id] = record
            self._ensure_reaper()
        return {
            "event": "session.opened",
            "session_id": session_id,
            "project_id": project_id,
            "mode": mode,
            "supports_history_injection": bool(translator is not None and translator.supports_history_injection),
            "budget": {
                "max_turns": session_budget.max_turns,
                "turn_wait_timeout_ms": session_budget.turn_wait_timeout_ms,
                "session_timeout_ms": session_budget.session_timeout_ms,
                "token_limit": session_budget.token_limit,
            },
            "transcript_prefix": list(session.transcript_prefix),
            "prefix_results": prefix_results,
            "pool": record.pool,
        }

    def send(self, session_id: str, message: Dict[str, Any], *, tokens: int = 0) -> Dict[str, Any]:
        record = self._require_open(session_id)
        user_message = UserMessage.from_dict(message)
        with record.lock:
            session = record.session
            if tokens:
                session.report_tokens(tokens)
            if session.closed:
                return self._closed_event(record)
            try:
                result = session.send(user_message)
            except SessionBudgetExceeded as exc:
                return {**self._closed_event(record), "error": str(exc)}
            except SessionAdapterError as exc:
                return {**self._closed_event(record), "error": str(exc)}
            except SessionProtocolError as exc:
                raise ValueError(str(exc)) from exc
            event = self._turn_event(result)
            if session.closed:
                event["session_closed"] = self._closed_event(record)
            return event

    def intent(self, session_id: str, *, user_intent: str, user_context: Optional[Dict[str, Any]] = None, source: str = "seeded") -> Dict[str, Any]:
        record = self._require_open(session_id)
        if source not in INTENT_SOURCES:
            raise ValueError(f"source must be one of {INTENT_SOURCES}")
        if not str(user_intent or "").strip():
            raise ValueError("user_intent is required")
        with record.lock:
            declaration = record.session.declare_intent(
                MockIntentOutput(user_intent=str(user_intent), query="", user_context=dict(user_context or {})),
                source=source,
            )
        return {"event": "intent.declared", "session_id": session_id, **declaration.to_dict()}

    def close(self, session_id: str, stop_reason: str) -> Dict[str, Any]:
        if stop_reason not in stop_reasons.USER_STOP_REASONS:
            raise ValueError(f"stop_reason must be one of {sorted(stop_reasons.USER_STOP_REASONS)}")
        record = self._require_open(session_id)
        with record.lock:
            record.session.close(stop_reason, stopped_by_user=True)
        return self._closed_event(record)

    def list(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            records = list(self._open.values()) + list(self._closed.values())
        items = []
        for record in records:
            if project_id and record.project_id != project_id:
                continue
            session = record.session
            items.append({
                "session_id": session.session_id,
                "project_id": record.project_id,
                "run_id": record.run_id,
                "pool": record.pool,
                "mode": session.mode,
                "closed": session.closed,
                "stop_reason": session.stop_reason,
                "turns": session.turn_count,
                "budget_usage": session.budget_usage(),
                "opened_at": record.opened_at,
                "export_path": str(record.export_path) if record.export_path else "",
            })
        return {"sessions": items}

    def reap(self) -> List[str]:
        """预算超限的会话由评测系统单方面关闭；返回被关闭的 session_id。"""
        with self._lock:
            records = list(self._open.values())
        closed: List[str] = []
        for record in records:
            if record.lock.acquire(blocking=False):
                try:
                    if record.session.expire_if_over_budget():
                        closed.append(record.session.session_id)
                finally:
                    record.lock.release()
        return closed

    # --- 导出（4.10）---

    def export_of(self, project_id: str, session_id: str) -> Dict[str, Any]:
        path = sessions_dir(project_id) / f"{session_id}.json"
        if not path.exists():
            raise KeyError(f"session export not found: {session_id}")
        payload = _read_json(path)
        # 候选 case 文件位置只在响应里给：落盘 payload 走 portable artifact 契约，不放裸路径。
        candidate = _candidate_file_path(project_id, str(payload.get("run_id") or ""))
        if candidate.exists():
            payload["candidate_file"] = _repository_relative(candidate)
        return payload

    def update_export(self, project_id: str, session_id: str, **fields: Any) -> Dict[str, Any]:
        path = sessions_dir(project_id) / f"{session_id}.json"
        payload = _read_json(path)
        payload.update(fields)
        _write_json(path, payload)
        return payload

    def list_exports(self, project_id: str, run_id: str = "") -> List[Dict[str, Any]]:
        directory = sessions_dir(project_id)
        if not directory.exists():
            return []
        items = []
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            payload = _read_json(path)
            if run_id and payload.get("run_id") != run_id:
                continue
            items.append({key: payload.get(key) for key in (
                "session_id", "project_id", "run_id", "candidate_file", "mode", "scenario", "opened_at", "closed_at",
                "stop_reason", "completion_status", "driver_health", "turns", "protocol_fuzz", "intent_history",
                "judge_verdict", "judge_summary",
            )})
        return items

    def _export(self, record: _Record, session: Session) -> None:
        with self._lock:
            self._open.pop(session.session_id, None)
            self._closed[session.session_id] = record
            while len(self._closed) > CLOSED_HISTORY_LIMIT:
                self._closed.pop(next(iter(self._closed)))
        if not session.turns and not session.ctx.turns:
            # 一轮都没发过的会话没有 trace 可导；只留状态。
            return
        first_request = dict(session.ctx.turn_request(0) or {})
        trace = trace_from_context(
            record.live,
            session.ctx,
            case_id=session.session_id,
            scenario=record.scenario,
            reference_contract={},
            initial_request=first_request,
            output=session.last_output or {},
            is_multi_turn=session.turn_count > 1,
            intent=session.ctx.intent,
        )
        seed = session.transcript_seed()
        health = _health_of(session)
        last_intent = session.intent_history[-1] if session.intent_history else None
        seed_case = {
            "id": session.session_id,
            "project_id": record.project_id,
            "scenario": record.scenario,
            "live_request": first_request,
            "intent": {
                "user_intent": last_intent.user_intent,
                "query": session.user_query_of(first_request),
                "user_context": dict(last_intent.user_context),
                "system_understanding": "",
                "scenario": record.scenario,
            } if last_intent is not None else None,
            "output": None,
            "reference": None,
            "seed": seed,
        }
        record.candidate_file = _append_candidate_case(record.project_id, record.run_id, seed_case)
        payload = {
            "session_id": session.session_id,
            "project_id": record.project_id,
            "run_id": record.run_id,
            "mode": session.mode,
            "scenario": record.scenario,
            "opened_at": record.opened_at,
            "closed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stop_reason": session.stop_reason,
            "completion_status": session.ctx.completion_status,
            "driver_health": health,
            "turns": session.turn_count,
            "protocol_fuzz": session.protocol_fuzz_used,
            "intent_history": [item.to_dict() for item in session.intent_history],
            "seed_case": seed_case,
            "trace": to_dict(trace),
            "judge": None,
            "judge_verdict": None,
            "judge_summary": "",
        }
        record.export_path = sessions_dir(record.project_id) / f"{session.session_id}.json"
        _write_json(record.export_path, payload)

    # --- 内部 ---

    def _require_open(self, session_id: str) -> _Record:
        with self._lock:
            record = self._open.get(session_id)
        if record is None:
            with self._lock:
                closed = self._closed.get(session_id)
            if closed is not None:
                raise ValueError(f"session already closed: {session_id} (stop_reason={closed.session.stop_reason})")
            raise KeyError(f"unknown session_id: {session_id}; session ids are only issued by `session open`")
        return record

    def _turn_event(self, result: Any) -> Dict[str, Any]:
        if result.ok:
            return {"event": "live.response", "turn_index": result.turn_index, "extracted_output": result.output}
        return {"event": "live.error", "turn_index": result.turn_index, "error": result.error, "recoverable": False}

    def _closed_event(self, record: _Record) -> Dict[str, Any]:
        session = record.session
        health = _health_of(session)
        return {
            "event": "session.closed",
            "session_id": session.session_id,
            "stop_reason": session.stop_reason,
            "completion_status": session.ctx.completion_status,
            "driver_health": health,
            "turns": session.turn_count,
            "export_path": str(record.export_path) if record.export_path else "",
            "candidate_file": record.candidate_file,
        }

    def _ensure_reaper(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return

        def loop() -> None:
            while True:
                time.sleep(REAPER_INTERVAL_S)
                try:
                    self.reap()
                except Exception:  # pragma: no cover - 看守线程不能死
                    pass
                with self._lock:
                    if not self._open:
                        self._reaper = None
                        return

        self._reaper = threading.Thread(target=loop, name="session-reaper", daemon=True)
        self._reaper.start()


STORE = SessionStore()
