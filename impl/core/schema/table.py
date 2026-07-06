from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ConversationTurn:
    # 表格 View 层：多轮对话展开时的单轮摘要。
    turn_index: int
    role: str
    content: str
    stage: str = ""
    extracted_summary: str = ""


@dataclass
class TraceTableRow:
    # 表格 View 层：summary/case-pool 中的一行 trace 展示数据。
    id: str
    input: str
    scenario: str = ""
    output_summary: str = ""
    reference_summary: str = ""
    status: str = ""
    execution_mode: str = ""
    output_source: str = ""
    verdict: str = ""
    score: Optional[float] = None
    fulfillment_status: str = ""
    judge_summary: Dict[str, Any] = field(default_factory=dict)
    attribution_summary: Dict[str, Any] = field(default_factory=dict)
    check_summary: Dict[str, Any] = field(default_factory=dict)
    fallback_summary: Dict[str, Any] = field(default_factory=dict)
    needs_human_review: bool = False
    quality_flags: List[str] = field(default_factory=list)
    check_passed: Optional[bool] = None
    issue_count: int = 0
    fallback_count: int = 0
    causal_category: str = ""
    divergence_stage: str = ""
    root_cause_summary: str = ""
    created_at: str = ""
    stop_reason: str = ""
    interaction_mode: str = "single_turn"
    conversation_summary: Dict[str, Any] = field(default_factory=dict)
    conversation_detail: Optional[List[ConversationTurn]] = None
    trace_id: str = ""


@dataclass
class CasePoolTable:
    # 表格 View 层：case-pool 的完整表格结构和统计摘要。
    project_id: str
    rows: List[TraceTableRow] = field(default_factory=list)
    total: int = 0
    summary: Dict[str, Any] = field(default_factory=dict)
