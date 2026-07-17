"""Live 协议层和扩展点基类

四层文件关系：
- live_protocol.py: 协议层（_LiveProtocol，主流程实现）+ 操作层（ProjectLive，扩展点）
- live.py: 通用层（工具函数：fallback_decision 等）
- projects/<project>/live.py: 项目层（实现扩展点）
"""
from __future__ import annotations
import logging
import time
from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Optional, Dict, List
from typing import final as typing_final
if TYPE_CHECKING:
    from impl.core.mock_agent import LiveSchema
    from impl.core.trace import TraceContext
    from impl.core.schema import MockIntentOutput
from impl.core.schema import (
    ExecutionTraceEvent, FallbackDecision,
    LiveMultiTurnState, LiveRequest,
    ProjectSpec, SingleTurnCase, MultiTurnCase, MultiTurnInteraction,
    to_dict,
)
from impl.core.protocol_base import check_forbidden_overrides

logger = logging.getLogger(__name__)

# deliver_turn 的公开返回值保持 EXTRACT_OUTPUT_SCHEMA；raw_response/validation 等执行事实
# 仅在当前执行上下文内临时传给 execute_live，避免 adapter 缓存的 Live 实例在并发批次中串 case。
_TURN_FACTS: ContextVar[Optional[Dict[str, Any]]] = ContextVar("live_turn_facts", default=None)


class LiveServiceUnavailableError(RuntimeError):
    """业务服务不可达；区别于 request/output schema 等协议实现错误。"""


