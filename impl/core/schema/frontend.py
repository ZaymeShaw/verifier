from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .table import TraceTableRow


@dataclass
class FrontendViewModel:
    # View 层：后端交给前端渲染的一致 ViewModel，不承载项目私有分支逻辑。
    project_info: Dict[str, Any]
    # *_panel fields are frontend-boundary projections; core logic should consume the typed schema fields above instead.
    run_trace_summary: Dict[str, Any] = field(default_factory=dict)
    raw_sections: Dict[str, Any] = field(default_factory=dict)
    reference_panel: Dict[str, Any] = field(default_factory=dict)
    judge_panel: Dict[str, Any] = field(default_factory=dict)
    attribute_panel: Dict[str, Any] = field(default_factory=dict)
    fulfillment_panel: Dict[str, Any] = field(default_factory=dict)
    expectation_attribution_panel: Dict[str, Any] = field(default_factory=dict)
    cluster_panel: Dict[str, Any] = field(default_factory=dict)
    check_panel: Dict[str, Any] = field(default_factory=dict)
    table_row: Optional[TraceTableRow] = None
    # project_extensions 仅用于前端展示扩展，不作为 core/judge/attribute 的事实来源。
    project_extensions: Dict[str, Any] = field(default_factory=dict)
    # spec/tool2.md: 可执行验证 tool 的调用记录（供前端展示 tool 调用链和对照）
    tool_call_log: list[Dict[str, Any]] = field(default_factory=list)
