"""Tools 协议层和扩展点基类

三层文件关系：
- tools_protocol.py: 协议层（_ToolsProtocol）+ 扩展点基类（ProjectTools）
- tools.py: 通用函数（build_agno_tools, ToolRegistry 等）
- projects/<project>/tools.py: 项目实现（XxxTools(ProjectTools)）
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from typing import final as typing_final
from impl.core.schema import ProjectSpec
from impl.core.protocol_base import check_forbidden_overrides


class _ToolsProtocol(ABC):
    """
    协议层：定义 Tools 注册流程骨架，项目不能覆盖。

    模板方法：
    - all_tools: 完整的工具注册流程（@final，不可覆盖）

    内部方法：
    - _merge_tools: 合并工具列表（内部方法，不可覆盖）
    - _deduplicate_tools: 去重工具（内部方法，不可覆盖）

    扩展点（通过 ProjectTools 实现）：
    - verifiable_tools: 返回可验证工具列表（可选覆盖）
    - protocol_tools: 返回协议工具注册表（可选覆盖）
    - runtime_checks: 运行时检查（可选覆盖）
    """

    _FORBIDDEN_OVERRIDES = frozenset({
        'all_tools',
        '_merge_tools',
        '_deduplicate_tools'
    })

    def __init_subclass__(cls, **kwargs):
        """检查子类是否覆盖了禁止的方法"""
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    @typing_final
    def all_tools(self) -> Any:
        """
        模板方法：完整的工具注册流程。

        流程：
        1. 调用 verifiable_tools() 获取可验证工具（扩展点）
        2. 调用 protocol_tools() 获取协议工具（扩展点）
        3. 调用 _merge_tools() 合并工具（通用逻辑）
        4. 调用 _deduplicate_tools() 去重（通用逻辑）
        5. 返回合并后的工具注册表
        """
        # 1. 获取可验证工具（项目实现）
        verifiable = self.verifiable_tools()

        # 2. 获取协议工具（项目实现）
        protocol_registry = self.protocol_tools()

        # 3. 合并工具（通用逻辑）
        merged = self._merge_tools(verifiable, protocol_registry)

        # 4. 去重（通用逻辑）
        final_registry = self._deduplicate_tools(merged)

        return final_registry

    def _merge_tools(self, verifiable_tools: List[Any], protocol_registry: Any) -> Any:
        """
        内部方法：合并工具列表。

        将可验证工具注册到协议工具注册表中。
        """
        from impl.tools import ToolRegistry

        # 如果 protocol_registry 不是 ToolRegistry，创建一个新的
        if not isinstance(protocol_registry, ToolRegistry):
            registry = ToolRegistry()
        else:
            registry = protocol_registry

        # 注册可验证工具
        for tool in verifiable_tools or []:
            try:
                registry.register(tool)
            except Exception:
                # 注册失败跳过，不中断流程
                pass

        return registry

    def _deduplicate_tools(self, registry: Any) -> Any:
        """
        内部方法：去重工具。

        移除重复的工具（基于 tool_id）。
        """
        # ToolRegistry 内部已经处理了去重逻辑
        # 这里直接返回
        return registry

    def verifiable_tools(self) -> List[Any]:
        """
        扩展点：返回可验证工具列表。

        项目可选覆盖，返回该项目支持的所有可验证工具列表。
        默认返回空列表。
        """
        return []

    def protocol_tools(self) -> Any:
        """
        扩展点：返回协议工具注册表。

        项目可选覆盖，返回该项目的协议工具注册表。
        默认返回空的 ToolRegistry。
        """
        from impl.tools import ToolRegistry
        return ToolRegistry()

    def runtime_checks(
        self,
        runtime_values: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        扩展点：运行时检查。

        项目可选覆盖，用于：
        - 运行时确定性检查
        - 收集运行时证据
        - 返回检查结果

        默认返回空 dict。
        """
        return {}


class ProjectTools(_ToolsProtocol):
    """
    扩展点基类：项目继承这个类，实现 Tools 扩展点。

    可选覆盖：
    - verifiable_tools: 返回可验证工具列表
    - protocol_tools: 返回协议工具注册表
    - runtime_checks: 运行时检查
    """

    def __init__(self, spec: ProjectSpec):
        """
        初始化 ProjectTools。

        Args:
            spec: 项目规格（ProjectSpec）
        """
        self.spec = spec
        # 集成 live_schema：协议层统一加载和使用
        self.live_schema = None
        if spec is not None:
            from impl.core.mock_agent import load_live_schema
            self.live_schema = load_live_schema(spec.project_id)
