"""协议层动态发现公用模块。

scaffold_project.py 和 verify_protocol_compliance.py 共用，避免发现逻辑重复导致口径分裂。
协议演进（新增 @abstractmethod / 新增角色 / 基类改名）时只改这里，两个脚本自动同步。

发现依据（spec/adapter.md 命名规范）：
- 角色基类：impl/core/*_protocol.py 中的 Project<Role> 类
- 必须实现项：该类中 @abstractmethod 标记的方法（__abstractmethods__）
- 中转站 ProjectAdapter：__abstractmethods__ 全是 _load_* 命名
- LegacyProjectAdapter：重写了所有 _load_*（不再 abstract），但仍可能继承旧版 build_request 等
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
    """发现中转站 ProjectAdapter 基类 + LegacyProjectAdapter 兼容层。

    中转站：__abstractmethods__ 非空，且全是 _load_* 命名（加载方法）。
        旧版 ProjectAdapter（adapter.py）的 abstract 是 build_request 等业务方法，不符合，自动排除。
    Legacy：继承中转站，但把所有 _load_* 重写为非抽象（_load_* 不再出现在 __abstractmethods__）。
        仍可能继承旧版 build_request 等 abstract，故不能用"__abstractmethods__ 为空"判断。
    不写死文件名（adapter_v2.py 是迁移期临时名，迁完会改回 adapter.py）。

    返回 (station_base, legacy_base)，legacy_base 可能为 None。
    """
    import impl.core as core_pkg
    station_candidates: List[Type] = []
    legacy_candidates: List[Type] = []
    for _finder, mod_name, _ispkg in pkgutil.iter_modules(core_pkg.__path__):
        full = f"{CORE_PKG}.{mod_name}"
        try:
            module = importlib.import_module(full)
        except Exception:
            continue
        for cls_name, bucket in (
            ("ProjectAdapter", station_candidates),
            ("LegacyProjectAdapter", legacy_candidates),
        ):
            cls = getattr(module, cls_name, None)
            if isinstance(cls, type):
                bucket.append(cls)

    station = None
    for cls in station_candidates:
        abstracts = getattr(cls, "__abstractmethods__", set()) or set()
        if abstracts and all(n.startswith("_load_") for n in abstracts):
            station = cls
            break
    if station is None:
        raise RuntimeError(
            "未找到中转站形态的 ProjectAdapter 基类"
            "（__abstractmethods__ 全是 _load_* 的那个）。"
            "可能是协议尚未迁移到中转站形态，或基类命名变了。"
        )

    station_loads = {n for n in getattr(station, "__abstractmethods__", set()) if n.startswith("_load_")}
    legacy = None
    for cls in legacy_candidates:
        if cls is station or not issubclass(cls, station):
            continue
        cls_abstracts = getattr(cls, "__abstractmethods__", set()) or set()
        # Legacy 把所有 _load_* 都重写为非抽象了
        if not (station_loads & cls_abstracts):
            legacy = cls
            break
    return station, legacy


def discover_adapter_base() -> Type:
    """仅返回中转站 ProjectAdapter 基类（scaffold 用）。"""
    station, _ = discover_adapter_bases()
    return station
