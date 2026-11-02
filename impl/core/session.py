"""多轮会话（Session）与驱动器（Driver）。

spec/mock/protocol.md 第 4 节（协议 A）与第 5 节（协议 B）的运行时骨架。

- Session：被动的一轮一轮执行器。持有 TraceContext，负责 deliver_turn、
  record_turn、transcript 累积与结束事实上报。不决定用户何时说话、说什么、何时停。
- Driver：消费 Session 的一方。OneShotDriver 单轮执行（发一次请求就关）；
  ReplayDriver 逐字重放录好的 transcript seed 并标回放分叉；
  harness 作为外部进程经 session_store 的工具接口消费。
- SessionTranslator：项目 adapter 侧的确定性翻译契约（6.1），text/action ↔ REQUEST_SCHEMA。
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from impl.core.live_protocol import _LiveProtocol
    from impl.core.schema import MockContinueDecision, MockIntentOutput
    from impl.core.trace import TraceContext

logger = logging.getLogger(__name__)

INTENT_SOURCES = ("seeded", "adopted_from_inference", "drifted")
SESSION_MODES = ("text", "protocol-fuzz")
SEED_MODES = ("replay", "context")


@dataclass
class UserMessage:
    """协议 A 4.2 用户侧消息：request 原样透传；text/action 经 adapter 确定性翻译。"""

    type: Literal["text", "action", "request"]
    text: str = ""
    name: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "UserMessage":
        kind = str(data.get("type") or "")
        if kind not in ("text", "action", "request"):
            raise ValueError(f"unknown user message type: {kind!r}")
        return UserMessage(
            type=kind,  # type: ignore[arg-type]
            text=str(data.get("text") or ""),
            name=str(data.get("name") or ""),
            params=dict(data.get("params") or {}),
            payload=dict(data.get("payload") or {}),
        )

    def identity(self) -> Dict[str, Any]:
        """往返不变式比较口径：request 级只比类型，text/action 比原文与字段。"""
        if self.type == "text":
            return {"type": "text", "text": self.text}
        if self.type == "action":
            return {"type": "action", "name": self.name, "params": self.params}
        return {"type": "request"}


@dataclass
class IntentDeclaration:
    """协议 A 4.2 declare_intent：模拟用户的真值标签，Session 只追加不加工。"""

    turn_index: int
    user_intent: str
    user_context: Dict[str, Any] = field(default_factory=dict)
    source: str = "seeded"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SessionState:
    """协议 A 4.4：Session 交给 adapter 的只读状态。"""

    session_id: str
    turn_index: int
    transcript: List[Dict[str, Any]]
    last_request: Optional[Dict[str, Any]]


class SessionTranslator(ABC):
    """adapter 契约 6.1。多轮项目的 Mock 类混入它，实现原话 ↔ 请求体的确定性互转。

    禁止：改写/摘要原文、从文本推断结构化参数、任何 LLM 调用、发明 transcript 中不存在的历史。
    """

    supports_history_injection: bool = False

    @abstractmethod
    def request_from_user_message(self, message: UserMessage, state: SessionState) -> Dict[str, Any]:
        """text/action → REQUEST_SCHEMA。"""

    @abstractmethod
    def user_message_from_request(self, request: Dict[str, Any]) -> UserMessage:
        """REQUEST_SCHEMA → text/action，与上者互逆。"""


class SessionProtocolError(RuntimeError):
    """用户方违反协议 A（非法消息、模式不允许的消息类型、无 open 直接 send 等）。"""


class SessionAdapterError(RuntimeError):
    """adapter 翻译失败或违反 6.2 往返不变式。Session 已按 adapter_error 关闭。"""


@dataclass
class SessionBudget:
    """协议 A 4.6 预算，由 Session 强制执行。

    - max_turns：最大轮数。
    - turn_wait_timeout_ms：上一轮 live 返回后，等待用户方下一条消息的墙钟上限；超限 → driver_timeout。
    - session_timeout_ms：整会话墙钟上限；超限 → session_timeout。
    - token_limit：用户方自报 token 上限；超限 → driver_budget_exceeded。
    """

    max_turns: int = 1
    turn_wait_timeout_ms: Optional[int] = None
    session_timeout_ms: Optional[int] = None
    token_limit: Optional[int] = None


class SessionBudgetExceeded(RuntimeError):
    """用户方在预算耗尽后仍尝试发消息。Session 已按对应 stop_reason 关闭。"""

    def __init__(self, stop_reason: str) -> None:
        super().__init__(f"session budget exceeded: {stop_reason}")
        self.stop_reason = stop_reason


@dataclass
class TurnResult:
    """一轮 live 调用的用户可见结果。"""

    turn_index: int
    ok: bool
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class Session:
    """协议 A 会话。一个 Session 对应一条 RunTrace。"""

    def __init__(
        self,
        live: "_LiveProtocol",
        ctx: "TraceContext",
        *,
        session_id: str,
        budget: SessionBudget,
        user_message_extractor: Any = None,
        translator: Optional[SessionTranslator] = None,
        mode: str = "protocol-fuzz",
        clock: Any = time.monotonic,
        on_close: Optional[Callable[["Session"], None]] = None,
        initial_request: Optional[Dict[str, Any]] = None,
    ) -> None:
        if mode not in SESSION_MODES:
            raise ValueError(f"unknown session mode: {mode!r}")
        self.live = live
        self.ctx = ctx
        self.session_id = session_id
        self.budget = budget
        self._extract_user_message = user_message_extractor
        self.translator = translator
        self.mode = mode
        self._clock = clock
        self._on_close = on_close
        self.opened_at = clock()
        self.last_activity_at = self.opened_at
        self.tokens_used = 0
        self.turns: List[Dict[str, Any]] = []
        self.transcript: List[Dict[str, Any]] = []
        # 每轮用户消息的原始形态（供导出 transcript seed 与回放）。
        self.user_messages: List[Dict[str, Any]] = []
        self.intent_history: List[IntentDeclaration] = []
        self.transcript_prefix: List[Dict[str, Any]] = []
        self.seed_mode: Optional[str] = None
        self.last_output: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None
        # case 的首轮请求作为首轮翻译的信封模板（身份、capability 等固定字段）；发过一轮后被真实请求覆盖。
        self.last_request: Optional[Dict[str, Any]] = dict(initial_request) if initial_request else None
        self.closed = False
        self.stop_reason = ""
        self.stopped_by_user = False
        self.protocol_fuzz_used = False

    # --- 状态 ---

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def budget_exhausted(self) -> bool:
        return self.turn_count >= self.budget.max_turns

    def elapsed_ms(self) -> int:
        return int((self._clock() - self.opened_at) * 1000)

    def idle_ms(self) -> int:
        return int((self._clock() - self.last_activity_at) * 1000)

    def budget_usage(self) -> Dict[str, Any]:
        return {
            "turns": self.turn_count,
            "max_turns": self.budget.max_turns,
            "elapsed_ms": self.elapsed_ms(),
            "session_timeout_ms": self.budget.session_timeout_ms,
            "tokens_used": self.tokens_used,
            "token_limit": self.budget.token_limit,
        }

    def report_tokens(self, count: int) -> None:
        """用户方自报本轮消耗的 token；超过 token_limit 时关闭会话。"""
        self.tokens_used += max(0, int(count or 0))
        limit = self.budget.token_limit
        if limit is not None and self.tokens_used > limit and not self.closed:
            self.close("driver_budget_exceeded")

    def exceeded_budget(self) -> Optional[str]:
        """返回当前已超限的预算对应的 stop_reason；未超限返回 None。"""
        if self.turn_count >= self.budget.max_turns:
            return "max_turns"
        timeout = self.budget.session_timeout_ms
        if timeout is not None and self.elapsed_ms() > timeout:
            return "session_timeout"
        wait = self.budget.turn_wait_timeout_ms
        if wait is not None and self.idle_ms() > wait:
            return "driver_timeout"
        limit = self.budget.token_limit
        if limit is not None and self.tokens_used > limit:
            return "driver_budget_exceeded"
        return None

    def expire_if_over_budget(self) -> Optional[str]:
        """供外部看守（如 CLI 会话仓库的 reaper）调用：超限则关闭并返回 stop_reason。"""
        if self.closed:
            return None
        reason = self.exceeded_budget()
        if reason is not None:
            self.close(reason)
        return reason

    def accumulated(self) -> Dict[str, Any]:
        """当前会话累积状态快照。"""
        return {
            "turns": list(self.turns),
            "current_turn": self.turn_count,
            "safety_max_turns": self.budget.max_turns,
        }

    # --- 用户方 → Session ---

    def state(self) -> SessionState:
        """协议 A 4.4：交给 adapter 的只读状态（含 seed 前缀）。"""
        transcript: List[Dict[str, Any]] = list(self.transcript_prefix)
        for turn in self.turns:
            request = dict(turn.get("live_request") or {})
            output = dict(turn.get("extract_output") or {})
            transcript.append({"role": "user", "content": self.user_query_of(request), "request": request})
            transcript.append({
                "role": "assistant",
                "content": self.live._summarize_assistant(output),
                "extracted_output": output,
            })
        return SessionState(
            session_id=self.session_id,
            turn_index=self.turn_count + 1,
            transcript=transcript,
            last_request=dict(self.last_request) if self.last_request else None,
        )

    def apply_seed(self, prefix: List[Dict[str, Any]], mode: str) -> List[TurnResult]:
        """协议 A 4.5：transcript 前缀。

        replay：前缀中每条用户消息依次真实打到 live；历史响应只作参考留在 transcript_prefix。
        context：前缀不执行，进入 state.transcript 供 adapter 注入历史字段；adapter 未声明
        supports_history_injection 时拒绝，不静默降级。
        """
        if mode not in SEED_MODES:
            raise SessionProtocolError(f"unknown seed mode: {mode!r}")
        if self.turn_count:
            raise SessionProtocolError("seed prefix must be applied before the first turn")
        prefix = [dict(item) for item in (prefix or []) if isinstance(item, dict)]
        self.seed_mode = mode
        if mode == "context":
            if self.translator is None or not self.translator.supports_history_injection:
                raise SessionProtocolError(
                    "seed mode 'context' requires an adapter with supports_history_injection=True"
                )
            self.transcript_prefix = prefix
            return []
        self.transcript_prefix = prefix
        results: List[TurnResult] = []
        for item in prefix:
            if str(item.get("role") or "") != "user":
                continue
            if isinstance(item.get("request"), dict):
                message = UserMessage(type="request", payload=dict(item["request"]))
            elif isinstance(item.get("message"), dict):
                message = UserMessage.from_dict(item["message"])
            else:
                message = UserMessage(type="text", text=str(item.get("content") or ""))
            results.append(self.send(message, allow_request=True))
            if self.closed:
                break
        return results

    def user_query_of(self, request: Dict[str, Any]) -> str:
        if self.translator is not None:
            message = self.translator.user_message_from_request(request)
            return message.text if message.type == "text" else f"{message.name} {message.params}".strip()
        if self._extract_user_message is not None:
            return str(self._extract_user_message(request) or "")
        return str(request.get("query") or request.get("content") or "")

    def send(self, message: UserMessage, *, allow_request: bool = False) -> TurnResult:
        """协议 A 4.2 统一入口。text/action 经 adapter 翻译并做往返校验；request 原样透传。"""
        if self.closed:
            raise SessionProtocolError("Session is closed")
        if message.type == "request":
            if self.mode != "protocol-fuzz" and not allow_request:
                raise SessionProtocolError(
                    "request-level messages require --mode protocol-fuzz"
                )
            if self.mode == "protocol-fuzz":
                self.protocol_fuzz_used = True
            return self.send_request(message.payload, message=message)
        if self.translator is None:
            raise SessionProtocolError(
                f"{self.ctx.project_id} adapter does not implement SessionTranslator; "
                "only request-level messages are possible"
            )
        try:
            request = self.translator.request_from_user_message(message, self.state())
            if not isinstance(request, dict) or not request:
                raise ValueError("request_from_user_message returned an empty or invalid request")
            back = self.translator.user_message_from_request(request)
            if back.identity() != message.identity():
                raise ValueError(
                    f"round-trip invariant violated: sent {message.identity()!r}, got back {back.identity()!r}"
                )
        except Exception as exc:
            logger.warning("adapter translation failed: %s", exc, exc_info=True)
            self.record_controller("error", exc)
            self.close("adapter_error")
            raise SessionAdapterError(str(exc)) from exc
        return self.send_request(request, message=message)

    def send_request(self, request: Dict[str, Any], *, message: Optional[UserMessage] = None) -> TurnResult:
        """request 级消息：把 REQUEST_SCHEMA 请求体原样打到 live，记录一轮。"""
        if self.closed:
            raise SessionProtocolError("Session is closed")
        over = self.exceeded_budget()
        if over is not None:
            self.close(over)
            raise SessionBudgetExceeded(over)
        request = dict(request or {})
        user_query = self.user_query_of(request)
        self.transcript.append({"role": "user", "content": user_query, "query": user_query})
        self.user_messages.append(
            (message or UserMessage(type="request", payload=dict(request))).to_dict()
        )
        self.last_request = request

        start = time.time()
        try:
            output = self.live.deliver_turn(request)
        except Exception as exc:
            runtime_ms = int((time.time() - start) * 1000)
            facts = self.live._take_turn_facts()
            from impl.core.live_protocol import live_failure_type

            fallback = self.live._build_fallback(request, str(exc), live_failure_type(exc))
            self.ctx.record_turn(
                request=request,
                raw_response=facts.get("raw_response"),
                live_exchanges=list(facts.get("live_exchanges") or []),
                extracted_output={},
                call_status="failed",
                runtime_ms=runtime_ms,
                error=str(exc),
                fallbacks=[fallback],
                validation=list(facts.get("validation") or []),
                mock_message=user_query,
            )
            self.last_activity_at = self._clock()
            # live 故障归 live 组：Session 自行关闭，不等用户方决定，也不落到预算超时上。
            self.last_error = str(exc)
            self.close("live_error")
            return TurnResult(turn_index=self.turn_count + 1, ok=False, error=str(exc))

        runtime_ms = int((time.time() - start) * 1000)
        facts = self.live._take_turn_facts()
        raw_response = facts.get("raw_response")
        # 包装 LiveRequest：project hooks (application_boundary / project_fields / build_execution_trace)
        # 期望 LiveRequest 对象而不是原始 dict。
        from impl.core.schema import LiveRequest as _LiveRequest
        live_request = _LiveRequest(
            project_id=self.live.spec.project_id,
            raw_input={},
            case_id=self.ctx.case_id or "",
            normalized_request=request,
            execution_mode="provided" if self.live._has_provided_output() else "live",
            session_id=self.session_id,
        )
        application_boundary = self.live.application_boundary(raw_response, output, live_request)
        project_fields = self.live.project_fields(raw_response, output, live_request, application_boundary)
        execution_trace = list(facts.get("validation") or []) + list(
            self.live.build_execution_trace(raw_response, output, live_request) or []
        )
        self.ctx.record_turn(
            request=request,
            raw_response=raw_response,
            live_exchanges=list(facts.get("live_exchanges") or []),
            extracted_output=output,
            call_status="succeeded",
            runtime_ms=runtime_ms,
            error=None,
            fallbacks=[],
            validation=[],
            execution_trace=execution_trace,
            application_boundary=application_boundary,
            project_fields=project_fields,
            mock_message=user_query,
        )
        self.last_output = output
        self.turns.append({
            "turn_index": self.turn_count + 1,
            "live_request": dict(request),
            "extract_output": dict(output),
            "status": "succeeded",
            "error": None,
        })
        self.transcript.append({
            "role": "assistant",
            "content": self.live._summarize_assistant(output),
            "stage": output.get("stage") if isinstance(output, dict) else None,
        })
        self.last_activity_at = self._clock()
        return TurnResult(turn_index=self.turn_count, ok=True, output=output)

    def declare_intent(
        self,
        intent: "MockIntentOutput",
        *,
        source: str = "seeded",
        turn_index: Optional[int] = None,
    ) -> IntentDeclaration:
        """协议 A 4.2 declare_intent：追加真值标签；mock_intent 暂取最后一条，保持 judge 现状。"""
        if source not in INTENT_SOURCES:
            raise SessionProtocolError(f"unknown intent source: {source!r}")
        declaration = IntentDeclaration(
            turn_index=self.turn_count if turn_index is None else int(turn_index),
            user_intent=str(getattr(intent, "user_intent", "") or ""),
            user_context=dict(getattr(intent, "user_context", {}) or {}),
            source=source,
        )
        self.intent_history.append(declaration)
        self.ctx.set_intent(intent)
        self.ctx.intent_history = [item.to_dict() for item in self.intent_history]
        return declaration

    def mark_divergence(self, turn_index: int) -> None:
        """协议 5.3：回放时第一处与录制响应不一致的轮次。只记第一处。"""
        if self.ctx.diverged_at_turn is None:
            self.ctx.diverged_at_turn = int(turn_index)

    def record_decision(self, decision: "MockContinueDecision") -> None:
        self.ctx.record_decision(decision)

    def record_controller(self, status: str, error: Any = None) -> None:
        self.ctx.record_interaction_controller(status, error)

    def close(self, stop_reason: str, *, stopped_by_user: Optional[bool] = None) -> None:
        """结束会话并上报结束事实。completion_status 由归责推导（4.8）：

        - 没有任何有效 live 输出 → failed
        - 由用户决定停止（stop_reason 属用户组）→ completed
        - 其余（预算 / Driver / adapter / live 故障）→ incomplete
        """
        from impl.core.stop_reasons import is_user_decision

        if self.closed:
            return
        self.closed = True
        self.stop_reason = stop_reason
        if stopped_by_user is None:
            stopped_by_user = is_user_decision(stop_reason)
        self.stopped_by_user = stopped_by_user
        final_output_turn = self.turn_count if self.last_output is not None else None
        if self.last_output is None:
            completion_status = "failed"
        elif stopped_by_user:
            completion_status = "completed"
        else:
            completion_status = "incomplete"
        self.ctx.finish_execution(
            session_id=self.session_id,
            stop_reason=stop_reason,
            transcript=self.transcript,
            final_output_turn=final_output_turn,
            completion_status=completion_status,
        )
        if self._on_close is not None:
            self._on_close(self)

    def transcript_seed(self) -> Dict[str, Any]:
        """协议 A 4.10 / 5.2：可回放的 transcript seed（按录制的用户轮次逐字重放）。"""
        turns: List[Dict[str, Any]] = []
        for index, message in enumerate(self.user_messages):
            turn = self.turns[index] if index < len(self.turns) else {}
            turns.append({
                "turn_index": index + 1,
                "message": dict(message),
                "request": dict(turn.get("live_request") or {}),
                "extracted_output": dict(turn.get("extract_output") or {}),
                "assistant": self.live._summarize_assistant(dict(turn.get("extract_output") or {})) if turn else "",
            })
        return {
            "level": "transcript" if len(turns) > 1 else "request",
            "mode": "replay",
            "session_mode": self.mode,
            "protocol_fuzz": self.protocol_fuzz_used,
            "stop_reason": self.stop_reason,
            "prefix": list(self.transcript_prefix),
            "prefix_mode": self.seed_mode,
            "turns": turns,
            "intent_history": [item.to_dict() for item in self.intent_history],
        }


class Driver(ABC):
    """协议 B 用户方。run 内部通过 Session 驱动整场会话并负责 close。"""

    @abstractmethod
    def run(
        self,
        session: Session,
        initial_request: Dict[str, Any],
        intent: Optional["MockIntentOutput"],
    ) -> None:
        ...


class OneShotDriver(Driver):
    """单轮执行：发一次请求就关。单轮是 N=1 的会话，不是另一种类型。"""

    def run(
        self,
        session: Session,
        initial_request: Dict[str, Any],
        intent: Optional["MockIntentOutput"],
    ) -> None:
        if intent:
            session.declare_intent(intent, source="seeded")
        result = session.send_request(initial_request)
        if result.ok:
            session.close("single_turn_completed")
        # If not ok, session.send_request already closed with live_error


class PersonaDriver(Driver):
    """多轮无 seed：mock 扮演用户，逐轮 infer_user_intent / decide_next_action / build_next_request。

    goal_satisfied 的可见证据兜底委托 live._has_visible_goal_evidence（项目如 policy_search 有覆盖）。
    轮数上限由 session.budget.max_turns（runtime.session.max_turns）决定。
    """

    def __init__(self, mock: Any) -> None:
        self.mock = mock

    def run(
        self,
        session: Session,
        initial_request: Dict[str, Any],
        intent: Optional["MockIntentOutput"],
    ) -> None:
        from impl.core.schema import MockContinueDecision

        mock = self.mock
        request = dict(initial_request or {})
        max_turns = session.budget.max_turns

        for turn_index in range(max_turns):
            result = session.send_request(request)
            if not result.ok:
                session.close("live_error")
                return
            output = result.output

            if intent is None or not getattr(intent, "user_intent", "") or not getattr(intent, "query", ""):
                try:
                    intent = mock.infer_user_intent(dict(initial_request))
                    if not getattr(intent, "user_intent", "") or not getattr(intent, "query", ""):
                        raise ValueError("infer_user_intent returned empty required fields")
                    # 推断出的意图不是真值标签（协议 8 节），只喂给 mock_intent，不进 intent_history。
                    session.ctx.set_intent(intent)
                except Exception as exc:
                    logger.warning("mock.infer_user_intent failed: %s", exc, exc_info=True)
                    session.record_controller("error", exc)
                    session.close("intent_unavailable")
                    return

            accumulated = session.accumulated()
            decision = None
            decision_error: Optional[Exception] = None
            for decision_attempt in range(2):
                try:
                    decision = mock.decide_next_action(intent, accumulated)
                    decision_error = None
                    break
                except Exception as exc:
                    decision_error = exc
                    logger.warning(
                        "mock.decide_next_action attempt %d/2 failed: %s",
                        decision_attempt + 1,
                        exc,
                        exc_info=True,
                    )
            if decision is None:
                session.record_controller("error", decision_error)
                session.close("decision_error")
                return
            session.record_controller("ok")
            if (
                decision.action == "stop"
                and decision.stop_reason == "goal_satisfied"
                and not session.live._has_visible_goal_evidence(output)
            ):
                decision = MockContinueDecision(action="stop", stop_reason="perceived_no_progress")
            session.record_decision(decision)
            if decision.action == "stop":
                session.close(decision.stop_reason or "user_abandons", stopped_by_user=True)
                return
            if turn_index + 1 >= max_turns:
                session.close("safety_max_turns")
                return
            try:
                request = mock.build_next_request(intent, accumulated)
            except Exception as exc:
                logger.warning("mock.build_next_request failed at turn %d: %s", turn_index + 2, exc, exc_info=True)
                session.record_controller("error", exc)
                session.close("request_build_error")
                return
            if not isinstance(request, dict) or not request:
                session.record_controller(
                    "error",
                    "mock.build_next_request returned an empty or invalid request",
                )
                session.close("request_build_error")
                return

        session.close("safety_max_turns")


def output_signature(live: Any, output: Dict[str, Any]) -> Dict[str, Any]:
    """协议 5.3 默认比较口径：用户可见文本 + stage。项目可通过覆盖 _summarize_assistant 改变文本口径。"""
    output = output if isinstance(output, dict) else {}
    return {
        "content": live._summarize_assistant(output),
        "stage": output.get("stage"),
    }


class ReplayDriver(Driver):
    """协议 5.2/5.3：确定性逐字重放 transcript seed，标记回放分叉。

    - 用户消息按录制的形态原样重发：text/action 经 adapter 重新翻译（会话身份由新 Session 分配），
      request 级（protocol-fuzz 录制）原样透传。
    - declare_intent 按录制的轮次重放，source 沿用录制值。
    - 每轮把新响应与录制响应按 output_signature 比较，第一处不一致记入 diverged_at_turn。
    - 重放结束用录制的 stop_reason 关闭；录制会话若非用户决定结束，如实沿用其 stop_reason。
    - 不做任何 LLM 适配；live 变了就改台词属于再探索，归 harness。
    """

    def __init__(self, seed: Dict[str, Any]) -> None:
        self.seed = dict(seed or {})

    def run(
        self,
        session: Session,
        initial_request: Dict[str, Any],
        intent: Optional["MockIntentOutput"],
    ) -> None:
        from impl.core.schema import MockIntentOutput

        turns = [turn for turn in (self.seed.get("turns") or []) if isinstance(turn, dict)]
        declarations = [item for item in (self.seed.get("intent_history") or []) if isinstance(item, dict)]
        prefix = [item for item in (self.seed.get("prefix") or []) if isinstance(item, dict)]
        prefix_mode = self.seed.get("prefix_mode")

        def declare_for(turn_index: int) -> None:
            for item in declarations:
                if int(item.get("turn_index") or 0) == turn_index:
                    session.declare_intent(
                        MockIntentOutput(
                            user_intent=str(item.get("user_intent") or ""),
                            query="",
                            user_context=dict(item.get("user_context") or {}),
                        ),
                        source=str(item.get("source") or "seeded"),
                        turn_index=turn_index,
                    )

        if prefix and prefix_mode in SEED_MODES:
            session.apply_seed(prefix, str(prefix_mode))
            if session.closed:
                return
        declare_for(0)
        for turn in turns:
            if session.closed:
                return
            recorded_index = int(turn.get("turn_index") or 0)
            message_data = turn.get("message") if isinstance(turn.get("message"), dict) else None
            if message_data is None:
                message = UserMessage(type="request", payload=dict(turn.get("request") or {}))
            else:
                message = UserMessage.from_dict(message_data)
            try:
                result = session.send(message, allow_request=True)
            except SessionBudgetExceeded:
                return
            except SessionAdapterError:
                return
            if not result.ok:
                session.close("live_error")
                return
            # 手写的 seed 没有录制响应（无 extracted_output 键），无可比对，不算分叉。
            if isinstance(turn.get("extracted_output"), dict):
                recorded = output_signature(session.live, dict(turn.get("extracted_output") or {}))
                if output_signature(session.live, result.output) != recorded:
                    session.mark_divergence(recorded_index or session.turn_count)
            declare_for(recorded_index or session.turn_count)
        if not session.closed:
            recorded_stop = str(self.seed.get("stop_reason") or "") or "user_abandons"
            session.close(recorded_stop)
