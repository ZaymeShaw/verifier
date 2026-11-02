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
    call_status: str = ""
    runtime_ms: int = 0
    error: str = ""


@dataclass
class TraceTableRow:
    # 表格 View 层：summary/case-pool 中的一行 trace 展示数据。
    id: str
    input: str
    scenario: str = ""
    output_summary: str = ""
    reference_summary: str = ""
    status: str = ""
    execution_status: str = ""
    execution_error: str = ""
    interaction_controller_status: str = "not_run"
    interaction_controller_error: str = ""
    execution_mode: str = ""
    output_source: str = ""
    score: Optional[float] = None
    fulfillment_status: str = ""
    carrier_placement: str = ""
    # 扩展评估轴（试验）：每轴一条 {axis_id, title, status, verdict, text, items[]}；预设没启用框时为空。
    eval_axes_summary: List[Dict[str, Any]] = field(default_factory=list)
    # 一个 case 各阶段墙钟毫秒：live_ms / judge_ms / carrier_ms / eval_axes_ms；哪段慢一眼看见，不用翻 context store。
    stage_timings: Dict[str, int] = field(default_factory=dict)
    judge_summary: Dict[str, Any] = field(default_factory=dict)
    attribution_summary: Dict[str, Any] = field(default_factory=dict)
    check_summary: Dict[str, Any] = field(default_factory=dict)
    fallback_summary: Dict[str, Any] = field(default_factory=dict)
    needs_human_review: bool = False
    quality_flags: List[str] = field(default_factory=list)
    check_passed: Optional[bool] = None
    issue_count: int = 0
    fallback_count: int = 0
    divergence_stage: str = ""
    root_cause_summary: str = ""
    created_at: str = ""
    stop_reason: str = ""
    # spec/mock/protocol.md 4.7/4.9：stop_reason 归责组与派生的用户方健康度。
    # 只有 attribution 为 user / live 的行计入 live 质量指标。
    stop_attribution: str = ""
    driver_health: Dict[str, Any] = field(default_factory=dict)
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
