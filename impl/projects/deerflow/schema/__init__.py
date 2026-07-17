"""deerflow 项目 dataclass schema（显式结构唯一来源）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DeerflowMessage:
    """业务 API messages 数组单项。"""
    role: str = "user"
    content: str = ""


@dataclass
class DeerflowApiInput:
    """业务 API input 字段。"""
    messages: List[DeerflowMessage] = field(default_factory=list)


@dataclass
class DeerflowApiConfig:
    """业务 API config 字段。"""
    configurable: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeerflowApiRequest:
    """真实业务 API 请求 body（对齐 /api/threads/{tid}/runs/wait）。

    真实业务系统两步：
    1. POST /api/threads 创建 thread（body {}）
    2. POST /api/threads/{tid}/runs/wait 发消息（本 dataclass 对齐此 body）
    """
    input: DeerflowApiInput = field(default_factory=DeerflowApiInput)
    config: DeerflowApiConfig = field(default_factory=DeerflowApiConfig)


@dataclass
class DeerflowRequest:
    """mock_agent 产出的 case.input 形状（项目语义层输入，不是 REQUEST_SCHEMA）。

    adapter.build_request 负责把它翻译成 DeerflowApiRequest（业务 API 形状）。
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
    reply_text: str = ""
    tool_calls: List[DeerflowToolCall] = field(default_factory=list)
    stage: str = "unknown"
    nbev_tool_count: int = 0
    scripts_called: List[str] = field(default_factory=list)
    session_summary: Dict[str, Any] = field(default_factory=dict)
    fallback: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