class _LiveProtocol(ABC):
    """协议层：Live 投递主流程的具体实现。

    主流程（execute_live 模板方法）：
    1. 通过 TraceContext 上报过程事实（由 trace 层注入）
    2. 判断单轮/多轮（isinstance MultiTurnInteractiveLive）
    3. 单轮：build_live_request → deliver_turn（real 路径）或 deliver_provided（provided 路径）
    4. 多轮：循环 build_next_request → deliver_turn，停止判断只用 mock.should_stop
    5. 返回 EXTRACT_OUTPUT_SCHEMA，不背 trace 字段

    项目不能修改流程的执行顺序。
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'execute_live',
        '_execute_single_turn',
        '_execute_multi_turn',
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
        intent: "MockIntentOutput",
        ctx: "TraceContext",
    ) -> Dict[str, Any]:
        """模板方法：完整调用入口，输入 intent + ctx，输出 EXTRACT_OUTPUT_SCHEMA。

        流程（spec/adapter/trace.md 第八节）：
        1. 判断单轮/多轮（isinstance MultiTurnInteractiveLive）
        2. 单轮：调 _execute_single_turn
        3. 多轮：调 _execute_multi_turn

        通过 ctx.record_turn() 上报每轮过程事实，由 trace 层收集。
        """
        turn_count_before = int(getattr(ctx, "turn_count", 0) or 0)
        try:
            if isinstance(self, MultiTurnInteractiveLive):
                return self._execute_multi_turn(intent, ctx)
            return self._execute_single_turn(intent, ctx)
        except Exception as exc:
            # build request / request schema 等在 record_turn 前失败时，也必须形成失败 trace，
            # 不能被 trace_from_live 吞成 status=ok 的空输出。
            if int(getattr(ctx, "turn_count", 0) or 0) == turn_count_before:
                ctx.record_execution_error(str(exc))
            raise

    # === 内部方法：主流程的各个步骤 ===

    def _execute_single_turn(
        self,
        intent: "MockIntentOutput",
        ctx: "TraceContext",
    ) -> Dict[str, Any]:
        """单轮执行路径。"""
        mock = self._mock_instance()
        request = mock.build_live_request(intent)
        # 判断走 provided 还是 real：_has_provided_output 已检查 spec ready + ProvidedOutputLive
        if self._has_provided_output():
            # provided 路径：不走 deliver_turn，由 deliver_provided → extract_output → 校验
            output, raw_response, error, fallbacks, validations, delivery_request = self._run_provided(request)
            application_boundary = self.application_boundary(raw_response, output, delivery_request) if error is None else {}
            project_fields = self.project_fields(raw_response, output, delivery_request, application_boundary) if error is None else {}
            execution_trace = self.build_execution_trace(raw_response, output, delivery_request) if error is None else []
            ctx.record_turn(
                request=request,
                raw_response=raw_response,
                extracted_output=output,
                call_status="succeeded" if error is None else "failed",
                runtime_ms=None,
                error=error,
                fallbacks=fallbacks,
                validation=validations,
                execution_trace=execution_trace,
                application_boundary=application_boundary,
                project_fields=project_fields,
            )
            ctx.finish_execution(
                stop_reason="single_turn_completed" if error is None else "execution_error",
                transcript=[],
                final_output_turn=1 if error is None else None,
                completion_status="completed" if error is None else "failed",
            )
            return output

        # real 路径：调 deliver_turn（deliver_real → extract_output → 校验）
        start = time.time()
        try:
            output = self.deliver_turn(request)
            runtime_ms = int((time.time() - start) * 1000)
            facts = self._take_turn_facts()
            raw_response = facts.get("raw_response")
            application_boundary = self.application_boundary(raw_response, output, request)
            project_fields = self.project_fields(raw_response, output, request, application_boundary)
            execution_trace = list(facts.get("validation") or []) + list(self.build_execution_trace(raw_response, output, request) or [])
            ctx.record_turn(
                request=request,
                raw_response=raw_response,
                extracted_output=output,
                call_status="succeeded",
                runtime_ms=runtime_ms,
                error=None,
                fallbacks=[],
                validation=[],
                execution_trace=execution_trace,
                application_boundary=application_boundary,
                project_fields=project_fields,
            )
            ctx.finish_execution(
                stop_reason="single_turn_completed",
                transcript=[],
                final_output_turn=1,
                completion_status="completed",
            )
            return output
        except Exception as exc:
            runtime_ms = int((time.time() - start) * 1000)
            facts = self._take_turn_facts()
            fallback = self._build_fallback(request, str(exc), unavailable=isinstance(exc, (LiveServiceUnavailableError, OSError)))
            ctx.record_turn(
                request=request,
                raw_response=facts.get("raw_response"),
                extracted_output={},
                call_status="failed",
                runtime_ms=runtime_ms,
                error=str(exc),
                fallbacks=[fallback],
                validation=list(facts.get("validation") or []),
            )
            ctx.finish_execution(
                stop_reason="execution_error",
                transcript=[],
                final_output_turn=None,
                completion_status="failed",
            )
            raise

    def _execute_multi_turn(
        self,
        intent: "MockIntentOutput",
        ctx: "TraceContext",
    ) -> Dict[str, Any]:
        """多轮执行路径：循环 build_next_request → deliver_turn，停止只用 mock.should_stop。

        主循环在 execute_live 内部（spec 第十一节 2）。TraceContext 收集每轮过程事实。
        每轮 output 独立符合 EXTRACT_OUTPUT_SCHEMA；完整轮次事实只进入 TraceContext。
        """
        mock = self._mock_for_multi_turn()
        max_turns = max(1, int(mock.max_turns() if hasattr(mock, "max_turns") else 4))

        extracted_turns: List[Dict[str, Any]] = []
        transcript: List[Dict[str, Any]] = []
        last_output: Optional[Dict[str, Any]] = None
        stop_reason = "max_turns"
        session_id = f"interactive-{getattr(intent, 'scenario', '') or 'session'}"

        accumulated: Optional[Dict[str, Any]] = None
        for turn_index in range(max_turns):
            # build_next_request：首轮 accumulated=None，后续轮看上一轮累积
            try:
                request = mock.build_next_request(intent, accumulated)
            except Exception as exc:
                logger.warning("mock.build_next_request failed at turn %d: %s", turn_index + 1, exc, exc_info=True)
                request = None
            if not isinstance(request, dict) or not request:
                goal = str(getattr(intent, "query", "") or "")
                request = {"query": goal}

            user_query = str(request.get("query") or request.get("content") or "")
            transcript.append({"role": "user", "content": user_query, "query": user_query})

            start = time.time()
            try:
                output = self.deliver_turn(request)
                runtime_ms = int((time.time() - start) * 1000)
                facts = self._take_turn_facts()
                raw_response = facts.get("raw_response")
                application_boundary = self.application_boundary(raw_response, output, request)
                project_fields = self.project_fields(raw_response, output, request, application_boundary)
                execution_trace = list(facts.get("validation") or []) + list(self.build_execution_trace(raw_response, output, request) or [])
                ctx.record_turn(
                    request=request,
                    raw_response=raw_response,
                    extracted_output=output,
                    call_status="succeeded",
                    runtime_ms=runtime_ms,
                    error=None,
                    fallbacks=[],
                    validation=[],
                    execution_trace=execution_trace,
                    application_boundary=application_boundary,
                    project_fields=project_fields,
                )
                extracted_turns.append(output)
                last_output = output
            except Exception as exc:
                runtime_ms = int((time.time() - start) * 1000)
                facts = self._take_turn_facts()
                fallback = self._build_fallback(request, str(exc), unavailable=isinstance(exc, (LiveServiceUnavailableError, OSError)))
                ctx.record_turn(
                    request=request,
                    raw_response=facts.get("raw_response"),
                    extracted_output={},
                    call_status="failed",
                    runtime_ms=runtime_ms,
                    error=str(exc),
                    fallbacks=[fallback],
                    validation=list(facts.get("validation") or []),
                )
                stop_reason = "live_error"
                break

            # 累积：本轮 output 和 transcript，供下一轮 build_next_request
            accumulated = {
                "turns": extracted_turns,
                "transcript": transcript,
                "last_output": last_output,
            }
            transcript.append({
                "role": "assistant",
                "content": self._summarize_assistant(output),
                "stage": output.get("stage") if isinstance(output, dict) else None,
            })

            # 停止判断：只用 mock.should_stop（spec 第十一节 9）
            if hasattr(mock, "should_stop") and mock.should_stop(transcript, last_output):
                stop_reason = "mock_should_stop"
                break

        final_output_turn = len(extracted_turns) if last_output is not None else None
        completion_status = "completed" if last_output is not None and stop_reason != "live_error" else "failed"
        ctx.finish_execution(
            session_id=session_id,
            stop_reason=stop_reason,
            transcript=transcript,
            final_output_turn=final_output_turn,
            completion_status=completion_status,
        )
        if last_output is None:
            raise RuntimeError(f"{self.spec.project_id} multi-turn execution produced no valid output")
        # 多轮返回最后一轮有效的项目 EXTRACT_OUTPUT_SCHEMA；完整 turns 由 TraceContext 持有。
        return last_output

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
            raise ValueError(
                f"[live_schema] request check failed for {self.spec.project_id}: "
                f"request 不符合 live_schema.REQUEST_SCHEMA。payload keys: "
                f"{list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}"
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
        2. spec.common.ready 声明了 output ready
        """
        from impl.core.live_protocol import ProvidedOutputLive
        if not isinstance(self, ProvidedOutputLive):
            return False
        ready = self.spec.common.get("ready", []) if self.spec and isinstance(self.spec.common, dict) else []
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
            fallback = self._build_fallback(live_request, str(exc), unavailable=False)
            return {}, None, str(exc), [fallback], [], live_request

    def _build_fallback(self, request: Any, reason: str, unavailable: bool = True) -> FallbackDecision:
        """内部方法：构建错误 fallback 决策。"""
        from impl.core.live import fallback_decision
        failure_type = "live_service_unavailable" if unavailable else "live_protocol_error"
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
        2. deliver_real(request) → raw_response
        3. extract_output(raw_response, request) → EXTRACT_OUTPUT_SCHEMA
        4. 校验 output 符合 EXTRACT_OUTPUT_SCHEMA
        5. 返回 EXTRACT_OUTPUT_SCHEMA

        raw_response 和校验事件仅保存在当前执行上下文，供 execute_live 上报 TraceContext；
        不写入共享 Live 实例字段，避免并发 case 串数据。
        """
        _TURN_FACTS.set(None)
        request_validation = self._validate_request(request)
        _TURN_FACTS.set({
            "raw_response": None,
            "validation": [event for event in (request_validation,) if event is not None],
        })
        raw_response = self.deliver_real(request)
        output = self.extract_output(raw_response, request)
        _TURN_FACTS.set({
            "raw_response": raw_response,
            "validation": [event for event in (request_validation,) if event is not None],
        })
        output_validation = self._validate_output(output)
        _TURN_FACTS.set({
            "raw_response": raw_response,
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

    def _resolve_intent(self, case: SingleTurnCase | MultiTurnCase | Dict[str, Any], mock: Any) -> "MockIntentOutput":
        """算意图：优先从 case 取，不足则调 mock.build_user_intent 补充。

        case 已有意图（case.user_intent 有值）时直接构造 MockIntentOutput，
        避免重复 LLM 调用；case 没有意图时调 mock.build_user_intent(scenario) 跑一次 LLM。
        """
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

        query = str(
            case_input.get("query")
            or case_input.get("user_text")
            or case_input.get("question")
            or case_input.get("content")
            or ""
        )
        # Persisted/imported cases already carry the authoritative user request.
        # Do not replace it with a newly generated scenario example merely because
        # the optional user_intent description is absent.
        if case_user_intent or case_input:
            return MockIntentOutput(
                user_intent=case_user_intent or query,
                query=query,
                user_context=dict(case_user_context or {}),
                scenario=scenario,
            )
        return mock.build_user_intent(scenario)

    def deliver_real(self, request: Any) -> Any:
        """扩展点：真实投递。项目可选覆盖。

        定位/目标：
            调用业务系统（真实 API / 服务），返回 raw_response。
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

    def extract_output(self, raw_response: Any, request: Any) -> Dict[str, Any]:
        """扩展点：提取输出。项目可选覆盖。"""
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

    deliver_real 是 @abstractmethod（必须实现）。
    deliver_provided 有默认实现（raise NotImplementedError）。

    继承此类后，项目只需实现 deliver_real，不需要实现 deliver_provided。
    """

    @abstractmethod
    def deliver_real(self, request: Any) -> Any:
        """扩展点：真实投递。项目必须实现。"""
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


class SingleTurnLive:
    """单轮交互模式 mixin。项目 Live 通过组合继承声明单轮形态。

    使用方式：
        class XxxLive(RealServiceLive, SingleTurnLive): ...
        class XxxLive(ProvidedOutputLive, SingleTurnLive): ...

    单轮 Live 不进入多轮主循环。execute_live 通过 isinstance(self, MultiTurnInteractiveLive)
    判断是否走多轮路径；不继承 MultiTurnInteractiveLive 即视为单轮。
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'deliver_multi_turn',  # 已废弃（trace.md 第十二节删除项）；单轮项目不应实现
    })

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)


