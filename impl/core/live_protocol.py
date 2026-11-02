"""Live 协议层和扩展点基类

四层文件关系：
- live_protocol.py: 协议层（_LiveProtocol，主流程实现）+ 操作层（ProjectLive，扩展点）
- live.py: 通用层（工具函数：fallback_decision 等）
- projects/<project>/live.py: 项目层（实现扩展点）
"""
from __future__ import annotations
import logging
import inspect
from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Optional, Dict, List
from typing import final as typing_final
if TYPE_CHECKING:
    from impl.core.trace import TraceContext
    from impl.core.schema import MockIntentOutput
from impl.core.schema import (
    ExecutionTraceEvent, FallbackDecision, LiveRequest,
    ProjectSpec, SingleTurnCase, MultiTurnCase,
)
from impl.core.protocol_base import check_forbidden_overrides
from impl.core.live_transport import LiveHTTPStatusError, LiveTransport, validate_real_transport

logger = logging.getLogger(__name__)

# deliver_turn 的公开返回值保持 EXTRACT_OUTPUT_SCHEMA；raw_response/validation 等执行事实
# 仅在当前执行上下文内临时传给 execute_live，避免 adapter 缓存的 Live 实例在并发批次中串 case。
_TURN_FACTS: ContextVar[Optional[Dict[str, Any]]] = ContextVar("live_turn_facts", default=None)


class LiveServiceUnavailableError(RuntimeError):
    """业务服务不可达；区别于 request/output schema 等协议实现错误。"""


LIVE_SERVICE_UNAVAILABLE = "live_service_unavailable"
LIVE_HTTP_ERROR = "live_http_error"
LIVE_PROTOCOL_ERROR = "live_protocol_error"


def live_failure_type(exc: BaseException) -> str:
    """投递失败三分：不可达（可补跑）/ 业务已响应但非 2xx（被测系统调用失败）/ 其余协议实现错误。

    LiveHTTPStatusError 继承 URLError/OSError，必须先判，否则会被当成不可达。
    """
    if isinstance(exc, LiveHTTPStatusError):
        return LIVE_HTTP_ERROR
    if isinstance(exc, (LiveServiceUnavailableError, OSError)):
        return LIVE_SERVICE_UNAVAILABLE
    return LIVE_PROTOCOL_ERROR


def business_call_failure(trace: Any) -> str:
    """被测系统已响应但以非 2xx 拒绝时返回失败原文（含状态码与响应体），否则空串。"""
    for fallback in getattr(trace, "fallbacks", None) or []:
        if LIVE_HTTP_ERROR in (getattr(fallback, "quality_flags", None) or []):
            return str(getattr(fallback, "reason", "") or LIVE_HTTP_ERROR)
    return ""


