from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional

from .base import GateDecision, SubagentResult, TransitionDecision, now_iso
from .evidence import EvidenceRef, ExecutionTraceEvent
from .fallback import FallbackDecision
from .live import LiveExecutionResult

if TYPE_CHECKING:
    from .attribute import AttributeResult
    from .check import CheckReport
    from .cluster import ClusterSummary
    from .judge import JudgeResult


@dataclass
class TraceStateRecord:
    # Trace 层：状态机单个状态的输入、输出、证据、质量门和错误记录。
    state_id: str
    role: str
    status: str = "succeeded"
    attempt: int = 1
    started_at: str = field(default_factory=now_iso)
    finished_at: str = field(default_factory=now_iso)
    input_summary: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    subagent_results: List[SubagentResult] = field(default_factory=list)
    evidence_refs: List[EvidenceRef] = field(default_factory=list)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    transition_decision: Optional[TransitionDecision] = None
    errors: List[str] = field(default_factory=list)


@dataclass
class RunTrace:
    # Trace 层：一次被测业务执行链路的主记录，是 judge/attribute 的核心输入；顶层字段是由 live_result 派生的稳定消费索引。
    trace_id: str
    project_id: str
    case_id: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    normalized_request: Dict[str, Any] = field(default_factory=dict)
    raw_response: Any = None
    extracted_output: Dict[str, Any] = field(default_factory=dict)
    live_result: Optional[LiveExecutionResult] = None
    execution_mode: str = ""
    output_source: str = ""
    scenario: str = ""
    reference_contract: Dict[str, Any] = field(default_factory=dict)
    application_boundary: Dict[str, Any] = field(default_factory=dict)
    # project_fields 仅承载 adapter 私有补充；live 调用事实以 live_result 为准。
    project_fields: Dict[str, Any] = field(default_factory=dict)
    runtime_logs: List[str] = field(default_factory=list)
    evidence_refs: List[EvidenceRef] = field(default_factory=list)
    execution_trace: List[ExecutionTraceEvent] = field(default_factory=list)
    status: str = "ok"
    error: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    state_history: List[TraceStateRecord] = field(default_factory=list)
    gate_decisions: List[GateDecision] = field(default_factory=list)
    transition_decisions: List[TransitionDecision] = field(default_factory=list)
    stop_reason: str = ""
    interaction_mode: str = "single_turn"
    session_id: str = ""
    turn_index: int = 0
    # 协议层 ready 声明快照：由 pipeline 在构造 trace 时从 spec.common.ready 注入一次，
    # judge/attribute 等下游直接读 trace.ready，单一数据源，禁止再 load_project 反查。
    ready: List[str] = field(default_factory=list)
    conversation_transcript: List[Dict[str, Any]] = field(default_factory=list)
    conversation_summary: Dict[str, Any] = field(default_factory=dict)
    multi_turn_input: Optional[Dict[str, Any]] = None
    fallbacks: List[FallbackDecision] = field(default_factory=list)


@dataclass
class TraceExecutionContext:
    project_id: str
    input_data: Dict[str, Any]
    expected_intent: Optional[str] = None
    trace: Optional[RunTrace] = None
    judge_result: Optional["JudgeResult"] = None
    attribute_result: Optional["AttributeResult"] = None
    cluster_summary: Optional["ClusterSummary"] = None
    check_report: Optional["CheckReport"] = None
    state_history: List[TraceStateRecord] = field(default_factory=list)
    executor_outputs: Dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def setdefault(self, key: str, default: Any) -> Any:
        value = getattr(self, key, None)
        if value is None:
            setattr(self, key, default)
            return default
        return value

    def keys(self) -> Iterator[str]:
        return iter(self.__dataclass_fields__.keys())

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)


@dataclass
class MultiTurnTraceSummary:
    # Trace 层：兼容旧聚合输出；新消费方优先读取 RunTrace 的 conversation_* 字段。
    trace_id: str
    project_id: str
    session_id: str
    input: Dict[str, Any]
    turn_traces: List[RunTrace]
    conversation_transcript: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    final_output: Dict[str, Any] = field(default_factory=dict)
