# marketting-planning-intent 项目 dataclass schema（显式结构唯一来源）
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MPIIntentCaseInput:
    """mock_agent 产出的 case.input 形状。"""
    query: str
    scenario: str = "intent_recognition"
    user_intent: str = ""
    reference: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPIIntentNormalizedRequest:
    """verifier live 协议 normalized_request 形状。"""
    case_id: str
    session_id: str
    query: str
    scenario: str
    reference: Dict[str, Any]
    metadata: Dict[str, Any]
    user_intent: Optional[str] = None


@dataclass
class MPIIntentApiRequest:
    """真实 API 请求 body。"""
    session_id: str
    trace_id: str
    org_id: str = "eval-org"
    user_text: str = ""
    extra_input_params: Dict[str, Any] = field(default_factory=dict)


# 兼容旧名称：真实 API body，不作为 live normalized_request schema 使用。
MPIIntentRequest = MPIIntentApiRequest


@dataclass
class MPIIntentRawCardResult:
    event: str = ""
    sse_id: str = ""
    think: Optional[str] = None
    answer: Optional[str] = None
    card_list: List[Any] = field(default_factory=list)
    extensions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPIIntentRawResponse:
    code: int
    msg: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPIIntentExtractOutput:
    """adapter 提取后的输出形状（IntentResult 字段）。"""
    intent: str
    confidence: float
    target_value: Optional[str] = None
    path_types: Optional[List[str]] = None
    subIntent: Optional[str] = None
