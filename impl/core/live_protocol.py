"""Live 协议层和扩展点基类

四层文件关系：
- live_protocol.py: 协议层（_LiveProtocol，主流程实现）+ 操作层（ProjectLive，扩展点）
- live.py: 通用层（工具函数：fallback_decision, generate_live_output_with_check 等）
- projects/<project>/live.py: 项目层（实现扩展点）
"""
from __future__ import annotations
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from typing import final as typing_final
from impl.core.schema import (
    RunTrace, LiveExecutionResult, ExecutionTraceEvent, FallbackDecision,
    LiveMultiTurnResult, LiveMultiTurnState, LiveRequest,
    ProjectSpec, SingleTurnCase, MultiTurnCase, MultiTurnInteraction,
    normalize_live_execution_result, to_dict,
)
from impl.core.protocol_base import check_forbidden_overrides

logger = logging.getLogger(__name__)


class _LiveProtocol(ABC):
    """
    协议层：Live 投递主流程的具体实现。

    主流程（deliver 模板方法）：
    1. 构建请求（扩展点 build_request）
    2. 校验请求（内部方法 _validate_request，使用 live_schema）
    3. 判断投递路径（内部方法 _has_provided_output）
    4. 执行投递（内部方法 _run_provided / _run_real_or_fallback）
    5. 应用交互状态（内部方法 _apply_interaction_state，多轮处理）
    6. 后处理（扩展点 normalize_result）

    需要工具时从通用层取，需要项目定制时调用扩展点。
    项目不能修改流程的执行顺序。
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'deliver',
        '_validate_request',
        '_validate_output',
        '_has_provided_output',
        '_run_provided',
        '_run_real_or_fallback',
        '_candidate_to_result',
        '_result_from_raw',
        '_failed_live_result',
        '_make_live_error_fallback',
        '_apply_interaction_state',
        '_multi_turn_accumulated_fields',
        '_live_multi_turn_result',
        '_append_validation',
        '_build_request',
    })

    def __init_subclass__(cls, **kwargs):
        """检查子类是否覆盖了禁止的方法"""
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    @typing_final
    def deliver(
        self,
        case: SingleTurnCase | MultiTurnCase,
        contract: Optional[MultiTurnInteraction] = None,
    ) -> LiveExecutionResult:
        """
        模板方法：Live 投递主流程的具体实现。

        流程：
        1. 构建请求（扩展点 + 内部方法）
        2. 校验请求（内部方法，使用 live_schema）
        3. 判断投递路径并执行（内部方法）
        4. 应用交互状态（内部方法，多轮处理）
        5. 后处理（扩展点）
        """
        # 1. 构建请求（内部方法，调用扩展点 build_request）
        request = self._build_request(case)

        # 2. 判断投递路径并执行（内部方法）
        if self._has_provided_output(case, request):
            result = self._run_provided(case, request)
        else:
            result = self._run_real_or_fallback(case, request)

        # 3. 应用交互状态（内部方法，多轮处理）
        self._apply_interaction_state(result, request, contract)

        # 4. 后处理（扩展点）
        final_result = self.normalize_result(result)

        return final_result

    # === 内部方法：主流程的各个步骤 ===

    def _build_request(self, case: SingleTurnCase | MultiTurnCase) -> LiveRequest:
        """内部方法：构建 LiveRequest。调用扩展点 build_request。"""
        normalized = self.build_request(case)
        return LiveRequest(
            project_id=self.spec.project_id,
            raw_input=dict(getattr(case, "input", {}) or {}),
            case_id=str(getattr(case, "id", "") or ""),
            normalized_request=normalized if isinstance(normalized, dict) else {},
        )

    def _validate_request(self, payload: Any) -> Optional[ExecutionTraceEvent]:
        """内部方法：使用 live_schema 校验请求。"""
        if self.live_schema is None or not hasattr(self.live_schema, "check"):
            return None
        try:
            ok = bool(self.live_schema.check.request(payload))
            if ok:
                return ExecutionTraceEvent(
                    stage="live_schema.validate_request", status="ok",
                    evidence={"project_id": self.spec.project_id}
                )
            evidence = {"project_id": self.spec.project_id, "kind": "request", "error": "request 不符合 live_schema"}
            logger.warning(f"[live_schema] request check failed for {self.spec.project_id}: {evidence['error']}")
            return ExecutionTraceEvent(stage="live_schema.validate_request", status="failed", evidence=evidence)
        except Exception as exc:
            logger.warning(f"[live_schema] request check exception for {self.spec.project_id}: {exc}")
            return ExecutionTraceEvent(
                stage="live_schema.validate_request", status="failed",
                evidence={"project_id": self.spec.project_id, "kind": "request", "error": str(exc)}
            )

    def _validate_output(self, payload: Any) -> Optional[ExecutionTraceEvent]:
        """内部方法：使用 live_schema 校验输出。"""
        if self.live_schema is None or not hasattr(self.live_schema, "check"):
            return None
        try:
            ok = bool(self.live_schema.check.output(payload))
            if ok:
                return ExecutionTraceEvent(
                    stage="live_schema.validate_output", status="ok",
                    evidence={"project_id": self.spec.project_id}
                )
            evidence = {"project_id": self.spec.project_id, "kind": "output", "error": "output 不符合 live_schema"}
            logger.warning(f"[live_schema] output check failed for {self.spec.project_id}: {evidence['error']}")
            return ExecutionTraceEvent(stage="live_schema.validate_output", status="failed", evidence=evidence)
        except Exception as exc:
            logger.warning(f"[live_schema] output check exception for {self.spec.project_id}: {exc}")
            return ExecutionTraceEvent(
                stage="live_schema.validate_output", status="failed",
                evidence={"project_id": self.spec.project_id, "kind": "output", "error": str(exc)}
            )

    def _has_provided_output(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> bool:
        """内部方法：判断是否走 provided 投递路径。"""
        from impl.core.interaction_protocol import resolve_ready
        if not resolve_ready(self.spec, case).output:
            return False
        output = getattr(case, "output", None)
        if isinstance(output, dict) and output:
            return True
        input_data = dict(getattr(case, "input", {}) or {})
        return any(key in input_data for key in ("raw_response", "response", "output"))

    def _run_provided(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> LiveExecutionResult:
        """内部方法：provided 投递路径。"""
        request_validation = self._validate_request(request.normalized_request)
        setattr(request, "_live_schema_request_validation", request_validation)

        raw_response = self.deliver_provided(case, request)
        extracted_output = self.extract_output(raw_response, request)
        application_boundary = self.application_boundary(raw_response, extracted_output, request)
        result = LiveExecutionResult(
            project_id=self.spec.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            raw_response=raw_response,
            extracted_output=extracted_output,
            output_source="provided_output",
            call_status="succeeded",
            execution_trace=self.build_execution_trace(raw_response, extracted_output, request),
            project_fields=self.project_fields(raw_response, extracted_output, request, application_boundary),
            application_boundary=application_boundary,
            interaction_mode="interactive_intent" if request.turns else "single_turn",
        )
        self._append_validation(result, self._validate_output(extracted_output))
        return result

    def _run_real_or_fallback(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> LiveExecutionResult:
        """内部方法：real 投递路径，带 fallback。"""
        request_validation = self._validate_request(request.normalized_request)
        setattr(request, "_live_schema_request_validation", request_validation)

        start = time.time()
        try:
            candidate = self.deliver_real(request)
        except Exception as exc:
            stub = self.deliver_stub(case, request)
            if stub is not None:
                result = self._result_from_raw(request, stub, "stub", start)
                self._append_validation(result, self._validate_output(result.extracted_output))
                return result
            return self._failed_live_result(request, str(exc))

        result = self._candidate_to_result(request, candidate, start)
        if result.call_status != "succeeded":
            unavailable = result.output_source == "live_service_unavailable"
            if not unavailable and result.output_source in ("", "live_service"):
                result.output_source = "live_protocol_error"
            if not result.fallbacks:
                result.fallbacks = [self._make_live_error_fallback(request, result.call_error or "business service call failed", unavailable=unavailable)]
            self._append_validation(result, None)
            return result
        self._append_validation(result, self._validate_output(result.extracted_output))
        return result

    def _candidate_to_result(self, request: LiveRequest, candidate: Any, start: float) -> LiveExecutionResult:
        """内部方法：将 deliver_real 的候选结果归一化为 LiveExecutionResult。"""
        if isinstance(candidate, LiveExecutionResult):
            result = candidate
        elif isinstance(candidate, dict) and {"project_id", "raw_input", "normalized_request", "extracted_output"}.intersection(candidate):
            result = normalize_live_execution_result(candidate)
            if result is None:
                result = self._result_from_raw(request, candidate, request.execution_mode, start)
        else:
            result = self._result_from_raw(request, candidate, request.execution_mode, start)
        if result.project_id != self.spec.project_id:
            result.project_id = self.spec.project_id
        if not result.case_id:
            result.case_id = request.case_id
        if not result.session_id:
            result.session_id = request.session_id
        if not result.raw_input:
            result.raw_input = request.raw_input
        if not result.normalized_request:
            result.normalized_request = request.normalized_request
        if result.runtime_ms is None:
            result.runtime_ms = int((time.time() - start) * 1000)
        return result

    def _result_from_raw(self, request: LiveRequest, raw_response: Any, output_source: str, start: float) -> LiveExecutionResult:
        """内部方法：从原始响应构建 LiveExecutionResult。"""
        extracted_output = self.extract_output(raw_response, request)
        application_boundary = self.application_boundary(raw_response, extracted_output, request)
        return LiveExecutionResult(
            project_id=self.spec.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            raw_response=raw_response,
            runtime_ms=int((time.time() - start) * 1000),
            extracted_output=extracted_output,
            output_source=output_source,
            execution_trace=self.build_execution_trace(raw_response, extracted_output, request),
            project_fields=self.project_fields(raw_response, extracted_output, request, application_boundary),
            application_boundary=application_boundary,
            interaction_mode="interactive_intent" if request.turns else "single_turn",
        )

    def _failed_live_result(self, request: LiveRequest, reason: str) -> LiveExecutionResult:
        """内部方法：构建失败结果。"""
        fallback = self._make_live_error_fallback(request, reason)
        result = LiveExecutionResult(
            project_id=self.spec.project_id,
            case_id=request.case_id,
            session_id=request.session_id,
            raw_input=request.raw_input,
            normalized_request=request.normalized_request,
            call_status="failed",
            call_error=reason,
            output_source="live_service_unavailable",
            execution_trace=[ExecutionTraceEvent(stage="project.call", status="failed", evidence=reason)],
            interaction_mode="interactive_intent" if request.turns else "single_turn",
            fallbacks=[fallback],
        )
        self._append_validation(result, None)
        return result

    def _make_live_error_fallback(self, request: LiveRequest, reason: str, unavailable: bool = True) -> FallbackDecision:
        """内部方法：构建错误 fallback 决策。"""
        from impl.core.live import fallback_decision
        failure_type = "live_service_unavailable" if unavailable else "live_protocol_error"
        return fallback_decision(
            fallback_id=f"live-error-{request.case_id or self.spec.project_id}",
            source_stage="live",
            fallback_type="live_error",
            status="error",
            reason=reason,
            missing_evidence=["live_response"] if unavailable else ["valid_live_response"],
            recoverable=unavailable,
            needs_human_review=True,
            quality_flags=[failure_type],
            metadata={"case_id": request.case_id, "session_id": request.session_id, "failure_type": failure_type},
        )

    def _multi_turn_accumulated_fields(self, extracted_output: Any) -> Dict[str, Any]:
        """内部方法：提取多轮累积字段。"""
        if not isinstance(extracted_output, dict):
            return {}
        candidates: list[dict[str, Any]] = []
        turns = extracted_output.get("turns")
        if isinstance(turns, list):
            candidates.extend(turn for turn in reversed(turns) if isinstance(turn, dict))
        candidates.append(extracted_output)
        for candidate in candidates:
            session_summary = candidate.get("session_summary") if isinstance(candidate, dict) else None
            if isinstance(session_summary, dict) and isinstance(session_summary.get("accumulated_fields"), dict):
                return dict(session_summary.get("accumulated_fields") or {})
        return {}

    def _apply_interaction_state(self, result: LiveExecutionResult, request: LiveRequest, contract: Optional[MultiTurnInteraction]) -> None:
        """内部方法：应用交互状态（多轮处理）。"""
        if contract is not None:
            result.interaction_mode = contract.mode
        elif request.turns or (isinstance(request.normalized_request, dict) and isinstance(request.normalized_request.get("turns"), list)):
            result.interaction_mode = "interactive_intent"
        if result.interaction_mode == "interactive_intent" or contract is not None:
            turns = request.normalized_request.get("turns") if isinstance(request.normalized_request, dict) else request.turns
            result.multi_turn_state = LiveMultiTurnState(
                session_id=request.session_id,
                transcript=list(turns or request.turns or []),
                accumulated_fields=self._multi_turn_accumulated_fields(result.extracted_output),
                stop_reason="live_error" if result.call_status != "succeeded" else "",
            )
            self._live_multi_turn_result(result)

    def _live_multi_turn_result(self, result: LiveExecutionResult) -> None:
        """内部方法：构建多轮结果。"""
        from impl.core.live import live_multi_turn_result
        live_multi_turn_result(result)

    def _append_validation(self, target: LiveExecutionResult, event: Optional[ExecutionTraceEvent]) -> None:
        """内部方法：挂载校验结果到 execution_trace。"""
        request_event = getattr(target, "_live_schema_request_validation", None)
        if request_event is None and isinstance(target.normalized_request, dict):
            request_event = self._validate_request(target.normalized_request)
        if isinstance(request_event, ExecutionTraceEvent):
            target.execution_trace.append(request_event)
        if event is not None:
            target.execution_trace.append(event)
        diagnostics = [to_dict(item) for item in target.execution_trace if getattr(item, "stage", "").startswith("live_schema.validate_")]
        if diagnostics:
            fields = dict(target.project_fields or {})
            fields["live_schema_validation"] = diagnostics
            target.project_fields = fields

    # === 扩展点：项目可选覆盖 ===

    def build_request(self, case: SingleTurnCase | MultiTurnCase) -> Dict[str, Any]:
        """扩展点：构建请求参数（normalized_request）。项目可选覆盖。

        定位/目标：
            把 case.input 翻译成 live 请求体形状（= live_schema.REQUEST_SCHEMA）。
            mock 直接对接 live_schema，build_request 不做形状翻译，默认透传 case.input。

        参数：
            case: 单轮或多轮用例，含 input/output/scenario 等字段。case.input 形状由 mock 产出。
        """
        return dict(getattr(case, "input", {}) or {})

    def deliver_real(self, request: LiveRequest) -> Any:
        """扩展点：真实投递。项目可选覆盖。

        定位/目标：
            调用业务系统（真实 API / 服务），返回 raw_response。
            这是 Live 的核心业务知识——如何调用业务系统无法通用化，必须由项目实现。
            返回值可以是 raw_response（dict/对象）或完整 LiveExecutionResult。

        参数：
            request: LiveRequest，含 project_id/case_id/raw_input/normalized_request/turns/session_id 等。
                     normalized_request 形状符合 live_schema.REQUEST_SCHEMA。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 未实现 deliver_real，"
            f"无法调用业务系统。如果是 provided-output 项目，请继承 ProvidedOutputLive。"
        )

    def deliver_provided(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        """扩展点：provided 投递。项目可选覆盖。

        定位/目标：
            从 case.output 取 raw_response（provided-output 模式）。
            provided-output 项目必须实现。

        参数：
            case: 单轮或多轮用例，含 output（provided 数据）。
            request: LiveRequest，含 normalized_request 等。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 未实现 deliver_provided，"
            f"无法从 case 取 provided output。如果是真实服务项目，请继承 RealServiceLive。"
        )

    def deliver_stub(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Optional[Dict[str, Any]]:
        """扩展点：stub 投递。项目可选覆盖。默认返回 None。"""
        return None

    def extract_output(self, raw_response: Any, request: LiveRequest) -> Dict[str, Any]:
        """扩展点：提取输出。项目可选覆盖。"""
        if isinstance(raw_response, dict):
            return raw_response
        return {}

    def application_boundary(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> Dict[str, Any]:
        """扩展点：应用边界。项目可选覆盖。"""
        return {}

    def project_fields(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest, application_boundary: Dict[str, Any]) -> Dict[str, Any]:
        """扩展点：项目字段。项目可选覆盖。"""
        return {}

    def build_execution_trace(self, raw_response: Any, extracted_output: Dict[str, Any], request: LiveRequest) -> List[ExecutionTraceEvent]:
        """扩展点：构建执行轨迹。项目可选覆盖。"""
        return []

    def run_interactive(self, case: Any) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.__class__.__name__} 不支持 interactive_intent")

    def normalize_result(self, result: LiveExecutionResult) -> LiveExecutionResult:
        """扩展点：后处理结果。项目可选覆盖。"""
        return result


class ProjectLive(_LiveProtocol):
    """
    操作层：告诉项目哪些地方可以定制。

    必须实现：
    - deliver_real 或 deliver_provided（二选一，通过继承中间基类指定）

    可选覆盖：
    - build_request: 构建请求参数（默认透传 case.input）
    - deliver_stub
    - extract_output / application_boundary / project_fields / build_execution_trace
    - normalize_result
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
    def deliver_real(self, request: LiveRequest) -> Any:
        """扩展点：真实投递。项目必须实现。

        定位/目标：
            调用业务系统（真实 API / 服务），返回 raw_response。
            返回值可以是 raw_response（dict/对象）或完整 LiveExecutionResult。

        参数：
            request: LiveRequest，含 project_id/case_id/raw_input/normalized_request/turns/session_id 等。
                     normalized_request 形状符合 live_schema.REQUEST_SCHEMA。
        """
        pass


class ProvidedOutputLive(ProjectLive):
    """provided-output 项目继承这个类。

    deliver_provided 是 @abstractmethod（必须实现）。
    deliver_real 有默认实现（raise NotImplementedError）。

    继承此类后，项目只需实现 deliver_provided，不需要实现 deliver_real。
    """

    @abstractmethod
    def deliver_provided(self, case: SingleTurnCase | MultiTurnCase, request: LiveRequest) -> Any:
        """扩展点：provided 投递。项目必须实现。

        定位/目标：
            从 case.output 取 raw_response（provided-output 模式）。

        参数：
            case: 单轮或多轮用例，含 output（provided 数据）。
            request: LiveRequest，含 normalized_request 等。
        """
        pass
