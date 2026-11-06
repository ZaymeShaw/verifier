"""规范文本、区间对照表与带下标映射的比对（spec/alg/resources.md §2、§6）。

规范文本与 ``impl.core.axis_loop.text.dump`` 逐字一致（``json.dumps(ensure_ascii=False, sort_keys=True)``）；
区间对照表记每个 JSON 节点在文本里的 ``[start, end)``：对象成员记"键 + 冒号 + 值"整段，值另记一条。
比对的宽容规则：沿用 ``axis_loop.text._normalize``（去空白、反斜杠、转义的换行制表），再把中英文各式引号归一
（同说法轴 ``claims/checks.py`` 的引号表；过程轴现有核对也把弯引号当直引号）；这里多了下标映射。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .spec import pointer_join

# 只抹掉不改变意思的写法差异（resources.md §10.5）：引号（中英文各式）与 markdown 强调符号两边都去掉；内容一个字不抹
IGNORED = frozenset('"“”„‟＂「」『』' + "'‘’‚‛＇" + "*`")


@dataclass(frozen=True)
class Span:
    pointer: str
    start: int
    end: int
    member: bool  # True = 对象成员整段（键 + 冒号 + 值）；False = 值本身


def render(value: Any) -> tuple[str, list[Span]]:
    parts: list[str] = []
    spans: list[Span] = []
    pos = 0

    def put(text: str) -> None:
        nonlocal pos
        parts.append(text)
        pos += len(text)

    def node(v: Any, pointer: str) -> None:
        start = pos
        if isinstance(v, Mapping):
            put("{")
            for i, key in enumerate(sorted(v)):
                if i:
                    put(", ")
                child = pointer_join(pointer, key)
                member_start = pos
                put(json.dumps(str(key), ensure_ascii=False) + ": ")
                node(v[key], child)
                spans.append(Span(child, member_start, pos, True))
            put("}")
        elif isinstance(v, (list, tuple)):
            put("[")
            for i, item in enumerate(v):
                if i:
                    put(", ")
                node(item, pointer_join(pointer, i))
            put("]")
        else:
            put(json.dumps(v, ensure_ascii=False))
        spans.append(Span(pointer, start, pos, False))

    node(value, "")
    return "".join(parts), spans


def normalize_map(text: str) -> tuple[str, list[int]]:
    """宽容比对的规范化：转义写法的 \\n \\t \\r 当空白，去空白与反斜杠，去引号与 markdown 强调符号（``IGNORED``）；
    返回规范化文本与每个字符的原下标。"""
    out: list[str] = []
    index: list[int] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            j = i
            while j < n and text[j] == "\\":
                j += 1
            i = j + 1 if j < n and text[j] in "ntr" else j
            continue
        if ch.isspace() or ch in IGNORED:
            i += 1
            continue
        out.append(ch)
        index.append(i)
        i += 1
    return "".join(out), index


def find_all(quote: str, text: str) -> list[tuple[int, int]]:
    """摘句在原文里的全部命中（可重叠），按宽容规则比对，返回原文下标区间。"""
    target, _ = normalize_map(quote)
    if not target:
        return []
    norm, index = normalize_map(text)
    hits, at = [], norm.find(target)
    while at >= 0:
        hits.append((index[at], index[at + len(target) - 1] + 1))
        at = norm.find(target, at + 1)
    return hits


def closest(quote: str, text: str) -> tuple[int, int] | None:
    """摘句与原文最长的公共片段（规范化后比），只作修改提示。"""
    from difflib import SequenceMatcher

    target, _ = normalize_map(quote)
    norm, index = normalize_map(text)
    if not target or not norm:
        return None
    m = SequenceMatcher(None, norm, target, autojunk=False).find_longest_match(0, len(norm), 0, len(target))
    if m.size < 2:
        return None
    return index[m.a], index[m.a + m.size - 1] + 1


def smallest(spans: list[Span], start: int, end: int) -> Span:
    """包含 [start, end) 的最小节点；同长时取值本身。"""
    inside = [s for s in spans if s.start <= start and end <= s.end]
    return min(inside, key=lambda s: (s.end - s.start, s.member))
