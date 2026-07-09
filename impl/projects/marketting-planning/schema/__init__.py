# marketting-planning 项目 dataclass schema（显式结构唯一来源）
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MPCaseInput:
    """mock_agent 产出的 case.input 形状（项目语义层输入）。"""
    query: str
    user_intent: str = ""
    turns: List[Dict[str, Any]] = field(default_factory=list)
    scenario: str = ""
    expected_stage: str = ""
    expected_path_types: List[str] = field(default_factory=list)
    expected_cards: List[str] = field(default_factory=list)
    shared_session: bool = False
    session_id: str = ""
    boundary: Dict[str, Any] = field(default_factory=dict)
    reference: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPNormalizedRequest:
    """verifier live 协议 normalized_request 形状。"""
    case_id: str
    session_id: str
    shared_session: bool
    user_intent: str
    query: str
    turns: List[Dict[str, Any]]
    current_turn: Dict[str, Any]
    scenario: str
    expected_path_types: List[str]
    expected_cards: List[str]
    metadata: Dict[str, Any]
    boundary: Dict[str, Any]
    reference: Dict[str, Any]
    expected_stage: Optional[str] = None


@dataclass
class MPApiRequest:
    """真实业务 API 请求 body。"""
    session_id: str
    trace_id: str
    org_id: str = "eval-org"
    user_text: str = ""
    extra_input_params: Dict[str, Any] = field(default_factory=dict)


# 兼容旧名称：真实 API body，不作为 live normalized_request schema 使用。
MPRequest = MPApiRequest


@dataclass
class MPCardResult:
    event: str = ""
    sse_id: str = ""
    think: Optional[str] = None
    answer: Optional[str] = None
    card_list: List[Dict[str, Any]] = field(default_factory=list)
    extensions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPExtraOutputParams:
    intent: str = ""
    intent_name: str = ""
    card_result: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPRawData:
    robot_text: str = ""
    end_flag: int = 0
    extra_output_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPRawResponse:
    """真实业务 API 原始 SSE JSON 帧形状。"""
    code: int
    msg: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPEventSummary:
    """SSE 事件的紧凑摘要，不携带原始帧。"""
    names: List[str] = field(default_factory=list)
    raw_names: List[str] = field(default_factory=list)
    canonical_names: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    raw_counts: Dict[str, int] = field(default_factory=dict)
    final_event: str = ""
    raw_final_event: str = ""
    protocol_completed: bool = False
    business_completed: bool = False
    completed: bool = False


@dataclass
class MPCardSummary:
    """规划卡片紧凑摘要，不携带完整 card_data。"""
    path_type: str = ""
    card_code: str = ""
    card_name: str = ""
    fallback: bool = False
    forecast_value: Optional[Any] = None
    achievement_rate: Optional[Any] = None
    business_evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPSessionSummary:
    """多轮会话状态摘要。"""
    session_id: str = ""
    required_fields: List[str] = field(default_factory=list)
    accumulated_fields: Dict[str, Any] = field(default_factory=dict)
    missing_fields: List[str] = field(default_factory=list)
    evidence_declared: bool = False
    evidence_status: str = "missing"


@dataclass
class MPFallbackSummary:
    """fallback 边界摘要。"""
    used: bool = False
    allowed: bool = False
    reason: str = ""


@dataclass
class MPTurnOutput:
    """单轮 live 输出 item：只保留评测所需的紧凑语义字段。"""
    code: int
    msg: str
    robot_text: str = ""
    end_flag: int = 0
    intent: str = ""
    intent_name: str = ""
    stage: str = "unknown"
    event_summary: MPEventSummary = field(default_factory=MPEventSummary)
    card_summary: List[MPCardSummary] = field(default_factory=list)
    session_summary: MPSessionSummary = field(default_factory=MPSessionSummary)
    fallback: MPFallbackSummary = field(default_factory=MPFallbackSummary)
    errors: List[str] = field(default_factory=list)
    turn_index: Optional[int] = None
    input_turn: Optional[Dict[str, Any]] = None


@dataclass
class MPExtractOutput:
    """trace.extracted_output 顶层形状。"""
    turns: List[MPTurnOutput]


@dataclass
class MPTurnExpectation:
    """多轮 turn_expectations 逐轮结构。"""
    turn: int
    stage: str = ""
    missing_fields: List[str] = field(default_factory=list)
    required_path_types: List[str] = field(default_factory=list)
