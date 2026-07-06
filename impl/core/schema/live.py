from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import now_iso
from .evidence import EvidenceRef, ExecutionTraceEvent
from .fallback import FallbackDecision


@dataclass
class LiveRequest:
    # Live 层：adapter.build_request 后的业务请求边界对象。
    project_id: str
    raw_input: Dict[str, Any]
    case_id: str = ""
    turns: List[Dict[str, Any]] = field(default_factory=list)
    normalized_request: Dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "live_service"
    session_id: str = ""
    timestamp: str = field(default_factory=now_iso)


@dataclass
class LiveMultiTurnState:
    # Live 层：多轮业务请求的运行中状态。
    session_id: str
    turn_index: int = 0
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    accumulated_fields: Dict[str, Any] = field(default_factory=dict)
    missing_fields: List[str] = field(default_factory=list)
    stop_reason: str = ""


@dataclass
class LiveExecutionResult:
    # Live 层：一次业务系统调用的完整输入、响应、提取结果和证据。
    project_id: str
    case_id: str = ""
    session_id: str = ""
    raw_input: Dict[str, Any] = field(default_factory=dict)
    normalized_request: Dict[str, Any] = field(default_factory=dict)
    call_status: str = "succeeded"
    raw_response: Optional[Any] = None
    call_error: Optional[str] = None
    runtime_ms: Optional[int] = None
    extracted_output: Dict[str, Any] = field(default_factory=dict)
    output_source: str = "live_service"
    execution_trace: List[ExecutionTraceEvent] = field(default_factory=list)
    evidence_refs: List[EvidenceRef] = field(default_factory=list)
    # project_fields 仅承载 adapter 私有补充；output_source/application_boundary 等核心事实使用顶层字段。
    project_fields: Dict[str, Any] = field(default_factory=dict)
    application_boundary: Dict[str, Any] = field(default_factory=dict)
    interaction_mode: str = "single_turn"
    multi_turn_state: Optional[LiveMultiTurnState] = None
    fallbacks: List[FallbackDecision] = field(default_factory=list)


@dataclass
class LiveMultiTurnResult:
    # Live 层：多轮执行聚合结果，供 Trace/Judge/Attribute 后续消费。
    project_id: str
    case_id: str
    session_id: str
    turn_results: List[LiveExecutionResult]
    conversation_transcript: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    final_output: Dict[str, Any] = field(default_factory=dict)
