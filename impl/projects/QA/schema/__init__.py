# QA 项目 live schema — dataclass 形状定义（spec/struct_output.md）
#
# 来源：impl/projects/QA/live_schema.py
# IS_PROVIDED_OUTPUT 模式，不调外部 live 服务。call_or_prepare 直接把 normalized_request.output 当 raw_response。
#
# 本文件只定义形状 dataclass。SCENARIO_ENUM / INTENT_LABELS / REQUIRED_INPUT_FIELDS /
# READY / LiveSchemaCheck 仍由 live_schema.py 维护，不受影响。
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
class QARequest:
    """normalized_request 形状（project.yaml IS_PROVIDED_OUTPUT）。"""
    input: Dict[str, Any] = field(default_factory=dict)
    reference: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    scenario: str = ""
    data_quality_flags: Optional[List[str]] = None
    output: Optional[Dict[str, Any]] = None


@dataclass
class QAExtractOutput:
    """extract_output 形状（极简）。"""
    actual_answer: str