"""大材料：推送只放目录，正文按需读（spec/alg/axis_loop.md §4.4、§9）。

做法沿用侦探现有的"先 outline 再读"（`dossier_collect` / `dossier_read` / `dossier_search`），推广成每个 loop 都有的内置工具：
- 序列化后超过上限的材料，推送时只放目录。值是 `{catalog, records: [{id, ...}]}` 形状的（记录库），目录就是 catalog；
  别的形状放开头预览与大小。
- `read_material(name, ids, path, full)`：按编号取记录；单条超过上限（与推送同一个上限 `loop_material_inline_chars`）时，
  从最长的正文段起换成预览（开头 + 字数 + 读全文的 path），小的部分照给全文；连结构都放不下才只给结构图（字段与大小），带 path 下钻，确需整段 full。
- `search_material(name, query)`：在记录里逐个字段按关键词找（值是 JSON 文本的先解开），返回命中的编号、字段位置与片段，再用 read_material 按编号 + 位置取。
- 按位置下钻遇到 JSON 文本先解开再走；走不通时报出这一层有哪些字段。
- 同一 loop 里已经给过的长段正文，在别的记录里再出现时只给指向（"同 X 里那段"），按大小判断前先去重：
  被测系统每次调模型的请求都带着完整的累积对话，不去重就一遍遍重读同样的系统提示词与工具返回。重读同一条记录照常给全文。
能读的范围由调用方给（本 loop 已出现任务的白名单条目，取值已按白名单投影、筛选），白名单没选的读不到。
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Callable, Optional, Sequence

from impl.tools.protocol import VerifiableTool

from .text import dump

READ, SEARCH = "read_material", "search_material"
PREVIEW_CHARS = 2_000
STUB_CHARS = 300           # 超限时长段只给开头这么多
FULL_CHARS = 60_000         # full=true 的上限
COLLECT_CHARS = 60_000      # 一次 read 合计上限
SEARCH_HITS = 12
REPEAT_CHARS = 300        # 这么长以上的正文段，同一 loop 里第二次出现只给指向
SNIPPET_CHARS = 240


def _records(items: Any) -> bool:
    return isinstance(items, list) and bool(items) and all(isinstance(r, Mapping) and "id" in r for r in items)


def as_store(value: Any) -> Optional[dict[str, Any]]:
    """认出记录库：{catalog?, records: [{id…}]}；按白名单投影后常成为一列带 id 的记录，或只含一个记录库的列表。"""
    if isinstance(value, list) and len(value) == 1 and not _records(value):
        value = value[0]
    if isinstance(value, Mapping) and _records(value.get("records")):
        return {"catalog": value.get("catalog") or [{"id": r["id"]} for r in value["records"]], "records": value["records"]}
    if _records(value):
        return {"catalog": [{"id": r["id"]} for r in value], "records": value}
    return None


def is_store(value: Any) -> bool:
    return as_store(value) is not None


def summarize(title: str, value: Any, limit: int) -> Any:
    """推送时放进上下文的那份：不超限原样；超限的记录库只放目录，其余放预览。"""
    text = dump(value)
    if value is None or len(text) <= limit:
        return value
    hint = f"正文太大（{len(text)} 字），这里只给目录；用 {READ}(name={title!r}, ids=[...]) 取记录，或 {SEARCH} 按关键词找"
    store = as_store(value)
    if store:
        # 只有记录正文换成目录；记录库旁的其他字段（例：案卷的环节表、可疑环节、缺口）照推，单个太大的给开头 + 读法
        side = {k: v if len(dump(v)) <= limit else
                {"说明": f"这一项太大（{len(dump(v))} 字），这里只给开头；用 {READ}(name={title!r}, path={k!r}) 读", "preview": dump(v)[:PREVIEW_CHARS]}
                for k, v in value.items() if k not in ("catalog", "records")} if isinstance(value, Mapping) else {}
        return {"说明": hint, "catalog": store["catalog"], **side, "records": len(store["records"])}
    return {"说明": f"正文太大（{len(text)} 字），这里只给开头；用 {READ}(name={title!r}, path=...) 按位置读",
            "preview": text[:PREVIEW_CHARS]}


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


def _fit(node: Any, limit: int, base: str) -> tuple[Any, set[str]]:
    """超限时从最长的正文段起换成预览（开头一段 + 字数 + 读全文的 path），直到放得下；小的部分照给全文。"""
    size, cut = len(dump(node)), set()
    for at, text in sorted(_leaves(node, ""), key=lambda x: -len(x[1])):
        if size <= limit or len(text) <= STUB_CHARS * 2:
            break
        full_path = "/".join(p for p in (base, at) if p)
        stub = f"〔预览，全文 {len(text)} 字；读全文：path={full_path!r}, full=true〕{text[:STUB_CHARS]}…"
        node, size, cut = _put(node, at, stub), size - len(dump(text)) + len(dump(stub)), cut | {text}
    return node, cut


def _render(node: Any, full: bool, limit: int, base: str = "") -> tuple[dict[str, Any], set[str]]:
    """→ (返回给模型的, 只给了预览的正文段)。"""
    text = dump(node)
    limit = FULL_CHARS if full else limit
    if len(text) <= limit:
        return {"content": node}, set()
    fitted, cut = _fit(node, limit, base)
    if len(dump(fitted)) <= limit:
        return {"content": fitted, "hint": f"这段 {len(text)} 字，超过单次上限 {limit} 字：长段只给了开头预览，要读全文按预览里写的 path 加 full=true 取"}, cut
    return {"shape": shape(node),
            "hint": f"这段 {len(text)} 字，超过单次上限 {limit} 字：带 path 往下取" + ("" if full else "，确需整段用 full=true")}, set()


class Reader:
    """一个 loop 实例的读工具；readable() 给出当前能读的 {标题: 值}。"""

    def __init__(self, readable: Callable[[], Mapping[str, Any]], limit: int) -> None:
        self.readable, self.limit = readable, limit
        self.given: dict[str, str] = {}   # 已给过的长段正文 → 在哪条记录里给的

    def _dedupe(self, node: Any, where: str, fresh: dict[str, str]) -> Any:
        """别的记录里已给过的长段换成指向；这次新出现的记进 fresh。"""
        if isinstance(node, str):
            first = self.given.get(node, where)
            if len(node) < REPEAT_CHARS or first == where:
                if len(node) >= REPEAT_CHARS:
                    fresh.setdefault(node, where)
                return node
            return f"〔同 {first} 里已给过的那段，{len(node)} 字〕"
        if isinstance(node, Mapping):
            return {k: self._dedupe(v, where, fresh) for k, v in node.items()}
        if isinstance(node, list):
            return [self._dedupe(v, where, fresh) for v in node]
        return node

    def _give(self, node: Any, full: bool, where: str, path: str) -> dict[str, Any]:
        fresh: dict[str, str] = {}
        rendered, cut = _render(self._dedupe(node, where, fresh), full, self.limit, path)
        if "content" in rendered:   # 只给了结构图、预览的没真给出去，不算给过
            for text, at in fresh.items():
                if text not in cut:
                    self.given.setdefault(text, at)
        return rendered

    def _value(self, name: str) -> tuple[Any, Optional[str]]:
        values = self.readable()
        if name not in values:
            return None, f"{name} 不在当前能读的材料里（能读的：{sorted(values)}）"
        return values[name], None

    def read(self, name: str, ids: Optional[Sequence[str]] = None, path: str = "", full: bool = False) -> dict[str, Any]:
        value, error = self._value(name)
        if error:
            return {"isError": True, "error": error}
        if value is None:
            return {"isError": True, "error": f"{name} 未启用或未出现"}
        if ids:
            store = as_store(value)
            if not store:
                return {"isError": True, "error": f"{name} 不是按编号存的记录，用 path 读"}
            by_id = {str(r["id"]): r for r in store["records"]}
            items, used = [], 0
            for ident in ids:
                record = by_id.get(str(ident))
                if record is None:
                    items.append({"id": ident, "error": "没有这个编号"})
                    continue
                try:
                    node = drill(record, path)
                except KeyError as exc:
                    items.append({"id": ident, "error": str(exc)})
                    continue
                rendered = self._give(node, full, f"{name} 的 {ident}", path)
                size = len(dump(rendered))
                if used and used + size > COLLECT_CHARS:
                    items.append({"id": ident, "error": f"本次合计已到 {COLLECT_CHARS} 字，下次再取"})
                    continue
                used += size
                items.append({"id": ident, **({"path": path} if path else {}), **rendered})
            return {"name": name, "records": items}
        try:
            node = drill(value, path)
        except KeyError as exc:
            return {"isError": True, "error": str(exc)}
        return {"name": name, **({"path": path} if path else {}), **self._give(node, full, f"{name} 的 {path or '整段'}", path)}

    def search(self, name: str, query: str) -> dict[str, Any]:
        value, error = self._value(name)
        if error:
            return {"isError": True, "error": error}
        query = str(query or "").strip()
        if not query:
            return {"isError": True, "error": "query 不能为空"}
        store = as_store(value)
        records = store["records"] if store else [{"id": "", "value": value}]
        hits = []
        for record in records:
            node = record if store else value
            for at, snippet in _hits(node, "", query):
                hits.append({"id": record.get("id", ""), "path": at, "snippet": snippet})
        return {"name": name, "query": query, "hits": hits[:SEARCH_HITS], "total": len(hits),
                "hint": f"片段不算读过正文，用 {READ}(name, ids=[id], path=path) 取回再引用" if store
                        else f"片段不算读过正文，用 {READ}(name, path=path) 取回再引用"}

    def tools(self) -> list[VerifiableTool]:
        name = {"type": "string", "description": "材料标题（推送里【】中的原文）"}
        return [
            VerifiableTool(tool_id=READ, execute_fn=self.read,
                           description="读大材料的正文：ids 按目录里的编号取记录；单条太大会给结构图，带 path（如 fields/content）往下取；确需整段 full=true。",
                           parameters={"type": "object", "properties": {
                               "name": name,
                               "ids": {"type": "array", "items": {"type": "string"}, "description": "要取的记录编号"},
                               "path": {"type": "string", "description": "记录内的位置，a/b/0 这样写；不填取整条"},
                               "full": {"type": "boolean", "description": "整段读取（上限更大）"}},
                               "required": ["name"]}),
            VerifiableTool(tool_id=SEARCH, execute_fn=self.search,
                           description="在大材料里按关键词找，逐个字段找（JSON 文本解开找），返回命中的记录编号、字段位置 path 与片段；片段不算读过，要引用先用 read_material 按编号 + path 取回。",
                           parameters={"type": "object", "properties": {
                               "name": name, "query": {"type": "string", "description": "关键词"}},
                               "required": ["name", "query"]}),
        ]
