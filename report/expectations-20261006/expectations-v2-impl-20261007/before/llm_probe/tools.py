"""llm_probe Tools：无项目特化工具。"""
from __future__ import annotations

from typing import Any, Dict, List

from impl.core.tools_protocol import ProjectTools
from impl.tools import ToolRegistry


class LlmProbeTools(ProjectTools):
    def verifiable_tools(self) -> List[Any]:
        return []

    def protocol_tools(self) -> Any:
        return ToolRegistry()

    def runtime_checks(
        self,
        runtime_values: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return {}
