"""材料：标准名注册表 + 白名单 + 每个 case 一张材料表（spec/alg/axis_loop.md §4）。

标准名按命名空间：`case.*`（这次运行）、`scenario.*`（场景登记）、`axis.*`（场景对当前轴的描述）由项目登记取值函数；
`result.<轴id>` 是轴被接受后的完整结果，schema 就是那个轴的输出 schema，不用登记。
白名单条目 = 标准名，可再接路径与字段投影：`result.expectations.expectations[].{expectation_id, statement}`。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from . import paths
from .text import dump

BUILTIN_SPACES = ("case", "scenario", "axis")
RESULT_SPACE = "result"


class MaterialUnavailable(RuntimeError):
    """内置材料这个 case 取不到（例：trace 存档是采集失败）：整个 case 记运行失败（spec/alg/axis_loop.md §4.1）。"""


@dataclass(frozen=True)
class Material:
    """load(case, context) -> 值，一个 case 一个值（不带参数）。context 只有 axis：读这份材料的轴（axis.* 用）。"""

    name: str
    schema: Mapping[str, Any]
    description: str
    load: Callable[[Any, Mapping[str, Any]], Any]


@dataclass(frozen=True)
class Entry:
    text: str          # 配置里的原文，也是放进上下文时的标题
    name: str          # 标准名：case.deliveries / result.expectations
    path: paths.Path   # 名字之后的部分；空 = 取整个值

    @property
    def space(self) -> str:
        return self.name.split(".", 1)[0]

    @property
    def axis(self) -> str:
        """result.* 条目指向的轴。"""
        return self.name.split(".", 1)[1] if self.space == RESULT_SPACE else ""


def parse_entry(text: str) -> Entry:
    raw = str(text or "").strip()
    head, _, rest = raw.partition(".")
    if head not in (*BUILTIN_SPACES, RESULT_SPACE) or not rest:
        raise ValueError(f"材料条目 {raw!r} 必须以 {'/'.join((*BUILTIN_SPACES, RESULT_SPACE))}.<名字> 开头")
    name_part, _, path_part = rest.partition(".")
    if "{" in name_part:  # result.x.{a,b} 这种：投影直接挂在名字上
        name_part, path_part = name_part.split("{", 1)[0].rstrip("."), "{" + rest.split("{", 1)[1]
    return Entry(raw, f"{head}.{name_part}", paths.parse(path_part))


class Registry:
    """内置材料注册表（代码里维护的字典）。"""

    def __init__(self, materials: Sequence[Material] = ()) -> None:
        self._items: dict[str, Material] = {}
        for item in materials:
            self.register(item)

    def register(self, material: Material) -> None:
        if material.name.split(".", 1)[0] not in BUILTIN_SPACES:
            raise ValueError(f"内置材料 {material.name} 必须在 {BUILTIN_SPACES} 命名空间里")
        if material.name in self._items:
            raise ValueError(f"内置材料重复登记：{material.name}")
        self._items[material.name] = material

    def get(self, name: str) -> Optional[Material]:
        return self._items.get(name)

    def names(self) -> list[str]:
        return sorted(self._items)


class MaterialTable:
    """一个 case 的材料表：内置材料按需取一次并缓存；轴结果随台账写入。"""

    def __init__(self, registry: Registry, case: Any) -> None:
        self.registry = registry
        self.case = case
        self._builtin: dict[tuple, Any] = {}
        self.results: dict[str, Optional[Mapping[str, Any]]] = {}  # 轴 id → 完整结果；None = 没出现 / 没启用

    def full(self, name: str, axis_id: str = "") -> Any:
        """标准名的完整值；result.* 的轴没出现时为 None。"""
        if name.startswith(RESULT_SPACE + "."):
            return self.results.get(name.split(".", 1)[1])
        material = self.registry.get(name)
        if material is None:
            raise KeyError(f"未登记的内置材料：{name}")
        key = (name, axis_id if name.startswith("axis.") else "")
        if key not in self._builtin:
            self._builtin[key] = material.load(self.case, {"axis": axis_id})
        return self._builtin[key]

    def take(self, entry: Entry, axis_id: str = "") -> Any:
        """按条目取值（给模型看的那份：筛选、下钻、投影都应用）。"""
        value = self.full(entry.name, axis_id)
        return None if value is None else paths.extract(value, entry.path)

    def view(self, entries: Sequence[Entry], axis_id: str = "") -> dict[str, Any]:
        return {entry.text: self.take(entry, axis_id) for entry in entries}

    def for_code(self, entries: Sequence[Entry], axis_id: str = "") -> dict[str, Any]:
        """给代码看的那份：{标准名: 值}，保留原结构，只应用元素筛选（同一名字多条选择时依次筛选）。"""
        out: dict[str, Any] = {}
        for entry in entries:
            value = out.get(entry.name, self.full(entry.name, axis_id))
            out[entry.name] = None if value is None else paths.prune(value, entry.path)
        return out


def render(values: Mapping[str, Any]) -> str:
    """材料放进上下文：每一项一段，以条目原文为标题；没启用的上游写明。"""
    parts = []
    for title, value in values.items():
        body = "（未启用或未出现）" if value is None else dump(value)
        parts.append(f"【{title}】\n{body}")
    return "\n".join(parts)
