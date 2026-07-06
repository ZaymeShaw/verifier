from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .check import CheckReport
from .cluster import ClusterSummary
from .fallback import FallbackDecision
from .table import CasePoolTable


@dataclass
class BatchRunResult:
    # Batch 层：批量运行输出，聚合每个 case 的 trace/judge/attribute/check 结果。
    project_id: str
    total: int
    runs: List[Dict[str, Any]] = field(default_factory=list)
    cluster: Optional[ClusterSummary] = None
    check: Optional[CheckReport] = None
    table: Optional[CasePoolTable] = None
    fallbacks: List[FallbackDecision] = field(default_factory=list)
