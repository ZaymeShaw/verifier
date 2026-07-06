# marketting-planning-intent 项目 live schema — dataclass 形状定义（spec/struct_output.md）
#
# 来源：impl/projects/marketting-planning-intent/live_schema.py
# 真实 API: POST http://127.0.0.1:9006/api/v1/marketing-planning/intent-recognition (non-SSE)
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MPIIntentCaseInput:
    """mock_agent 产出的 case.input 形状。"""
    query: str
    scenario: str = "intent_recognition"
    expected_intent: str = ""
    reference: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPIIntentRequest:
    """真实 API 请求形状（adapter._live_request_body 产出）。"""
    session_id: str
    trace_id: str
    org_id: str = "eval-org"
    user_text: str = ""
    extra_input_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MPIIntentExtractOutput:
    """adapter 提取后的输出形状（IntentResult 字段）。"""
    intent: str
    confidence: float
    target_value: Optional[str] = None
    path_types: Optional[List[str]] = None
    subIntent: Optional[str] = None