"""Adapter 中转站（新协议）+ Legacy 兼容层

按照 spec/adapter.md 设计：
- ProjectAdapter：只做加载和暴露各专项模块，零业务逻辑
- LegacyProjectAdapter：兼容层，继承旧版 ProjectAdapter 的所有方法

迁移策略：
- 新项目使用新的 ProjectAdapter（实现 _load_* 方法）
- 现有 4 个项目暂时使用 LegacyProjectAdapter（继承旧版 ProjectAdapter）
- 逐项目迁移后，LegacyProjectAdapter 可删除
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from impl.core.schema import ProjectSpec
from impl.core.adapter import ProjectAdapter as OldProjectAdapter


class ProjectAdapter(ABC):
    """
    新协议：统一中转站。

    只做加载并暴露各专项模块，不承载任何业务逻辑。

    项目继承这个类，只需实现 5 个 _load_* 方法：
    - _load_live: 返回 ProjectLive 实例
    - _load_mock: 返回 ProjectMock 实例
    - _load_judge: 返回 ProjectJudge 实例
    - _load_attribute: 返回 ProjectAttribute 实例
    - _load_tools: 返回 ProjectTools 实例
    """

    def __init__(self, spec: ProjectSpec):
        self.spec = spec
        self._cache: Dict[str, Any] = {}

    def live(self):
        """访问 ProjectLive 实例"""
        return self._get_or_load("live")

    def mock(self):
        """访问 ProjectMock 实例"""
        return self._get_or_load("mock")

    def judge(self):
        """访问 ProjectJudge 实例"""
        return self._get_or_load("judge")

    def attribute(self):
        """访问 ProjectAttribute 实例（支持 draft 切换）"""
        if self._use_draft("attribute"):
            return self._get_or_load("attribute_draft", "_load_attribute_draft")
        return self._get_or_load("attribute")

    def tools(self):
        """访问 ProjectTools 实例（支持 draft 切换）"""
        if self._use_draft("tools"):
            return self._get_or_load("tools_draft", "_load_tools_draft")
        return self._get_or_load("tools")

    def _get_or_load(self, key: str, loader_name: Optional[str] = None) -> Any:
        """懒加载并缓存专项模块实例"""
        if key not in self._cache:
            loader_method = loader_name or f"_load_{key}"
            loader = getattr(self, loader_method, None)
            if loader is None:
                raise NotImplementedError(
                    f"{self.__class__.__name__} 未实现 {loader_method}() 方法"
                )
            self._cache[key] = loader()
        return self._cache[key]

    def _use_draft(self, role: str) -> bool:
        """判断是否启用 draft 版本"""
        draft_cfg = getattr(self.spec, "attribute_draft", None) or {}
        return draft_cfg.get("enabled") is True

    # === 子类必须实现的加载方法 ===

    @abstractmethod
    def _load_live(self):
        """加载 ProjectLive 实例"""
        pass

    @abstractmethod
    def _load_mock(self):
        """加载 ProjectMock 实例"""
        pass

    @abstractmethod
    def _load_judge(self):
        """加载 ProjectJudge 实例"""
        pass

    @abstractmethod
    def _load_attribute(self):
        """加载 ProjectAttribute 实例"""
        pass

    @abstractmethod
    def _load_tools(self):
        """加载 ProjectTools 实例"""
        pass

    # === draft 版本加载方法（可选） ===

    def _load_attribute_draft(self):
        """加载 draft 版 ProjectAttribute 实例"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 未实现 _load_attribute_draft() 方法"
        )

    def _load_tools_draft(self):
        """加载 draft 版 ProjectTools 实例"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 未实现 _load_tools_draft() 方法"
        )


class LegacyProjectAdapter(ProjectAdapter, OldProjectAdapter):
    """
    兼容层：继承新协议 ProjectAdapter 和旧版 ProjectAdapter。

    现有 4 个项目暂时继承这个类，保持原有方法可用。
    迁移完成后可删除此类。

    注意：这个类同时满足新协议（提供 _load_* 访问器）和旧协议
    （保留 build_request 等业务方法），用于平滑迁移。
    """

    def __init__(self, spec: ProjectSpec):
        OldProjectAdapter.__init__(self, spec)
        ProjectAdapter.__init__(self, spec)

    # === 新协议访问器（优先使用 _load_* 方法，否则返回自身） ===

    def _try_load_role(self, role: str) -> Optional[Any]:
        """尝试加载指定角色的实例，如果未实现则返回 None"""
        loader_method = f"_load_{role}"
        loader = getattr(self, loader_method, None)
        if loader is None:
            return None
        try:
            return loader()
        except NotImplementedError as e:
            # 只有明确的"未实现"错误才返回 None
            if f"未实现 {loader_method}" in str(e):
                return None
            # 其他 NotImplementedError 继续抛出（可能是项目实现中的错误）
            raise

    def live(self):
        """兼容访问：优先使用 _load_live()，否则返回自身"""
        result = self._try_load_role("live")
        return result if result is not None else self

    def mock(self):
        """兼容访问：优先使用 _load_mock()，否则返回自身"""
        result = self._try_load_role("mock")
        return result if result is not None else self

    def judge(self):
        """兼容访问：优先使用 _load_judge()，否则返回自身"""
        result = self._try_load_role("judge")
        return result if result is not None else self

    def attribute(self):
        """兼容访问：优先使用 _load_attribute()，否则返回自身（支持 draft 切换）"""
        if self._use_draft("attribute"):
            result = self._try_load_role("attribute_draft")
            if result is not None:
                return result
        result = self._try_load_role("attribute")
        return result if result is not None else self

    def tools(self):
        """兼容访问：优先使用 _load_tools()，否则返回自身（支持 draft 切换）"""
        if self._use_draft("tools"):
            result = self._try_load_role("tools_draft")
            if result is not None:
                return result
        result = self._try_load_role("tools")
        return result if result is not None else self

    # === 加载方法（兼容层提供默认实现：未迁移的角色返回 NotImplementedError，由访问器捕获） ===

    def _load_live(self):
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 _load_live()")

    def _load_mock(self):
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 _load_mock()")

    def _load_judge(self):
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 _load_judge()")

    def _load_attribute(self):
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 _load_attribute()")

    def _load_tools(self):
        raise NotImplementedError(f"{self.__class__.__name__} 未实现 _load_tools()")
