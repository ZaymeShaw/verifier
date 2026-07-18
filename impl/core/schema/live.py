from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import now_iso


@dataclass(frozen=True)
class LiveExchange:
    """RealLive 一次物理传输的公共事实原件。仅由 LiveTransport 生成。"""

    exchange_id: str
    sequence: int
    transport: str
    method: str
    url: str
    carries_live_request: bool = False
    contributes_raw_response: bool = False
    request_headers: Dict[str, Any] = field(default_factory=dict)
    request: Any = None
    status_code: Optional[int] = None
    response_headers: Dict[str, Any] = field(default_factory=dict)
    response: Any = None
    error: Optional[str] = None
    started_at: str = ""
    finished_at: str = ""


@dataclass
class LiveRequest:
    # Live 层：mock 产出的 REQUEST_SCHEMA 在 provided-output 路径中的请求边界对象。
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
    # 兼容的多轮运行中状态；完整轮次事实最终写入 RunTrace.turn_records，
    # 每轮 extracted_output 分别保持项目 EXTRACT_OUTPUT_SCHEMA 形状。
    turn_traces: List[Dict[str, Any]] = field(default_factory=list)
    conversation_summary: Dict[str, Any] = field(default_factory=dict)
    final_stage: str = ""
