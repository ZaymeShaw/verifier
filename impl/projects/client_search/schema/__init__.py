# client_search 项目 dataclass schema（显式结构唯一来源）
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ClientSearchCaseInput:
    """mock_agent 产出的 case.input 形状。"""
    query: str
    scenario: str = ""
    reference: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClientSearchRequest:
    """adapter.build_request 产出的 normalized_request / 真实 API 请求体。"""
    user_text: str
    user_id: str = "eval-user"
    trace_id: str = ""
    session_id: str = "general-eval-session"
    source: str = "askbob"
    extra_input_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClientSearchRawData:
    robot_text: Optional[str] = None
    end_flag: Optional[int] = None
    trace_id: Optional[str] = None
    extra_output_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClientSearchRawResponse:
    code: int
    msg: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClientSearchExtractOutput:
    """adapter.extract_output 产出的扁平化输出形状。"""
    code: int
    msg: str
    query: str
    conditions: List[Any]
    robot_text: Optional[str]
    query_logic: Optional[str]
    rewritten_query: Optional[str]
    end_flag: Optional[int] = None
    trace_id: Optional[str] = None
    matched_level: Optional[int] = None
    matched_patterns: Optional[str] = None
    intent_summary: Optional[str] = None
    confidence: Optional[float] = None
    cost_times: Optional[float] = None
