"""本任务可见的资源（spec/alg/resources.md §10.4）：交给校验代码的只有这一份，不是整张资源表。

资源表 = 本 case 的全部资源（存在）。可见 = 本任务给模型看的那份材料（白名单的筛选与投影都应用，即
``MaterialTable.view``）里出现的记录：凡是带 ``id`` 的对象，``id`` 等于某个资源的 ``name``，该资源可见；
直接资源可见则它的字段（模板资源）可见。不按给代码的那份（``for_code`` 不做投影、比模型看到的多）算：
能引的只能是模型看得到的。
可见范围由白名单自然得到，各轴不另算；校验仍只看得到白名单里的东西（demand/axis_loop.md §3.4.3）。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from impl.core.resources import CiteResult, ResourceTable, cite

FIELDS = "/fields/"


def _ids(value: Any, out: set[str]) -> set[str]:
    if isinstance(value, Mapping):
        if isinstance(value.get("id"), str):
            out.add(value["id"])
        for child in value.values():
            _ids(child, out)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _ids(child, out)
    return out


class Visible:
    """只读：按材料里的写法换地址、判可见；读不到不可见资源的正文。"""

    def __init__(self, table: ResourceTable, materials: Mapping[str, Any]) -> None:
        self._table = table
        self.uris = frozenset(block.uri for name in _ids(materials, set())
                              if (block := table.by_name(name)) is not None)

    def address(self, ref: str) -> Optional[str]:
        """材料里的写法 → 资源地址：``记录编号`` 或 ``记录编号/fields/字段名``；按 name 换，对不上任何资源为 None。"""
        ref = str(ref or "")
        block = self._table.by_name(ref)
        if block is not None:
            return block.uri
        record, sep, field = ref.rpartition(FIELDS)
        block = self._table.by_name(record) if sep and field else None
        return block.uri + FIELDS + field if block is not None else None

    def cite(self, ref: str, quote: str) -> CiteResult:
        """按材料里的写法核一条引用：换成地址后交资源层 cite，范围 = 本任务可见的资源。"""
        uri = self.address(ref)
        if uri is None:
            return CiteResult(False, "no_address", address=str(ref or ""))
        return cite(self._table, uri, quote, scope=self.uris)
