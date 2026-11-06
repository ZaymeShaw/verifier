"""引用核对的公共入口（spec/alg/resources.md §10.5）。

依次判：地址所指的资源存在 → 在可见范围内 → 在这个资源的规范文本里找得到；找到即过。
资源是最小引用单位：命中几处都算过，如实报出各处所在节点与位置；一条引用够不够支撑结论由使用方判。
读没读过不在这里判：逐字原文本身是读过的证明；读的与核的是同一份（展示与正文不一致时修展示）。
地址只收完整的资源地址，引用方自己把写法转成地址。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Collection, Sequence

from .mount import ResourceTable
from .text import closest, render, smallest
from .types import TYPES
from .types.record_set import Place

HINT_CHARS = 60


@dataclass(frozen=True)
class Region:
    node: str                         # 包含命中的最小节点（这一块正文里的位置）
    start: int                        # 这一块规范文本上的区间
    end: int


@dataclass(frozen=True)
class CiteResult:
    ok: bool
    reason: str = ""                  # no_address / out_of_scope / not_found
    address: str = ""                 # 地址所指的资源
    block: str = ""                   # 所属那一块（直接资源）的地址
    regions: Sequence[Region] = field(default_factory=tuple)
    places: Sequence[Place] = field(default_factory=tuple)   # 各处命中所在位置（去重、排序）
    hint: str = ""


def cite(table: ResourceTable, uri: str, quote: str, *, scope: Collection[str] | None = None) -> CiteResult:
    """``scope``：可引的块地址（本任务可见的资源），None 为不限。"""
    try:
        part = table.part(uri)
    except ValueError:
        return CiteResult(False, "no_address", address=str(uri))
    if part is None:
        return CiteResult(False, "no_address", address=uri)
    block, node = part
    kind = TYPES[block.type]
    if node and kind.slice(block.body, node) is None:
        return CiteResult(False, "no_address", address=uri, block=block.uri)
    if scope is not None and block.uri not in scope:
        return CiteResult(False, "out_of_scope", address=uri, block=block.uri)
    hits = kind.locate(block, quote, node=node) or []
    if not hits:
        return CiteResult(False, "not_found", address=uri, block=block.uri, hint=_hint(quote, block.body))
    regions = tuple(Region(h.node.pointer, h.start, h.end) for h in hits)
    places = tuple(sorted({kind.place(block, r.node) for r in regions}))
    return CiteResult(True, address=uri, block=block.uri, regions=regions, places=places)


def _hint(quote: str, body) -> str:
    text, spans = render(body)
    found = closest(quote, text)
    if not found:
        return "这里没有相近的原文"
    near = smallest(spans, *found)
    lo, hi = max(near.start, found[0] - 10), min(near.end, found[1] + HINT_CHARS)
    return f"最接近的是 {near.pointer or '/'} 里的：{text[lo:hi]}"
