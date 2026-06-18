from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Protocol

from agno.tools import Function, Toolkit

from impl.core.schema import ProjectSpec, RunTrace


@dataclass
class ToolContext:
    project_id: str
    purpose: str
    spec: ProjectSpec | None = None
    trace: RunTrace | None = None
    inputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool_id: str
    tool_type: str
    status: str = "succeeded"
    outputs: Dict[str, Any] = field(default_factory=dict)
    evidence: list[Any] = field(default_factory=list)
    missing_evidence: list[Any] = field(default_factory=list)
    boundary_limits: list[Any] = field(default_factory=list)
    error: str = ""




@dataclass
class ToolSelectionPolicy:
    tool_type: str | None = None
    tool_ids: list[str] = field(default_factory=list)
    allow_planner_variability: bool = False


@dataclass
class ToolSelection:
    tool_id: str
    tool_type: str
    reason: str = ""


class ProtocolToolPlanner:
    def select(self, registry: "ToolRegistry", context: ToolContext, policy: ToolSelectionPolicy | None = None) -> list[ToolSelection]:
        policy = policy or ToolSelectionPolicy()
        if policy.tool_ids:
            selected = [registry.get(tool_id) for tool_id in policy.tool_ids]
            reason = "explicit tool_ids policy"
        else:
            selected = registry.by_type(policy.tool_type) if policy.tool_type else list(registry.tools())
            reason = "deterministic tool_type policy" if policy.tool_type else "deterministic all-tools policy"
        return [ToolSelection(tool_id=tool.tool_id, tool_type=tool.tool_type, reason=reason) for tool in selected]


class ProtocolTool(Protocol):
    tool_id: str
    tool_type: str

    def run(self, context: ToolContext) -> ToolResult:
        ...


@dataclass
class AgnoToolCall:
    function: Function
    context: ToolContext

    def run(self) -> ToolResult:
        result = self.function.entrypoint() if self.function.entrypoint else None
        if isinstance(result, ToolResult):
            return result
        return ToolResult(
            tool_id=self.function.name,
            tool_type="unknown",
            outputs={"result": result} if result is not None else {},
        )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ProtocolTool] = {}
        self._agno_functions: Dict[str, Function] = {}

    def register(self, tool: ProtocolTool) -> None:
        self._tools[tool.tool_id] = tool
        self._agno_functions[tool.tool_id] = self._to_agno_function(tool)

    def register_many(self, tools: Iterable[ProtocolTool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, tool_id: str) -> ProtocolTool:
        return self._tools[tool_id]

    def tools(self) -> list[ProtocolTool]:
        return list(self._tools.values())

    def by_type(self, tool_type: str) -> list[ProtocolTool]:
        return [tool for tool in self._tools.values() if tool.tool_type == tool_type]

    def _to_agno_function(self, tool: ProtocolTool) -> Function:
        def entrypoint() -> ToolResult:
            raise RuntimeError("protocol tools require ToolContext; use select() or run() with context")

        entrypoint.__name__ = tool.tool_id.replace(".", "_")
        return Function(
            name=tool.tool_id,
            description=f"{tool.tool_type} protocol tool",
            entrypoint=entrypoint,
            skip_entrypoint_processing=True,
        )

    def _to_agno_callable(self, tool: ProtocolTool):
        def entrypoint() -> dict:
            raise RuntimeError("protocol tools require ToolContext; use run_protocol_tools() with context")

        entrypoint.__name__ = tool.tool_id.replace(".", "_")
        entrypoint.__doc__ = f"{tool.tool_type} protocol tool; deterministic context-bound execution only."
        return entrypoint

    def agno_functions(self, tool_type: str | None = None) -> list[Function]:
        tools = self.by_type(tool_type) if tool_type else list(self._tools.values())
        return [self._agno_functions[tool.tool_id] for tool in tools]

    def agno_toolkit(self, name: str = "protocol_tools", tool_type: str | None = None) -> Toolkit:
        tools = self.by_type(tool_type) if tool_type else list(self._tools.values())
        return Toolkit(name=name, tools=[self._to_agno_callable(tool) for tool in tools], auto_register=True)

    def select(self, context: ToolContext, tool_type: str | None = None, policy: ToolSelectionPolicy | None = None) -> list[AgnoToolCall]:
        selection_policy = policy or ToolSelectionPolicy(tool_type=tool_type)
        selections = ProtocolToolPlanner().select(self, context, selection_policy)
        return [AgnoToolCall(function=self._agno_functions[item.tool_id], context=context) for item in selections]

    def run_selected(self, context: ToolContext, tool_type: str | None = None, policy: ToolSelectionPolicy | None = None) -> list[ToolResult]:
        results = []
        for call in self.select(context, tool_type, policy):
            tool = self.get(call.function.name)
            results.append(tool.run(context))
        return results

    def run(self, tool_id: str, context: ToolContext) -> ToolResult:
        try:
            return self.get(tool_id).run(context)
        except KeyError:
            return ToolResult(tool_id=tool_id, tool_type="unknown", status="failed", error=f"tool not registered: {tool_id}")

    def run_type(self, tool_type: str, context: ToolContext) -> list[ToolResult]:
        return self.run_selected(context, tool_type)


def function_tool(tool_id: str, tool_type: str, func: Callable[[ToolContext], ToolResult]) -> ProtocolTool:
    class _FunctionTool:
        def __init__(self) -> None:
            self.tool_id = tool_id
            self.tool_type = tool_type

        def run(self, context: ToolContext) -> ToolResult:
            return func(context)

    return _FunctionTool()
