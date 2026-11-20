"""公共资源区与大材料的按需读取与搜索（spec/alg/resources.md §11.3、spec/alg/axis_loop.md §4.4）。

契约：
- 公共资源区（``name='resources'``）直连本 Loop 的 ``ResourceZone``，只暴露当前已开放的资源与字段（防污染）；
  ``ids`` 同时接受短名（``记录编号`` / ``记录编号/fields/字段名``）与完整 URI（``trace://...``）。
- 普通超限材料（``materials``）在任务卡内放前 ``PREVIEW_CHARS`` 字预览，可按 ``path`` / ``offset`` 读取。
- 点名 ``read_material`` 单次上限直接为 ``READ_CHARS = 60_000``（删去 ``full`` 二道门参数；单批合计 ``COLLECT_CHARS = 60_000``）：
  - 结构化对象超限时，将超长子字段切成 ``STUB_CHARS = 2_000`` 字预览 + 子 ``path`` 下钻；仍放不下则给 ``shape()`` 结构图；
  - 单段纯文本超限时，直接返回 ``offset .. offset + READ_CHARS`` 并提示续读 ``offset``，杜绝死循环。
- 同一 Loop 内已在公共资源区内联或此前已完整返回过的 ``(资源, path, offset)`` 重复点名时直接短提示指向上文；
  跨记录相同大段文本（``>= REPEAT_CHARS = 2_000`` 字）折叠时提示原文见前文，且引用本记录时 ``ref`` 仍填本记录自身编号。
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Optional

from impl.tools.protocol import VerifiableTool

from .text import dump
from .zone import ZONE_NAME, ResourceZone

READ, SEARCH = "read_material", "search_material"
PREVIEW_CHARS = 2_000       # 普通材料内联超限时的预览字数
STUB_CHARS = 2_000          # 结构化记录超 60k 时超长子字段的预览字数
READ_CHARS = 60_000         # 单条点名读取上限
COLLECT_CHARS = 60_000      # 一次 read_material 调用合计上限
REPEAT_CHARS = 2_000        # 跨记录重复折叠阈值（仅折叠系统提示词/长历史级大块，不折短输出）
SEARCH_HITS = 12
SNIPPET_CHARS = 240


def summarize(title: str, value: Any, limit: int) -> Any:
    """普通材料放进任务卡前的大小检查：不超限原样放入；超限放开头预览与读法。"""
    text = dump(value)
    if value is None or len(text) <= limit:
        return value
    return {
        "说明": f"正文太大（{len(text)} 字），这里只给开头预览；用 {READ}(name={title!r}, path=..., offset=...) 按位置或偏移读",
        "preview": text[:PREVIEW_CHARS],
    }


def shape(node: Any) -> Any:
    """结构图：字段名与各自大小，不含正文。"""
    if isinstance(node, Mapping):
        return {k: f"{type(v).__name__} {len(dump(v))} 字" for k, v in node.items()}
    if isinstance(node, list):
        return {"list": len(node), "items": [f"{i}: {type(v).__name__} {len(dump(v))} 字" for i, v in enumerate(node[:60])]}
    return f"{type(node).__name__} {len(dump(node))} 字"


def _parsed(node: Any) -> Any:
    """值是 JSON 文本（MCP、工具返回常见）时解出来，才能按位置往下走、按字段搜。"""
    if isinstance(node, str) and node[:1] in "[{":
        try:
            return json.loads(node)
        except ValueError:
            return node
    return node


def drill(node: Any, path: str) -> Any:
    """按 a/b/0 这样的位置往下取；值是 JSON 文本的先解开再走。走不通抛 KeyError，并说明这一层有什么。"""
    for part in [p for p in str(path or "").split("/") if p]:
        node = _parsed(node)
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            here = (f"这一层的字段：{sorted(node)[:30]}" if isinstance(node, Mapping)
                    else f"这一层是 {len(node)} 项的列表，用 0–{len(node) - 1}" if isinstance(node, list)
                    else f"这一层已是 {type(node).__name__}，不能再往下")
            raise KeyError(f"位置 {path!r} 走不通：{part!r} 不在这一层；{here}")
    return node


def _hits(node: Any, path: str, query: str):
    """按字段找：(位置, 命中处前后的原文)；JSON 文本解开后逐个字段找。"""
    node = _parsed(node)
    if isinstance(node, Mapping):
        for k, v in node.items():
            yield from _hits(v, f"{path}/{k}" if path else str(k), query)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _hits(v, f"{path}/{i}" if path else str(i), query)
    elif node is not None:
        text = node if isinstance(node, str) else dump(node)
        at = text.find(query)
        if at >= 0:
            start = max(0, at - SNIPPET_CHARS // 3)
            yield path, text[start:start + SNIPPET_CHARS]


def _leaves(node: Any, path: str):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, Mapping):
        for k, v in node.items():
            yield from _leaves(v, f"{path}/{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _leaves(v, f"{path}/{i}" if path else str(i))


def _put(node: Any, path: str, value: Any) -> Any:
    if not path:
        return value
    head, _, rest = path.partition("/")
    if isinstance(node, list):
        return [_put(v, rest, value) if str(i) == head else v for i, v in enumerate(node)]
    return {k: _put(v, rest, value) if k == head else v for k, v in node.items()}


def _fit(node: Any, limit: int, base: str, stub_chars: int) -> tuple[Any, set[str]]:
    """结构化节点超限时，从最长的字符串叶子起换成预览（开头 + 字数 + path），直到放得下；小的部分照给全文。"""
    size, cut = len(dump(node)), set()
    for at, text in sorted(_leaves(node, ""), key=lambda x: -len(x[1])):
        if not at:
            continue
        if size <= limit or len(text) <= stub_chars + 200:
            break
        full_path = "/".join(p for p in (base, at) if p)
        stub = f"〔预览，全文 {len(text)} 字；读全文请传 path={full_path!r}〕{text[:stub_chars]}…"
        node, size, cut = _put(node, at, stub), size - len(dump(text)) + len(dump(stub)), cut | {text}
    return node, cut


def _slice_text(text: str, limit: int, base: str, offset: int) -> dict[str, Any]:
    start = max(0, int(offset or 0))
    total = len(text)
    if start >= total and total > 0:
        return {"content": "", "hint": f"offset={start} 已超出总长度 {total} 字"}
    end = min(total, start + limit)
    chunk = text[start:end]
    if start == 0 and end == total:
        return {"content": chunk}
    tail = (f"；继续往后读请传 offset={end}" + (f", path={base!r}" if base else "")
            if end < total else "（已到末尾）")
    return {"content": chunk, "hint": f"全文共 {total} 字，本次显示 {start}..{end} 字{tail}"}


def _render(node: Any, limit: int, base: str = "", offset: int = 0,
            stub_chars: int = STUB_CHARS) -> tuple[dict[str, Any], set[str], bool]:
    """→ (返回给模型的字典, 被截断没给全的正文段集合, 本次请求的目标切片是否已完整给出)。"""
    start = max(0, int(offset or 0))
    if isinstance(node, str):
        out = _slice_text(node, limit, base, start)
        partial = start > 0 or len(node) > limit
        return out, ({node} if partial else set()), True
    if start > 0:
        return _slice_text(dump(node), limit, base, start), set(), True
    text = dump(node)
    if len(text) <= limit:
        return {"content": node}, set(), True
    fitted, cut = _fit(node, limit, base, stub_chars)
    if cut and len(dump(fitted)) <= limit:
        return {
            "content": fitted,
            "hint": f"整条共 {len(text)} 字，超过单次上限 {limit} 字：超长字段已给前 {stub_chars} 字预览，按预览里写的 path 单独取全文",
        }, cut, False
    return {
        "shape": shape(node),
        "hint": f"整条共 {len(text)} 字，超过单次上限 {limit} 字：请按 shape 里的字段带 path 下钻（或加 offset 分段读）",
    }, set(), False


class Reader:
    """一个 Loop 实例的读取与搜索工具：支持公共资源区 ``name='resources'`` 与普通材料。"""

    def __init__(self, readable: Callable[[], Mapping[str, Any]], zone: Optional[ResourceZone] = None, *,
                 read_limit: int = READ_CHARS, stub_chars: int = STUB_CHARS,
                 repeat_chars: int = REPEAT_CHARS) -> None:
        self.readable = readable
        self.zone = zone
        self.read_limit = read_limit
        self.stub_chars = stub_chars
        self.repeat_chars = repeat_chars
        self.given: dict[str, str] = {}                     # 已完整给过的长段正文 → 首次出现的记录名
        self.delivered: dict[tuple[str, str, str, int], str] = {}  # (空间, 标识, path, offset) → 开放签名

    def _dedupe(self, node: Any, where: str, fresh: dict[str, str]) -> Any:
        """跨记录重复的大段正文（>= repeat_chars）折叠指向前文，但明确告知引用时仍填当前记录编号。"""
        if isinstance(node, str):
            first = self.given.get(node, where)
            if len(node) < self.repeat_chars or first == where:
                if len(node) >= self.repeat_chars:
                    fresh.setdefault(node, where)
                return node
            return f"〔内容与本会话前文 {first} 完全相同，共 {len(node)} 字；原文见前文，若本任务需引用本记录，ref 仍填本记录自己的编号〕"
        if isinstance(node, Mapping):
            return {k: self._dedupe(v, where, fresh) for k, v in node.items()}
        if isinstance(node, list):
            return [self._dedupe(v, where, fresh) for v in node]
        return node

    def _give(self, node: Any, where: str, path: str, offset: int) -> tuple[dict[str, Any], bool]:
        fresh: dict[str, str] = {}
        deduped = node if offset > 0 else self._dedupe(node, where, fresh)
        rendered, cut, complete = _render(deduped, self.read_limit, path, offset, self.stub_chars)
        if "content" in rendered:
            for text, at in fresh.items():
                if text not in cut:
                    self.given.setdefault(text, at)
        return rendered, complete

    def _available_names(self) -> list[str]:
        names = sorted(self.readable())
        if self.zone is not None and self.zone.has_open:
            names = [ZONE_NAME, *names]
        return names

    def _read_zone(self, ids: Optional[Sequence[str]], path: str, offset: int) -> dict[str, Any]:
        if self.zone is None or not self.zone.has_open:
            return {"isError": True, "error": f"当前没有开放的公共资源（能读的：{self._available_names()}）"}
        if not ids:
            return {"isError": True, "error": f"读公共资源区 {ZONE_NAME!r} 必须传 ids=[记录编号, ...]"}
        items, used = [], 0
        start = max(0, int(offset or 0))
        for ident in ids:
            block, record, sub_path, err = self.zone.resolve_open(ident)
            if err or block is None or record is None:
                items.append({"id": ident, "error": err or "没有这个编号"})
                continue
            full_path = "/".join(p for p in (sub_path, path) if p)
            req_field = sub_path.removeprefix("fields/") if sub_path.startswith("fields/") and not path else ""
            if start == 0 and not path and self.zone.already_inlined(block.uri, req_field):
                items.append({
                    "id": block.descriptor.name,
                    **({"path": full_path} if full_path else {}),
                    "already_shown": f"该资源已在上文【{ZONE_NAME}】内联给出全文，请直接查阅上文，无需重读",
                })
                continue
            sig = self.zone.open_signature(block.uri)
            dkey = (ZONE_NAME, block.uri, full_path, start)
            if self.delivered.get(dkey) == sig:
                items.append({
                    "id": block.descriptor.name,
                    **({"path": full_path} if full_path else {}),
                    "already_shown": f"本会话上文已完整返回过 {block.descriptor.name}"
                                     + (f" ({full_path})" if full_path else "") + "，请直接查阅上文，无需重读",
                })
                continue
            try:
                node = drill(record, full_path)
            except KeyError as exc:
                items.append({"id": ident, "error": str(exc)})
                continue
            rendered, complete = self._give(node, block.descriptor.name, full_path, start)
            size = len(dump(rendered))
            if used and used + size > COLLECT_CHARS:
                items.append({"id": ident, "error": f"本次合计已到 {COLLECT_CHARS} 字，剩余编号请下次再取"})
                continue
            used += size
            if complete:
                self.delivered[dkey] = sig
            items.append({
                "id": block.descriptor.name,
                **({"path": full_path} if full_path else {}),
                **({"offset": start} if start else {}),
                **rendered,
            })
        return {"name": ZONE_NAME, "records": items}

    def read(self, name: str, ids: Optional[Sequence[str]] = None, path: str = "", offset: int = 0) -> dict[str, Any]:
        if name == ZONE_NAME:
            return self._read_zone(ids, path, offset)
        values = self.readable()
        if name not in values:
            return {"isError": True, "error": f"{name} 不在当前能读的材料里（能读的：{self._available_names()}）"}
        value = values[name]
        if value is None:
            return {"isError": True, "error": f"{name} 未启用或未出现"}
        start = max(0, int(offset or 0))
        if ids:
            records = value.get("records") if isinstance(value, Mapping) and isinstance(value.get("records"), list) else None
            if records is None:
                return {"isError": True, "error": f"{name} 不是按编号存的记录，去掉 ids 改用 path / offset 读"}
            by_id = {str(r["id"]): r for r in records if isinstance(r, Mapping) and "id" in r}
            items, used = [], 0
            for ident in ids:
                record = by_id.get(str(ident))
                if record is None:
                    items.append({"id": ident, "error": "没有这个编号"})
                    continue
                dkey = (name, str(ident), path, start)
                if self.delivered.get(dkey) == "*":
                    items.append({"id": ident, **({"path": path} if path else {}),
                                  "already_shown": f"本会话上文已完整返回过 {ident}，请直接查阅上文，无需重读"})
                    continue
                try:
                    node = drill(record, path)
                except KeyError as exc:
                    items.append({"id": ident, "error": str(exc)})
                    continue
                rendered, complete = self._give(node, f"{name} 的 {ident}", path, start)
                size = len(dump(rendered))
                if used and used + size > COLLECT_CHARS:
                    items.append({"id": ident, "error": f"本次合计已到 {COLLECT_CHARS} 字，剩余编号请下次再取"})
                    continue
                used += size
                if complete:
                    self.delivered[dkey] = "*"
                items.append({"id": ident, **({"path": path} if path else {}), **({"offset": start} if start else {}), **rendered})
            return {"name": name, "records": items}
        try:
            node = drill(value, path)
        except KeyError as exc:
            return {"isError": True, "error": str(exc)}
        rendered, _ = self._give(node, f"{name} 的 {path or '整段'}", path, start)
        return {"name": name, **({"path": path} if path else {}), **({"offset": start} if start else {}), **rendered}

    def search(self, name: str, query: str) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {"isError": True, "error": "query 不能为空"}
        if name == ZONE_NAME:
            if self.zone is None or not self.zone.has_open:
                return {"isError": True, "error": f"当前没有开放的公共资源（能读的：{self._available_names()}）"}
            records = self.zone.iter_open_records()
            hits = [
                {"id": rec.get("id", ""), "path": at, "snippet": snippet}
                for rec in records for at, snippet in _hits(rec, "", query)
            ]
            return {
                "name": ZONE_NAME, "query": query, "hits": hits[:SEARCH_HITS], "total": len(hits),
                "hint": f"片段不算读过正文，用 {READ}(name={ZONE_NAME!r}, ids=[id], path=path) 取回再引用",
            }
        values = self.readable()
        if name not in values:
            return {"isError": True, "error": f"{name} 不在当前能读的材料里（能读的：{self._available_names()}）"}
        value = values[name]
        hits = [{"id": "", "path": at, "snippet": snippet} for at, snippet in _hits(value, "", query)]
        return {
            "name": name, "query": query, "hits": hits[:SEARCH_HITS], "total": len(hits),
            "hint": f"片段不算读过正文，用 {READ}(name={name!r}, path=path) 取回再引用",
        }

    def tools(self) -> list[VerifiableTool]:
        name = {"type": "string", "description": f"公共资源区填 {ZONE_NAME!r}，或普通材料标题（推送里【】中的原文）"}
        return [
            VerifiableTool(
                tool_id=READ, execute_fn=self.read,
                description=(f"按需读取公共资源区（name={ZONE_NAME!r}，传 ids）或超限普通材料正文（单次上限 {READ_CHARS} 字）。"
                             "结构超限时超长字段给开头预览，按预览提示的 path 下钻；单段纯文本超限时按提示传 offset 续读。"
                             "同一会话已给过的资源不必重读。"),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": name,
                        "ids": {"type": "array", "items": {"type": "string"}, "description": "要取的资源编号列表（可一次传多个）"},
                        "path": {"type": "string", "description": "内部字段路径，如 fields/output；不填取整条"},
                        "offset": {"type": "integer", "description": "单段超长文本续读的起始字符位置（默认 0）"},
                    },
                    "required": ["name"],
                },
            ),
            VerifiableTool(
                tool_id=SEARCH, execute_fn=self.search,
                description=(f"在公共资源区（name={ZONE_NAME!r}）或大材料里逐字段按关键词搜索（自动解开内层 JSON 文本），"
                             "返回命中的编号、字段位置 path 与片段；片段不算读过，要引用须先用 read_material 取回。"),
                parameters={"type": "object", "properties": {
                    "name": name, "query": {"type": "string", "description": "关键词"}},
                    "required": ["name", "query"]},
            ),
        ]