class _LiveProtocol(ABC):
    """协议层：Live 投递主流程的具体实现。

    主流程（execute_live 模板方法）：
    所有项目统一走 Session + Driver 路径（spec/mock/protocol.md 协议 A）。
    返回 EXTRACT_OUTPUT_SCHEMA，不背 trace 字段。

    项目不能修改流程的执行顺序。
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'execute_live',
        '_validate_request',
        '_validate_output',
        '_has_provided_output',
        'deliver_turn',
        '_run_provided',
        '_build_fallback',
        '_append_validation',
        '_take_turn_facts',
    })

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    @typing_final
    def execute_live(
        self,
        initial_request: Dict[str, Any],
        ctx: "TraceContext",
        intent: Optional["MockIntentOutput"] = None,
    ) -> Dict[str, Any]:
        """模板方法：完整调用入口，首轮 Request 必填，Intent 可选。

        所有项目统一走 Session + Driver 路径（spec/mock/protocol.md 协议 A）。
        通过 ctx.record_turn() 上报每轮过程事实，由 trace 层收集。
        """
        turn_count_before = int(getattr(ctx, "turn_count", 0) or 0)
        try:
            return self._execute_via_session(initial_request, ctx, intent)
        except Exception as exc:
            # build request / request schema 等在 record_turn 前失败时，也必须形成失败 trace，
            # 不能被 trace_from_live 吞成 status=ok 的空输出。
            if int(getattr(ctx, "turn_count", 0) or 0) == turn_count_before:
                ctx.record_execution_error(str(exc))
            raise

    # === 内部方法：主流程的各个步骤 ===





    def _execute_via_session(
        self,
        initial_request: Dict[str, Any],
        ctx: "TraceContext",
        intent: Optional["MockIntentOutput"],
    ) -> Dict[str, Any]:
        """Session 路径（spec/mock/protocol.md 协议 A）：Session 执行、Driver 驱动。

        - ctx.seed 为 transcript 级 → ReplayDriver 逐字重放。
        - 否则 mock 实现 MultiTurnInteractiveMock 且 max_turns > 1 → PersonaDriver 扮演用户逐轮交互。
        - 否则 → OneShotDriver 单轮执行。
        """
        import uuid

        from impl.core.mock_protocol import MultiTurnInteractiveMock
        from impl.core.session import (
            Driver,
            OneShotDriver,
            PersonaDriver,
            ReplayDriver,
            Session,
            SessionBudget,
            SessionTranslator,
        )

        mock = self._mock_instance()
        seed = ctx.seed if isinstance(getattr(ctx, "seed", None), dict) else None
        if seed is not None:
            max_turns = max(1, len(seed.get("turns") or []))
            session_id = f"replay-{ctx.case_id or 'session'}-{uuid.uuid4().hex[:8]}"
        else:
            max_turns = self.spec.session_max_turns
            session_id = f"interactive-{getattr(intent, 'scenario', '') or ctx.scenario or 'session'}"
        session = Session(
            self,
            ctx,
            session_id=session_id,
            budget=SessionBudget(max_turns=max_turns),
            user_message_extractor=getattr(mock, "extract_mock_message", None),
            translator=mock if isinstance(mock, SessionTranslator) else None,
            initial_request=initial_request,
        )
        if seed is not None:
            driver: Driver = ReplayDriver(seed)
        elif max_turns > 1 and isinstance(mock, MultiTurnInteractiveMock):
            driver = PersonaDriver(mock)
        else:
            driver = OneShotDriver()
        driver.run(session, dict(initial_request or {}), intent)
        if not session.closed:
            session.close("driver_error")
        if session.last_output is None:
            raise RuntimeError(
                f"{self.spec.project_id} execution produced no valid output: {session.last_error or session.stop_reason}"
            )
        return session.last_output

    @staticmethod
    def _has_visible_goal_evidence(output: Any) -> bool:
        """Reject goal_satisfied when the latest user-visible output is structurally empty."""
        if not isinstance(output, dict) or not output:
            return False
        event_summary = output.get("event_summary")
        if isinstance(event_summary, dict):
            if event_summary.get("business_completed") is True:
                return True
            if (
                event_summary.get("business_completed") is False
                and event_summary.get("protocol_completed") is False
            ):
                return False
        for key in ("robot_text", "reply_text", "answer", "content", "text"):
            if str(output.get(key) or "").strip():
                return True
        for key in ("card_summary", "cards", "tool_calls"):
            if output.get(key):
                return True
        stage = str(output.get("stage") or "").strip().lower()
        return bool(stage and stage not in {"unknown", "empty", "error", "failed"})

    def _validate_request(self, payload: Any) -> Optional[ExecutionTraceEvent]:
        """内部方法：使用 live_schema 校验请求。校验失败抛 ValueError，不降级。"""
        if self.live_schema is None or not hasattr(self.live_schema, "check"):
            return None
        try:
            ok = bool(self.live_schema.check.request(payload))
            if ok:
                return ExecutionTraceEvent(
                    stage="live_schema.validate_request", status="ok",
                    evidence={"project_id": self.spec.project_id}
                )
            details = []
            if hasattr(self.live_schema.check, "request_errors"):
                details = list(self.live_schema.check.request_errors(payload) or [])
            detail_text = f" errors: {'; '.join(details)}" if details else ""
            raise ValueError(
                f"[live_schema] request check failed for {self.spec.project_id}: "
                f"request 不符合 live_schema.REQUEST_SCHEMA。payload keys: "
                f"{list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}"
                f"{detail_text}"
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                f"[live_schema] request check exception for {self.spec.project_id}: {exc}"
            ) from exc

    def _validate_output(self, payload: Any) -> Optional[ExecutionTraceEvent]:
        """内部方法：使用 live_schema 校验输出。校验失败抛 ValueError，不降级。"""
        if self.live_schema is None or not hasattr(self.live_schema, "check"):
            return None
        try:
            ok = bool(self.live_schema.check.output(payload))
            if ok:
                return ExecutionTraceEvent(
                    stage="live_schema.validate_output", status="ok",
                    evidence={"project_id": self.spec.project_id}
                )
            raise ValueError(
                f"[live_schema] output check failed for {self.spec.project_id}: "
                f"output 不符合 live_schema.EXTRACT_OUTPUT_SCHEMA。payload keys: "
                f"{list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}"
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                f"[live_schema] output check exception for {self.spec.project_id}: {exc}"
            ) from exc

    def _has_provided_output(self) -> bool:
        """内部方法：判断是否走 provided 路径。

        条件：
        1. 当前 Live 实例是 ProvidedOutputLive 子类（具备 deliver_provided 能力）
        2. spec.runtime.ready 声明了 output ready
        """
        from impl.core.live_protocol import ProvidedOutputLive
        if not isinstance(self, ProvidedOutputLive):
            return False
        ready = self.spec.ready if self.spec is not None else []
        return "output" in ready

    def _run_provided(
        self,
        request: Dict[str, Any],
    ) -> tuple:
        """内部方法：provided 路径。返回 output/raw_response/error/fallbacks/validations/request。"""
        live_request = LiveRequest(
            project_id=self.spec.project_id,
            raw_input={},
            case_id=str(request.get("case_id") or ""),
            normalized_request=request,
            execution_mode="provided",
            session_id="",
        )
        try:
            request_validation = self._validate_request(request)
            raw_response = self.deliver_provided(live_request)
            output = self.extract_output(raw_response, live_request)
            output_validation = self._validate_output(output)
            return output, raw_response, None, [], [request_validation, output_validation], live_request
        except Exception as exc:
            fallback = self._build_fallback(live_request, str(exc), LIVE_PROTOCOL_ERROR)
            return {}, None, str(exc), [fallback], [], live_request

    def _build_fallback(self, request: Any, reason: str, failure_type: str) -> FallbackDecision:
        """内部方法：构建错误 fallback 决策。"""
        from impl.core.live import fallback_decision
        unavailable = failure_type == LIVE_SERVICE_UNAVAILABLE
        case_id = getattr(request, "case_id", "") if hasattr(request, "case_id") else str(request.get("case_id", "") if isinstance(request, dict) else "")
        session_id = getattr(request, "session_id", "") if hasattr(request, "session_id") else ""
        return fallback_decision(
            fallback_id=f"live-error-{case_id or self.spec.project_id}",
            source_stage="live",
            fallback_type="live_error",
            status="error",
            reason=reason,
            missing_evidence=["live_response"] if unavailable else ["valid_live_response"],
            recoverable=unavailable,
            needs_human_review=True,
            quality_flags=[failure_type],
            metadata={"case_id": case_id, "session_id": session_id, "failure_type": failure_type},
        )

    def _append_validation(
        self,
        target_execution_trace: List[ExecutionTraceEvent],
        event: Optional[ExecutionTraceEvent],
    ) -> None:
        """内部方法：挂载校验结果到 execution_trace。"""
        if event is not None:
            target_execution_trace.append(event)

    # === 扩展点：项目可选覆盖 ===

    @typing_final
    def deliver_turn(self, request: Any) -> Dict[str, Any]:
        """单次 real 投递（spec 第十节）。@final，项目不覆盖。

        内部流程：
        1. 校验 request 符合 REQUEST_SCHEMA
        2. 创建公共 LiveTransport，deliver_real(request, transport) 返回同一个 transport
        3. seal transport，从贡献响应生成 raw_response: list[Any]
        4. extract_output(raw_response) → EXTRACT_OUTPUT_SCHEMA
        5. 校验 output 符合 EXTRACT_OUTPUT_SCHEMA
        6. 返回 EXTRACT_OUTPUT_SCHEMA

        raw_response 和校验事件仅保存在当前执行上下文，供 execute_live 上报 TraceContext；
        不写入共享 Live 实例字段，避免并发 case 串数据。
        """
        # provided 路径：直接走 deliver_provided，不调 deliver_real。
        if self._has_provided_output():
            output, raw_response, error, fallbacks, validations, delivery_request = self._run_provided(request)
            if error is not None:
                raise RuntimeError(error)
            _TURN_FACTS.set({
                "raw_response": raw_response,
                "live_exchanges": [],
                "validation": validations,
            })
            return output

        _TURN_FACTS.set(None)
        request_validation = self._validate_request(request)
        _TURN_FACTS.set({
            "raw_response": None,
            "live_exchanges": [],
            "validation": [event for event in (request_validation,) if event is not None],
        })
        transport = LiveTransport()
        try:
            returned_transport = self.deliver_real(request, transport)
            if returned_transport is not transport:
                raise RuntimeError("deliver_real must return the LiveTransport provided by LiveProtocol")
            transport.seal()
            validate_real_transport(transport, request)
            raw_response = transport.raw_responses()
            output = self.extract_output(raw_response)
        except Exception:
            if not transport.sealed:
                transport.seal()
            _TURN_FACTS.set({
                "raw_response": transport.raw_responses(),
                "live_exchanges": transport.exchanges,
                "validation": [event for event in (request_validation,) if event is not None],
            })
            raise
        _TURN_FACTS.set({
            "raw_response": raw_response,
            "live_exchanges": transport.exchanges,
            "validation": [event for event in (request_validation,) if event is not None],
        })
        output_validation = self._validate_output(output)
        _TURN_FACTS.set({
            "raw_response": raw_response,
            "live_exchanges": transport.exchanges,
            "validation": [event for event in (request_validation, output_validation) if event is not None],
        })
        return output

    def _take_turn_facts(self) -> Dict[str, Any]:
        facts = _TURN_FACTS.get() or {}
        _TURN_FACTS.set(None)
        return dict(facts)

    def _mock_instance(self) -> Any:
        """获取同项目的 Mock 实例。通过 _adapter.mock() 访问。"""
        adapter = getattr(self, "_adapter", None)
        if adapter is None:
            raise RuntimeError(
                f"{self.__class__.__name__} 缺少 _adapter，"
                f"Pipeline 应在加载 Live 时注入 adapter 引用"
            )
        return adapter.mock()

    def _resolve_intent(self, case: SingleTurnCase | MultiTurnCase | Dict[str, Any], mock: Any) -> Optional["MockIntentOutput"]:
        """只读取 Case 明确携带的可选 Intent；不从 Request 或 scenario 补造。"""
        from impl.core.schema import MockIntentOutput
        if isinstance(case, dict):
            case_user_intent = str(case.get("user_intent") or "")
            case_metadata = dict(case.get("metadata") or {})
            case_input = case.get("input") if isinstance(case.get("input"), dict) else {}
            case_user_context = case_metadata.get("user_context") if isinstance(case_metadata.get("user_context"), dict) else {}
            scenario = str(case.get("scenario") or "")
        else:
            case_user_intent = str(getattr(case, "user_intent", "") or "")
            case_metadata = dict(getattr(case, "metadata", {}) or {})
            case_user_context = case_metadata.get("user_context") if isinstance(case_metadata.get("user_context"), dict) else {}
            scenario = str(getattr(case, "scenario", "") or "")
            case_input = dict(getattr(case, "input", {}) or {})

        stored_intent = case_metadata.get("mock_intent") if isinstance(case_metadata.get("mock_intent"), dict) else {}
        query = str(
            stored_intent.get("query")
            or
            case_input.get("query")
            or case_input.get("user_text")
            or case_input.get("question")
            or case_input.get("content")
            or ""
        )
        if not query and case_user_intent and hasattr(mock, "extract_mock_message"):
            query = str(mock.extract_mock_message(case_input) or "")
        if (stored_intent and stored_intent.get("user_intent") and stored_intent.get("query")) or (case_user_intent and query):
            return MockIntentOutput(
                user_intent=str(stored_intent.get("user_intent") or case_user_intent or query),
                query=query,
                user_context=dict(stored_intent.get("user_context") or case_user_context or {}),
                system_understanding=str(stored_intent.get("system_understanding") or ""),
                scenario=str(stored_intent.get("scenario") or scenario),
            )
        return None

    def deliver_real(self, request: Any, transport: LiveTransport) -> LiveTransport:
        """扩展点：真实投递。项目可选覆盖。

        定位/目标：
            使用公共 transport 调用业务系统并返回传入的同一个 transport。
            这是 Live 的核心业务知识——如何调用业务系统无法通用化，必须由项目实现。

        参数：
            request: REQUEST_SCHEMA 形状（项目特定 dict 或 LiveRequest）
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 未实现 deliver_real，"
            f"无法调用业务系统。如果是 provided-output 项目，请继承 ProvidedOutputLive。"
        )

    def deliver_provided(self, request: LiveRequest) -> Any:
        """扩展点：provided 投递。项目可选覆盖。

        定位/目标：
            从 case.output 取 raw_response（provided-output 模式）。
            provided-output 项目必须实现。

        参数：
            request: LiveRequest，含 normalized_request 等。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 未实现 deliver_provided，"
            f"无法从 case 取 provided output。如果是真实服务项目，请继承 RealServiceLive。"
        )

    def deliver_stub(self, request: Any) -> Optional[Dict[str, Any]]:
        """扩展点：stub 投递。项目可选覆盖。默认返回 None。"""
        return None

    def extract_output(self, raw_response: Any, request: Any = None) -> Dict[str, Any]:
        """provided-output 兼容扩展点；RealServiceLive 必须实现单参数版本。"""
        if isinstance(raw_response, dict):
            return raw_response
        return {}

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: Any) -> Dict[str, Any]:
        """扩展点：应用边界。项目可选覆盖。"""
        return {}

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: Any, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        """扩展点：项目字段。项目可选覆盖。"""
        return {}

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: Any) -> List[ExecutionTraceEvent]:
        """扩展点：构建执行轨迹。项目可选覆盖。"""
        return []

    def normalize_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """扩展点：后处理结果。项目可选覆盖。"""
        return result

    def _summarize_assistant(self, extracted: Dict[str, Any]) -> str:
        """默认助手摘要（通用）。项目可覆盖以补充项目特化字段。"""
        if not extracted:
            return "empty"
        keys = [k for k in ("stage", "status") if extracted.get(k)]
        if keys:
            return " · ".join(f"{k}={extracted[k]}" for k in keys)
        return "ok"


class ProjectLive(_LiveProtocol):
    """操作层：告诉项目哪些地方可以定制。

    必须实现：
    - deliver_real 或 deliver_provided（二选一，通过继承中间基类指定）

    可选覆盖：
    - deliver_stub
    - extract_output / application_boundary / project_fields / build_execution_trace
    - normalize_result
    - _summarize_assistant（多轮项目）
    """

    def __init__(self, spec: ProjectSpec):
        """初始化 ProjectLive。"""
        self.spec = spec
        # 集成 live_schema：协议层统一加载和使用
        self.live_schema = None
        if spec is not None:
            from impl.core.mock_agent import load_live_schema
            self.live_schema = load_live_schema(spec.project_id)


class RealServiceLive(ProjectLive):
    """真实服务项目继承这个类。

    deliver_real / extract_output 是 @abstractmethod（必须实现）。
    deliver_provided 有默认实现（raise NotImplementedError）。

    继承此类后，项目只需实现 deliver_real，不需要实现 deliver_provided。
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        expected = {"deliver_real": ["self", "request", "transport"], "extract_output": ["self", "raw_response"]}
        for method_name, parameter_names in expected.items():
            method = cls.__dict__.get(method_name)
            if method is None:
                continue
            actual = list(inspect.signature(method).parameters)
            if actual != parameter_names:
                raise TypeError(
                    f"{cls.__name__}.{method_name} signature must be "
                    f"({', '.join(parameter_names)}), got ({', '.join(actual)})"
                )

    @abstractmethod
    def deliver_real(self, request: Any, transport: LiveTransport) -> LiveTransport:
        """扩展点：真实投递。项目必须实现。"""
        pass

    @abstractmethod
    def extract_output(self, raw_response: list[Any]) -> Dict[str, Any]:
        """只从公共层生成的真实响应列表提取 EXTRACT_OUTPUT_SCHEMA。"""
        pass


class ProvidedOutputLive(ProjectLive):
    """provided-output 项目继承这个类。

    deliver_provided 是 @abstractmethod（必须实现）。
    deliver_real 有默认实现（raise NotImplementedError）。

    继承此类后，项目只需实现 deliver_provided，不需要实现 deliver_real。
    """

    @abstractmethod
    def deliver_provided(self, request: LiveRequest) -> Any:
        """扩展点：provided 投递。项目必须实现。"""
        pass






