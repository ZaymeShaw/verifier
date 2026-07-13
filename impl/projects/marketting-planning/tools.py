"""Marketing Planning 项目的 Tools 实现

实现 ProjectTools 协议。
"""
from __future__ import annotations

from typing import Any, Dict, List

from impl.core.schema import ProjectSpec, RunTrace
from impl.core.tools_protocol import ProjectTools


class MarketingPlanningTools(ProjectTools):
    """Marketing Planning 项目 Tools 实现"""

    def verifiable_tools(self) -> List[Any]:
        """返回可验证工具列表"""
        # marketting-planning 项目没有特殊工具
        return []

    def protocol_tools(self) -> Any:
        """返回协议工具注册表"""
        from impl.tools import ToolRegistry
        return ToolRegistry()

    def runtime_checks(
        self,
        runtime_values: Dict[str, Any],
        context: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """运行时检查"""
        context = context or {}
        expected = context.get("expected") if isinstance(context.get("expected"), dict) else {}
        actual = context.get("actual") if isinstance(context.get("actual"), dict) else {}
        checks: Dict[str, Any] = {}
        expected_stage = expected.get("expected_stage") or expected.get("stage")
        actual_stage = actual.get("stage") or actual.get("current_stage")
        if expected_stage or actual_stage:
            checks["stage_match"] = {
                "expected": expected_stage,
                "actual": actual_stage,
                "match": bool(expected_stage) and expected_stage == actual_stage,
            }
        if runtime_values:
            checks["runtime_values"] = runtime_values
        reference = context.get("reference") if isinstance(context.get("reference"), dict) else {}
        if reference:
            checks["reference_contract"] = reference
        return checks

    def frontend_extensions(self, trace: RunTrace) -> Dict[str, Any]:
        return {
            "schema_protocol_extensions": trace.project_fields,
            "scenarios": self.spec.frontend_extensions.get("scenarios") or [],
            "stages": self.spec.frontend_extensions.get("stages") or [],
            "path_types": self.spec.frontend_extensions.get("path_types") or [],
            "output_summary_shape": ["stage", "event_summary", "card_summary", "session_summary", "fallback", "errors"],
        }
