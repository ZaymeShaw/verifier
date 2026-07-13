"""协议层动态发现公用模块。

scaffold_project.py 和 verify_protocol_compliance.py 共用，避免发现逻辑重复导致口径分裂。
协议演进（新增 @abstractmethod / 新增角色 / 基类改名）时只改这里，两个脚本自动同步。

发现依据（spec/adapter.md 命名规范）：
- 角色基类：impl/core/*_protocol.py 中的 Project<Role> 类
- 必须实现项：该类中 @abstractmethod 标记的方法（__abstractmethods__）
- 中转站 ProjectAdapter：__abstractmethods__ 全是 _load_* 命名
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from typing import List, Optional, Tuple, Type

CORE_PKG = "impl.core"


def class_prefix(project_id: str) -> str:
    """把 project_id 转成类名前缀（去掉前导非字母，按 [-_] 分词驼峰化）。

    例: "_scaffold-test" -> "ScaffoldTest"
         "QA" -> "QA"
         "client_search" -> "ClientSearch"
    """
    cleaned = re.sub(r"^[^a-zA-Z]+", "", project_id)
    parts = [p for p in re.split(r"[-_]", cleaned) if p]
    if not parts:
        return "Project"
    return "".join(p.capitalize() for p in parts)


def discover_role_bases() -> List[Tuple[str, Type]]:
    """扫描 impl/core/*_protocol.py，发现所有 Project<Role> 操作层基类。

    返回 [(role_name, base_class), ...]，role_name = 去掉 Project 前缀并小写化。
    例如 ProjectLive -> ("live", ProjectLive)。
    """
    import impl.core as core_pkg
    roles: List[Tuple[str, Type]] = []
    for _finder, mod_name, _ispkg in pkgutil.iter_modules(core_pkg.__path__):
        if not mod_name.endswith("_protocol"):
            continue
        full = f"{CORE_PKG}.{mod_name}"
        try:
            module = importlib.import_module(full)
        except Exception:
            continue
        for attr in dir(module):
            obj = getattr(module, attr)
            if not isinstance(obj, type):
                continue
            if not attr.startswith("Project") or attr == "ProjectAdapter":
                continue
            if not hasattr(obj, "__abstractmethods__"):
                continue
            role = attr[len("Project"):].lower()
            roles.append((role, obj))
    return roles


def discover_adapter_bases() -> Tuple[Type, Optional[Type]]:
    """发现唯一的中转站 ProjectAdapter 基类。"""
    import impl.core.adapter_v2 as adapter_module

    station = getattr(adapter_module, "ProjectAdapter")
    abstracts = getattr(station, "__abstractmethods__", set()) or set()
    if not abstracts or not all(name.startswith("_load_") for name in abstracts):
        raise RuntimeError("ProjectAdapter 必须只声明 _load_* 抽象方法")
    return station, None


def discover_adapter_base() -> Type:
    """仅返回中转站 ProjectAdapter 基类（scaffold 用）。"""
    station, _ = discover_adapter_bases()
    return station
