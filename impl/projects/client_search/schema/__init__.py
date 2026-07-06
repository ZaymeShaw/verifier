# client_search 项目 live schema — dataclass 形状定义（spec/struct_output.md）
#
# 来源：impl/projects/client_search/live_schema.py
# 真实 API: POST http://localhost:8000/api/v1/client_search_query_parse_no_encipher
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
    """真实 API 请求形状（adapter.build_request 产出的 normalized_request）。"""
    user_text: str
    user_id: str = "eval-user"
    trace_id: str = ""
    session_id: str = "general-eval-session"
    source: str = "askbob"
    extra_input_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClientSearchExtractOutput:
    """adapter.extract_output 产出的扁平化输出形状。

    真实 API 返回 {code, msg, data: {robot_text, end_flag, ...}}，adapter 扁平化后只保留这些字段。
    链路必传字段不给 default；允许 null 的必传字段用 Optional[T] 且不设 default。
    链路非必需字段给 default / default_factory，不阻断 verifier 主链路。
    """
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