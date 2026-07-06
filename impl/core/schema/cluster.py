from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ClusterSummary:
    # 聚类层：多个归因结果的聚合摘要，用于发现共性根因和优先级。
    project_id: str
    clusters: List[Dict[str, Any]] = field(default_factory=list)
    representative_cases: List[Any] = field(default_factory=list)
    common_root_cause: str = ""
    impact: str = ""
    priority: str = ""
    next_actions: List[str] = field(default_factory=list)
