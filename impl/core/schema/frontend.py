from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .table import TraceTableRow


@dataclass
class FrontendViewModel:
    # View 层：后端交给前端渲染的一致 ViewModel，不承载项目私有分支逻辑。
    project_info: Dict[str, Any]
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
    project_extensions: Dict[str, Any] = field(default_factory=dict)
    tool_call_log: list[Dict[str, Any]] = field(default_factory=list)