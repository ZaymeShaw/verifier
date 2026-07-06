from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .fallback import FallbackDecision


@dataclass
class CheckReport:
    # Check 层：标准化审查结果，记录协议缺口、一致性缺口、过拟合和只改数据风险。
    passed: bool
    issues: List[str] = field(default_factory=list)
    boundary_violations: List[str] = field(default_factory=list)
    protocol_gaps: List[str] = field(default_factory=list)
    consistency_gaps: List[str] = field(default_factory=list)
    overfit_risks: List[str] = field(default_factory=list)
    data_only_patch_risks: List[str] = field(default_factory=list)
    verification_results: List[str] = field(default_factory=list)
    recommended_fixes: List[str] = field(default_factory=list)
    fallbacks: List[FallbackDecision] = field(default_factory=list)
