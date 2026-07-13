"""Adapter 中转站：只加载并暴露各专项模块。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from impl.core.schema import ProjectSpec


class ProjectAdapter(ABC):
    """
    新协议：统一中转站。

    只做加载并暴露各专项模块，不承载任何业务逻辑。

    项目继承这个类，只需实现 4 个 _load_* 方法：
    - _load_live: 返回 ProjectLive 实例
    - _load_mock: 返回 ProjectMock 实例
    - _load_judge: 返回 ProjectJudge 实例
    - _load_attribute: 返回 ProjectAttribute 实例
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
        """访问 ProjectJudge 实例。"""
        return self._get_or_load("judge")

    def attribute(self):
        """访问 ProjectAttribute 实例。"""
        return self._get_or_load("attribute")

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
