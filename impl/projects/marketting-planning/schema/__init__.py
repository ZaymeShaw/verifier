# marketting-planning 项目 live schema — dataclass 形状定义（spec/struct_output.md）
#
# 来源：impl/projects/marketting-planning/live_schema.py
# 真实 API: POST http://127.0.0.1:9006/api/v1/marketing-planning/stream (SSE)
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MPCaseInput:
    """mock_agent 产出的 case.input 形状（项目语义层输入，adapter 再翻译成真实 API 请求）。"""
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
class MPRequest:
    """真实 API 请求形状（adapter._live_request_body 产出，发给真实 API 的 body）。

    来自原项目 app/schemas/request.py MarketingPlanningRequest。
    """
    session_id: str
    trace_id: str
    org_id: str = "eval-org"
    user_text: str = ""
    extra_input_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPExtractOutput:
    """adapter 提取后的输出形状（SSE 单帧扁平化）。

    真实 API 返回 MarketingPlanningStreamResponse，每帧 JSON:
    {code, msg, data: {robot_text, end_flag, extra_output_params}}
    """
    code: int
    msg: str
    robot_text: str = ""
    end_flag: int = 0
    extra_output_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPTurnExpectation:
    """多轮 turn_expectations 逐轮结构。"""
    turn: int
    stage: str = ""
    missing_fields: List[str] = field(default_factory=list)
    required_path_types: List[str] = field(default_factory=list)