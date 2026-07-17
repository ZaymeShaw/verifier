"""Trace 层：组装 RunTrace

职责（spec/adapter/trace.md 第 9 节）：
- 构造 TraceContext，传给 live.execute_live(intent, ctx)
- 从 ctx 收集过程事实（raw_response / call_status / fallbacks / execution_trace / multi_turn_state）
- 从 live 拿 EXTRACT_OUTPUT_SCHEMA
- 组装完整 RunTrace（含 trace 字段 + output）
- 返回 RunTrace（judge/attribute/cluster/check/frontend 由 pipeline 层调用）

入口：
- trace_from_live(live, case, intent=None): 构造 TraceContext，调 live.execute_live(intent, ctx)，收集过程事实，组装 RunTrace
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .schema import (
    ExecutionTraceEvent,
    FallbackDecision,
    RunTrace,
    SingleTurnCase,
    normalize_mock_case,
    normalize_run_trace,
)

if TYPE_CHECKING:
    from .interaction_protocol import NormalizedCaseInteraction
    from .live_protocol import ProjectLive


@dataclass
class TraceContext:
    """trace 层提供的黑盒，execute_live 内部每轮通过 record_turn 上报过程事实。

    trace 层构造此对象并传给 live.execute_live(intent, ctx)。
    execute_live 内部每轮 deliver_turn 后调 ctx.record_turn(...) 上报本轮过程事实。
    trace 层在 execute_live 返回后从 ctx 读取过程事实，组装 RunTrace。

    live 层不持有 ctx 的引用，不背 trace 字段。
    """

    project_id: str = ""
    case_id: str = ""
    scenario: str = ""
    reference_contract: Dict[str, Any] = field(default_factory=dict)
    # 每轮过程事实累积
    turns: List[Dict[str, Any]] = field(default_factory=list)
    # 多轮聚合状态
    multi_turn: bool = False
    turn_count: int = 0
    session_id: str = ""
    stop_reason: str = ""
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    final_output_turn: Optional[int] = None
    completion_status: str = ""

    def record_turn(
        self,
        request: Any = None,
        raw_response: Any = None,
        extracted_output: Optional[Dict[str, Any]] = None,
        call_status: str = "succeeded",
        runtime_ms: Optional[int] = None,
        error: Optional[str] = None,
        fallbacks: Optional[List[FallbackDecision]] = None,
        validation: Optional[List[Optional[ExecutionTraceEvent]]] = None,
        execution_trace: Optional[List[ExecutionTraceEvent]] = None,
        application_boundary: Optional[Dict[str, Any]] = None,
        project_fields: Optional[Dict[str, Any]] = None,
        mock_message: str = "",
    ) -> None:
        """execute_live 内部每轮 deliver_turn 后调用，上报本轮过程事实。"""
        from .schema import ExecutionTraceEvent

        valid_events = [
            e for e in (validation or [])
            if e is not None and isinstance(e, ExecutionTraceEvent)
        ]
        self.turns.append({
            "turn_index": len(self.turns) + 1,
            "mock_message": str(mock_message or ""),
            "request": request if isinstance(request, dict) else {},
            "raw_response": raw_response,
            "extracted_output": extracted_output if isinstance(extracted_output, dict) else {},
            "call_status": call_status,
            "runtime_ms": runtime_ms,
            "error": error,
            "fallbacks": list(fallbacks or []),
            "validation": valid_events,
            "execution_trace": list(execution_trace or []),
            "application_boundary": dict(application_boundary or {}),
            "project_fields": dict(project_fields or {}),
        })
        self.turn_count = len(self.turns)

    def record_execution_error(self, error: str) -> None:
        """记录发生在首轮事实形成前的协议/构建错误。"""
        self.record_turn(call_status="failed", error=error, extracted_output={})
        self.finish_execution(
            stop_reason="execution_error",
            transcript=[],
            final_output_turn=None,
            completion_status="failed",
        )

    def finish_execution(
        self,
        session_id: str = "",
        stop_reason: str = "",
        transcript: Optional[List[Dict[str, Any]]] = None,
        final_output_turn: Optional[int] = None,
        completion_status: str = "",
    ) -> None:
        """记录整个单轮/多轮执行的结束事实。live 只上报，不读取内部状态。"""
        self.session_id = str(session_id or self.session_id or "")
        self.stop_reason = str(stop_reason or self.stop_reason or "")
        self.transcript = list(transcript or [])
        self.final_output_turn = final_output_turn
        self.completion_status = str(completion_status or "")

    def last_raw_response(self) -> Any:
        return self.turns[-1]["raw_response"] if self.turns else None

    def last_extracted_output(self) -> Dict[str, Any]:
        return self.turns[-1]["extracted_output"] if self.turns else {}

    def all_raw_responses(self) -> List[Any]:
        return [t["raw_response"] for t in self.turns]

    def all_fallbacks(self) -> List[FallbackDecision]:
        result: List[FallbackDecision] = []
        for t in self.turns:
            result.extend(t.get("fallbacks") or [])
        return result

    def execution_trace(self) -> List[ExecutionTraceEvent]:
        """从 turns 构建 execution_trace。"""
        trace: List[ExecutionTraceEvent] = []
        for i, t in enumerate(self.turns):
            trace.extend(t.get("validation") or [])
            trace.extend(t.get("execution_trace") or [])
            if t["call_status"] != "succeeded":
                trace.append(ExecutionTraceEvent(
                    stage=f"turn_{i + 1}",
                    status="failed",
                    evidence=t.get("error") or "",
                ))
        return trace

    def turn_request(self, index: int = 0) -> Dict[str, Any]:
        if index < len(self.turns):
            return self.turns[index].get("request") or {}
        return {}

    def last_request(self) -> Dict[str, Any]:
        return self.turn_request(-1) if self.turns else {}


def trace_from_live(
    live: "ProjectLive",
    case: SingleTurnCase | "NormalizedCaseInteraction" | dict,
    intent: Optional[Any] = None,
) -> RunTrace:
    """trace 层主入口：构造 TraceContext，调 live.execute_live(intent, ctx)，收集过程事实，组装 RunTrace。

    流程（spec/adapter/trace.md 第 8-9 节）：
    1. 从 case 提取 intent（调 mock.build_user_intent 或从 case.user_intent 取）
    2. 构造 TraceContext
    3. 调 live.execute_live(intent, ctx) 拿 EXTRACT_OUTPUT_SCHEMA
    4. 从 ctx 收集过程事实，组装 RunTrace
    5. 注入 ready 快照

    参数：
        live: ProjectLive 实例（携带 spec 和 _adapter 引用）
        case: 单轮或多轮用例（dict / SingleTurnCase / NormalizedCaseInteraction）
        intent: 可选的 MockIntentOutput（多轮场景由上游算好传入）

    返回：
        RunTrace（含 trace 字段、ready 快照）
    """
    from .interaction_protocol import NormalizedCaseInteraction, ready_from_spec
    from .live_protocol import MultiTurnInteractiveLive

    # live 实例自带 spec 和 _adapter（由 adapter_v2 注入）
    spec = live.spec
    adapter = live._adapter
    mock = adapter.mock()

    # 归一化 case 形态用于意图计算和提取元信息
    if isinstance(case, NormalizedCaseInteraction):
        normalized_case = case
        case_for_intent = case.source_case
        case_id = str(normalized_case.case_id or "")
        scenario = str(normalized_case.scenario or "")
        reference_contract = dict(normalized_case.reference or {})
        is_multi_turn = True
    elif isinstance(case, SingleTurnCase):
        normalized_case = case
        case_for_intent = case
        case_id = str(case.id or "")
        scenario = str(case.scenario or "")
        reference_contract = dict(case.reference or {}) if isinstance(case.reference, dict) else {}
        is_multi_turn = isinstance(live, MultiTurnInteractiveLive)
    else:
        normalized_case = normalize_mock_case(case) or SingleTurnCase(id="", input=dict(case or {}))
        case_for_intent = normalized_case
        case_id = str(normalized_case.id or "")
        scenario = str(normalized_case.scenario or "")
        reference_contract = {}
        is_multi_turn = isinstance(live, MultiTurnInteractiveLive)
        # 归一化后从 normalized_case 提取 reference_contract（dict 形态不会自动带 reference）
        if isinstance(normalized_case, SingleTurnCase) and isinstance(normalized_case.reference, dict):
            reference_contract = dict(normalized_case.reference)

    # 算意图（intent 未传入时调 live._resolve_intent）
    if intent is None:
        intent = live._resolve_intent(case_for_intent, mock)

    # 用 case 数据预构建请求：仅当 case.input 已符合 REQUEST_SCHEMA 时（固化 fixture 场景），
    # 才注入 intent.live_request 避免 mock.build_live_request 走 LLM 编造请求。
    # 不匹配 REQUEST_SCHEMA 的 case 仍走正常 build_live_request LLM 路径（不掩盖 mock LLM 失败）。
    if not isinstance(case, NormalizedCaseInteraction):
        if isinstance(normalized_case, SingleTurnCase) and isinstance(normalized_case.input, dict) and normalized_case.input:
            request_candidate = dict(normalized_case.input)
            live_schema_check = getattr(live, "live_schema", None)
            checker = getattr(live_schema_check, "check", None) if live_schema_check is not None else None
            if checker is not None and hasattr(checker, "request") and checker.request(request_candidate):
                delivery_request = dict(request_candidate)
                ready = set(ready_from_spec(spec))
                if "output" in ready and isinstance(normalized_case.output, dict):
                    delivery_request["output"] = dict(normalized_case.output)
                if "reference" in ready and isinstance(normalized_case.reference, dict) and "reference" not in delivery_request:
                    delivery_request["reference"] = dict(normalized_case.reference)
                intent.live_request = delivery_request if checker.request(delivery_request) else request_candidate

    # 构造 TraceContext
    ctx = TraceContext(
        project_id=spec.project_id,
        case_id=case_id,
        scenario=scenario,
        reference_contract=reference_contract,
        multi_turn=is_multi_turn,
    )

    # 调 execute_live 拿最后一轮有效的 EXTRACT_OUTPUT_SCHEMA。
    # 每轮 output 和完整交互事实由 ctx 持有，不把 {"turns": [...]} 混入项目 output schema。
    execution_error = ""
    try:
        output = live.execute_live(intent, ctx)
    except Exception as exc:
        # execute_live 负责先把失败事实写入 ctx；trace 层只组装 error trace。
        execution_error = str(exc)
        output = {}

    # 从 ctx 收集过程事实，组装 RunTrace
    # 计算 execution_mode / output_source
    if is_multi_turn:
        execution_mode = "interactive_intent"
        output_source = "interactive_adapter"
    else:
        # 单轮执行模式由协议能力和 ready 声明决定，不能因 provided 校验失败而伪装成 live_service。
        from .live_protocol import ProvidedOutputLive
        if isinstance(live, ProvidedOutputLive) and "output" in ready_from_spec(spec):
            execution_mode = "provided"
            output_source = "provided_output"
        else:
            execution_mode = "live"
            output_source = "live_service"

    # 提取 normalized_request（从 ctx 首轮 request）
    normalized_request = ctx.last_request() if ctx.turns else {}

    # 提取 raw_response（单轮取首轮，多轮取所有）
    raw_response = ctx.last_raw_response() if not is_multi_turn else ctx.all_raw_responses()

    # 提取 fallbacks
    fallbacks = ctx.all_fallbacks()

    # 提取 execution_trace
    execution_trace = ctx.execution_trace()

    # 判断 call_status
    call_status = "ok"
    call_error = execution_error
    if execution_error:
        call_status = "error"
    if ctx.turns:
        last_turn = ctx.turns[-1]
        if last_turn["call_status"] != "succeeded":
            call_status = "error"
            call_error = last_turn.get("error") or ""

    # 多轮状态
    stop_reason = ctx.stop_reason
    turn_index = ctx.turn_count
    conversation_transcript: List[Dict[str, Any]] = list(ctx.transcript or [])
    conversation_summary: Dict[str, Any] = {
        "turn_count": ctx.turn_count,
        "final_output_turn": ctx.final_output_turn,
        "completion_status": ctx.completion_status,
        "stop_reason": ctx.stop_reason,
    }
    application_boundary = {}
    project_fields = {}
    for turn in ctx.turns:
        if turn.get("application_boundary"):
            application_boundary = dict(turn.get("application_boundary") or {})
        if turn.get("project_fields"):
            project_fields.update(dict(turn.get("project_fields") or {}))

    source_input = {}
    if hasattr(case_for_intent, "input") and isinstance(case_for_intent.input, dict):
        source_input = dict(case_for_intent.input)
    elif isinstance(case_for_intent, dict):
        source_input = dict(case_for_intent.get("input") or {}) if isinstance(case_for_intent.get("input"), dict) else dict(case_for_intent)

    trace_id = f"{spec.project_id}:{case_id}:{int(time.time() * 1000)}"
    trace = RunTrace(
        trace_id=trace_id,
        project_id=spec.project_id,
        case_id=case_id,
        mock_intent=intent,
        input=source_input,
        normalized_request=normalized_request,
        raw_response=raw_response,
        extracted_output=output if isinstance(output, dict) else {},
        execution_mode=execution_mode,
        output_source=output_source,
        scenario=scenario,
        reference_contract=reference_contract,
        application_boundary=application_boundary,
        project_fields=project_fields,
        runtime_logs=[],
        evidence_refs=[],
        execution_trace=execution_trace,
        status=call_status,
        error=call_error,
        interaction_mode="interactive_intent" if is_multi_turn else "single_turn",
        session_id=ctx.session_id,
        stop_reason=stop_reason,
        turn_index=turn_index,
        multi_turn_input=None,
        fallbacks=fallbacks,
        ready=ready_from_spec(spec),
        conversation_transcript=conversation_transcript,
        conversation_summary=conversation_summary,
        turn_records=list(ctx.turns),
        final_output_turn=ctx.final_output_turn,
        completion_status=ctx.completion_status,
    )
    return normalize_run_trace(trace)
