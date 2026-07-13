# QA 项目 dataclass schema（显式结构唯一来源）
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class QAInput:
    """mock_agent 产出的 case.input 形状（adapter.build_request 消费）。"""
    question: str
    contexts: List[str] = field(default_factory=list)
    reference: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    scenario: str = ""
    data_quality_flags: Optional[List[str]] = None
    output: Optional[Dict[str, Any]] = None


@dataclass
class QAExtractOutput:
    """extract_output 形状。"""
    actual_answer: str
