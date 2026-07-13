"""协议层基类工具

提供协议层基类的通用功能，包括：
- 禁止覆盖检查装饰器
- 协议层基类通用功能
"""
from abc import ABC
from typing import Set, Type


def forbidden_overrides(forbidden_methods: Set[str]):
    """
    装饰器：检查子类是否覆盖了禁止的方法。

    用法：
        class _MyProtocol(ABC):
            _FORBIDDEN_OVERRIDES = frozenset({'method1', 'method2'})

            def __init_subclass__(cls, **kwargs):
                super().__init_subclass__(**kwargs)
                check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    Args:
        forbidden_methods: 禁止覆盖的方法名集合
    """
    def decorator(cls):
        original_init_subclass = cls.__init_subclass__

        def new_init_subclass(cls, **kwargs):
            super().__init_subclass__(**kwargs)
            for method_name in forbidden_methods:
                if method_name in cls.__dict__:
                    raise TypeError(
                        f"类 {cls.__name__} 不能覆盖协议方法 '{method_name}'。\n"
                        f"这是协议层锁定的流程方法，项目应该实现扩展点。\n"
                        f"禁止覆盖的方法列表: {', '.join(sorted(forbidden_methods))}"
                    )

        cls.__init_subclass__ = classmethod(new_init_subclass)
        return cls

    return decorator


def check_forbidden_overrides(cls: type, forbidden_methods: Set[str]) -> None:
    """
    检查子类是否覆盖了禁止的方法。

    Args:
        cls: 子类
        forbidden_methods: 禁止覆盖的方法名集合

    Raises:
        TypeError: 如果子类覆盖了禁止的方法
    """
    for method_name in forbidden_methods:
        if method_name in cls.__dict__:
            raise TypeError(
                f"类 {cls.__name__} 不能覆盖协议方法 '{method_name}'。\n"
                f"这是协议层锁定的流程方法，项目应该实现扩展点。\n"
                f"禁止覆盖的方法列表: {', '.join(sorted(forbidden_methods))}"
            )