class MultiTurnInteractiveLive:
    """多轮交互模式 mixin。声明 execute_live 走多轮路径（_execute_multi_turn）。

    使用方式：
        class XxxLive(RealServiceLive, MultiTurnInteractiveLive): ...
        class XxxLive(ProvidedOutputLive, MultiTurnInteractiveLive): ...

    协议层提供的（项目不能覆盖）：
    - execute_live: 完整调用入口（@final，在 _LiveProtocol）
    - _execute_multi_turn: 多轮主循环（@final，在 _LiveProtocol）
    - deliver_turn: 单次 real 投递（@final，在 _LiveProtocol）

    协议层提供的默认实现（项目可选覆盖以注入项目特化语义）：
    - _summarize_assistant: 默认通用摘要

    项目必须实现（继承自 RealServiceLive / ProvidedOutputLive）：
    - deliver_real 或 deliver_provided

    项目不应该实现：
    - 多轮主循环、transcript 累积、停止判断（停止判断在 mock.should_stop）
    - judge/attribute 调用、run payload 组装

    多轮主循环在 execute_live 内部（spec 第十一节 2），不再抽出独立的 deliver_multi_turn 模板方法
    （spec 第十二节明确删除项）。多轮过程事实通过 TraceContext 上报，trace 层收集。
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'deliver_multi_turn',  # 已废弃（trace.md 第十二节删除项），多轮主循环合并到 execute_live 内部
    })

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    def _mock_for_multi_turn(self) -> Any:
        """获取同项目的 Mock 实例（多轮主循环用）。复用单轮的 _mock_instance。"""
        return self._mock_instance()
