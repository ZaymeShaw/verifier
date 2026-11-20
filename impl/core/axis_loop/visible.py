"""本任务可见的资源（spec/alg/resources.md §10.4、§11.1）：由轴定义 ``resources`` 主动推送的 URI 集合直接决定。

不再递归扫描普通材料字典猜测 ``id``：
- 直接资源 URI（如 ``trace://turn1/records/observations/15``）开放整块及其全部模板字段；
- 模板资源 URI（如 ``trace://turn1/records/observations/15/fields/input``）仅开放该模板节点，同块未列出的其他字段仍为 ``out_of_scope``。
地址写法同时接受完整 URI（``trace://...``）与短名（``记录编号`` 或 ``记录编号/fields/字段名``）。
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from impl.core.resources import Address, CiteResult, ResourceTable, TYPES, cite
from impl.core.resources.cite import _hint

FIELDS = "/fields/"


class Visible:
    """只读：按显式声明的 URI 白名单换算地址、判可见、核对引文。"""

    def __init__(self, table: ResourceTable, uris: Iterable[str] = (), *,
                 inlined: Iterable[str] = ()) -> None:
        self._table = table
        blocks: set[str] = set()
        templates: set[str] = set()
        template_fields: dict[str, set[str]] = {}
        for raw in uris:
            try:
                part = table.part(str(raw))
            except ValueError:
                continue
            if part is None:
                continue
            block, node = part
            if not node:
                blocks.add(block.uri)
            else:
                templates.add(str(Address.parse(str(raw))))
                kind = TYPES[block.type]
                fname = kind.field_name(node) if hasattr(kind, "field_name") else ""
                if fname:
                    template_fields.setdefault(block.uri, set()).add(fname)
        self.uris = frozenset(blocks)
        self.template_uris = frozenset(templates)
        self._template_fields = {u: frozenset(fs) for u, fs in template_fields.items() if u not in blocks}
        self.inlined = frozenset(inlined)

    def address(self, ref: str) -> Optional[str]:
        """引用出处写法 → 标准资源 URI：接受完整 URI、``记录编号`` 或 ``记录编号/fields/字段名``。"""
        ref = str(ref or "").strip()
        if not ref:
            return None
        if "://" in ref:
            try:
                addr = str(Address.parse(ref))
            except ValueError:
                return None
            return addr if self._table.part(addr) is not None else None
        block = self._table.by_name(ref)
        if block is not None:
            return block.uri
        record, sep, field = ref.rpartition(FIELDS)
        block = self._table.by_name(record) if sep and field else None
        return block.uri + FIELDS + field if block is not None else None

    def cite(self, ref: str, quote: str) -> CiteResult:
        """按白名单范围核一条引用：直接资源可见则其任意字段可见；仅模板字段可见时仅放行记录属性与已开放字段，同块未开放字段报 ``out_of_scope``。"""
        uri = self.address(ref)
        if uri is None:
            return CiteResult(False, "no_address", address=str(ref or ""))
        part = self._table.part(uri)
        if part is None:
            return CiteResult(False, "no_address", address=uri)
        block, node = part
        if block.uri in self.uris:
            return cite(self._table, uri, quote, scope=self.uris)
        if node:
            if uri in self.template_uris:
                return cite(self._table, uri, quote, scope=None)
            return CiteResult(False, "out_of_scope", address=uri, block=block.uri)
        allowed = self._template_fields.get(block.uri)
        if not allowed:
            return CiteResult(False, "out_of_scope", address=uri, block=block.uri)
        kind = TYPES[block.type]
        res = cite(self._table, uri, quote, scope=None)
        if not res.ok:
            hint = _hint(quote, kind.present(block, allowed)) if res.reason == "not_found" else ""
            return CiteResult(False, res.reason, address=uri, block=block.uri, hint=hint)
        kept = tuple(
            r for r in res.regions
            if (p := kind.place(block, r.node)).part == "attribute"
            or (p.part == "field" and bool(p.field) and p.field in allowed)
        )
        if not kept:
            return CiteResult(False, "out_of_scope", address=uri, block=block.uri)
        places = tuple(sorted({kind.place(block, r.node) for r in kept}))
        return CiteResult(True, address=uri, block=block.uri, regions=kept, places=places)
