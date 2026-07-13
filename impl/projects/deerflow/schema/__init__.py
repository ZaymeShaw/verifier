"""deerflow 项目 dataclass schema（显式结构唯一来源）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DeerflowRequest:
    """mock_agent 产出的 case.input 形状（= REQUEST_SCHEMA）。

    形状对齐 Gateway 多轮 API：query + turns + scenario + expected_stage +
    expected_dimensions + reference + metadata。adapter.build_request 负责把它
    翻译成 Gateway 实际请求体（thread_id 续上下文）。
    """
    query: str = ""
    user_intent: str = ""
    turns: List[Dict[str, Any]] = field(default_factory=list)
    scenario: str = ""
    expected_stage: str = ""
    expected_dimensions: List[str] = field(default_factory=list)
    boundary: Dict[str, Any] = field(default_factory=dict)
    reference: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeerflowToolCall:
    """工具调用摘要。"""
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    is_nbev_script: bool = False


@dataclass
class DeerflowTurnOutput:
    """单轮 live 输出：只保留评测所需的紧凑语义字段。"""
    turn_index: int = 0
    reply_text: str = ""
    tool_calls: List[DeerflowToolCall] = field(default_factory=list)
    stage: str = "unknown"
    nbev_tool_count: int = 0
    scripts_called: List[str] = field(default_factory=list)
    session_summary: Dict[str, Any] = field(default_factory=dict)
    fallback: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    input_turn: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeerflowExtractOutput:
    """adapter.extract_output 产出的标准化输出形状。"""
    turns: List[DeerflowTurnOutput] = field(default_factory=list)
