"""可执行可验证 Tool 的统一注册表（spec/tool2.md 最终方案）。

通用层只做"协议 + 编排"，不碰项目结构、不预设 tool 分类、不做拆解器/重放器/执行内核。
执行能力（本地跑 / mock 跑 / 远程调）由各项目 adapter 的 execute_fn 自己提供。

核心理念：归因不是"全知判断对错"，而是"信息不全时拿能拿到的信息做最可能正确的判断，
并用执行验证来证明这个判断"。证据是 actual，不是 expected。

- VerifiableTool：tool_id + description + applicable_scenario + parameters + execute_fn
- ToolResult：tool_id + actual + evidence(执行日志) + status(passed|diverged|inconclusive)
- ToolRegistry：全局注册表，LLM 拿到 tool 目录按需调用，不绑定特定阶段
- ToolOrchestrator：接收 LLM 的 (tool_id + params) 调用请求，执行 execute_fn，返回 ToolResult
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Iterable, List, Optional

from impl.tools import ToolResult, VerifiableTool

__all__ = ["ToolRegistry", "ToolOrchestrator", "VerifiableTool", "ToolResult"]


class ToolRegistry:
    """VerifiableTool 的全局注册表。

    不绑定阶段（judge/attr/check 都能用）。LLM 拿到的 tool 目录是
    `[{tool_id, description, applicable_scenario, parameters}]`。
    """

    def __init__(self) -> None:
        self._tools: Dict[str, VerifiableTool] = {}
        self._lock = threading.RLock()

    def register(self, tool: VerifiableTool) -> None:
        if not tool.tool_id:
            raise ValueError("VerifiableTool.tool_id is required")
        with self._lock:
            self._tools[tool.tool_id] = tool

    def register_many(self, tools: Iterable[VerifiableTool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, tool_id: str) -> Optional[VerifiableTool]:
        with self._lock:
            return self._tools.get(tool_id)

    def tools(self) -> List[VerifiableTool]:
        with self._lock:
            return list(self._tools.values())

    def has(self, tool_id: str) -> bool:
        with self._lock:
            return tool_id in self._tools

    def catalog(self) -> List[Dict[str, Any]]:
        """返回 tool 目录给 LLM：tool_id + description + applicable_scenario + parameters。

        parameters 直接对齐 agno/OpenAI function calling 格式，不做格式转换。
        """
        with self._lock:
            return [
                {
                    "tool_id": tool.tool_id,
                    "description": tool.description,
                    "applicable_scenario": tool.applicable_scenario,
                    "parameters": tool.parameters or {},
                }
                for tool in self._tools.values()
            ]


class ToolOrchestrator:
    """接收 LLM 的 tool 调用请求，执行 execute_fn，返回 ToolResult。

    编排层只管调度，不管执行细节。本地/mock/远程的执行方式由项目 execute_fn 决定。
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def call(self, tool_id: str, params: Optional[Dict[str, Any]] = None) -> ToolResult:
        tool = self._registry.get(tool_id)
        if tool is None:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"tool not registered: {tool_id}",
            )
        if tool.execute_fn is None:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"tool has no execute_fn: {tool_id}",
            )
        try:
            result = tool.execute_fn(**(params or {}))
            if isinstance(result, ToolResult):
                if not result.tool_id:
                    result.tool_id = tool_id
                return result
            # execute_fn 返回裸 dict / None → 包装成 ToolResult
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                actual=result if isinstance(result, dict) else {},
                evidence=f"execute_fn returned non-ToolResult value of type {type(result).__name__}",
            )
        except Exception as exc:  # noqa: BLE001 - orchestrator 必须把执行异常转成 ToolResult
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"execute_fn raised: {exc}",
                evidence=f"exception type={type(exc).__name__}",
            )

    def call_many(self, calls: List[Dict[str, Any]]) -> List[ToolResult]:
        """批量调用：calls = [{tool_id, params}, ...]。"""
        return [self.call(item.get("tool_id", ""), item.get("params") or {}) for item in calls]
