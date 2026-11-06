"""挂载与读取（spec/alg/resources.md §4、§10）：一个 case 一张资源表，由声明了资源的材料往里挂直接资源。

对外的读法照 MCP：``list`` = ``resources/list``（直接资源的描述），``templates`` = ``resources/templates/list``
（各资源类型声明的模板），``read`` = ``resources/read``（直接资源、模板资源都按地址读）。
地址只要求唯一，不表示层级（MCP）：``trace://turn1`` 与 ``trace://turn1/records/…`` 是两个互不包含的资源。
"""
from __future__ import annotations

from typing import Any, Mapping

from mcp.types import ReadResourceResult, Resource, ResourceTemplate

from .spec import TYPE_KEY, Address, Block
from .types import TYPES


class ResourceTable:
    def __init__(self) -> None:
        self._items: dict[str, Block] = {}
        self._names: dict[str, str] = {}   # name → 地址；name 唯一是我们的约束（MCP 不要求），按它换算地址

    def mount(self, uri: str, type: str, body: Any, *, name: str, title: str | None = None,
              description: str | None = None, meta: Mapping[str, Any] | None = None) -> Block:
        """挂一个直接资源：信息源给地址、类型、正文与目录标签；``mimeType``、``size`` 由类型算，类型名记进 ``_meta``。"""
        address = str(Address.parse(uri))
        if type not in TYPES:
            raise ValueError(f"未知资源类型 {type!r}；可用：{sorted(TYPES)}")
        kind = TYPES[type]
        descriptor = Resource(uri=uri, name=name, title=title, description=description, mimeType=kind.mime_type,
                              size=len(kind.text(body).encode()), _meta={**(meta or {}), TYPE_KEY: type})
        if str(descriptor.uri) != address:
            raise ValueError(f"地址不合 RFC 3986（会被改写成 {descriptor.uri}）：{uri}")
        if self.part(address) is not None or any(self._template_of(key, address) for key in self._items):
            raise ValueError(f"同一地址只能是一个资源（已挂，或与某个模板资源的地址相同）：{uri}")
        if name in self._names:
            raise ValueError(f"同一 name 只能挂一次：{name}")
        block = self._items[address] = Block(descriptor, body)
        self._names[name] = address
        return block

    def by_name(self, name: str) -> Block | None:
        address = self._names.get(name)
        return self._items[address] if address else None

    def get(self, uri: str) -> Block | None:
        return self._items.get(str(Address.parse(uri)))

    def part(self, uri: str) -> tuple[Block, str] | None:
        """地址所指的资源：直接资源 → (这一块, "")；模板资源 → (所属那一块, 块里的节点)；都不是返回 None。"""
        address = str(Address.parse(uri))
        if address in self._items:
            return self._items[address], ""
        for name, kind in TYPES.items():
            hit = kind.resolve(address)
            block = self._items.get(hit[0]) if hit else None
            if block is not None and block.type == name:
                return block, hit[1]
        return None

    def _template_of(self, key: str, block_address: str) -> bool:
        """已挂的 key 是不是 block_address 这一块的模板地址（先挂字段、后挂它所属的记录）。"""
        return any((kind.resolve(key) or ("",))[0] == block_address for kind in TYPES.values())

    def list(self) -> list[Resource]:
        return [block.descriptor for block in self._items.values()]

    def templates(self) -> list[ResourceTemplate]:
        used = sorted({(block.type, Address.parse(block.uri).scheme) for block in self._items.values()})
        return [t for name, scheme in used for t in TYPES[name].templates(scheme)]

    def read(self, uri: str) -> ReadResourceResult:
        address = str(Address.parse(uri))
        part = self.part(address)
        if part is None:
            raise LookupError(f"资源不存在：{uri}")
        block, node = part
        return ReadResourceResult(contents=[TYPES[block.type].read(block, node, address)])

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items.values())
