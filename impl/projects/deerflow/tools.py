"""deerflow 项目的 Tools 实现

实现 ProjectTools 协议。
"""
from __future__ import annotations

from typing import Any, Dict, List

from impl.core.tools_protocol import ProjectTools
from impl.core.schema import ProjectSpec


class DeerflowTools(ProjectTools):
    """deerflow 项目 Tools 实现"""

    def verifiable_tools(self) -> List[Any]:
        """返回可验证工具列表"""
        # deerflow 项目没有特殊工具
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
        # deerflow 项目没有特殊运行时检查
        return {}
