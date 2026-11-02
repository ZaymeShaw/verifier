"""axis loop 的信息源（spec/alg/axis_loop.md §5.1、§7.3、§8）：场景选用的知识源 → 一组固定工具 + 每次调用的实例。

场景怎么选用：沿用现有写法，在轴框描述里写 {es://名/索引}、{mcp://名}、{material://项目/资料}。
一个轴框里引用的就是这个轴挑的实例；整个场景选用的是各轴框引用的并集。外部的（ES、MCP）都经 MCP 访问；
资料（material://）是评测器自己存的，内置读取。
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from impl.core.tool_loop import Call
from impl.tools.protocol import VerifiableTool

from . import expand_sources, es_mcp_source, knowledge_tools
from .mcp_tools import call_tool, catalog_sources, tool_prefix
from .registry import load_registry
from impl.core.capability_store import validate_es_refs, validate_mcp_refs

KNOWLEDGE = "knowledge"
# 一条登记拿来做什么由它的类型决定（spec/alg/axis_loop.md §8）：知识源登记的 es / mcp，以及评测器自己的资料库，都是知识类。
TYPE_CATEGORY = {"es": KNOWLEDGE, "mcp": KNOWLEDGE}
MATERIAL_CATEGORY = KNOWLEDGE


def _catalog(note: str) -> list[dict[str, Any]]:
    return expand_sources(note or "", material_catalog=True)[1] if note else []


def selected_categories(notes: Iterable[str]) -> set[str]:
    """场景选了哪几类信息源：解析引用、找到登记、看登记的类型（不搜描述文字，不连信息源）。"""
    registry = load_registry()
    out: set[str] = set()
    for note in notes:
        for ref in validate_es_refs(note or ""):
            out.add(TYPE_CATEGORY[registry[ref.split("/", 1)[0]]["type"]])
        for name in validate_mcp_refs(note or ""):
            out.add(TYPE_CATEGORY[registry[name]["type"]])
        if "{material://" in (note or ""):
            out.add(MATERIAL_CATEGORY)
    return out


def union_catalog(notes: Iterable[str]) -> tuple[list[dict[str, Any]], list[Any]]:
    """各轴框引用的知识源并集，以及 ES 索引的字段骨架（经 ES 的 MCP server 取，和查证首条消息给的一样）。"""
    seen: dict[str, dict[str, Any]] = {}
    for note in notes:
        for item in _catalog(note):
            seen.setdefault(item["uri"], item)
    catalog = list(seen.values())
    indices: dict[str, list[str]] = {}
    for item in catalog:
        if item.get("source") == "es":
            name, index = item["uri"][len("es://"):].split("/", 1)
            indices.setdefault(name, []).append(index)
    outline = []
    for name, idx in indices.items():
        source = es_mcp_source(name, idx)
        for index in idx:
            text, is_error = call_tool(source, "es_outline", {"index": f"{name}/{index}"})
            if is_error:
                raise ValueError(f"知识源 outline 失败：{text[:300]}")
            outline.append(json.loads(text))
            seen[f"es://{name}/{index}"]["doc_count"] = outline[-1].get("doc_count")
    return catalog, outline


class ProbeSources:
    """实现 impl.core.axis_loop.loop.Sources。实例用目录里的 uri 标识（es://名/索引、mcp://名、material://项目/资料）。"""

    def __init__(self, notes: Mapping[str, str], request: Any = None) -> None:
        self.by_axis = {axis: [c["uri"] for c in _catalog(note)] for axis, note in notes.items()}
        seen: dict[str, dict[str, Any]] = {}
        for note in notes.values():
            for item in _catalog(note):
                seen.setdefault(item["uri"], item)
        self.catalog = list(seen.values())
        self.receipts: list[dict[str, Any]] = []
        self.tools: list[VerifiableTool] = knowledge_tools(self.catalog, self.receipts, request) if self.catalog else []
        self._mcp_names = {c["uri"][len("mcp://"):]: c["uri"] for c in self.catalog if c.get("source") == "mcp"}
        self._es_names = {c["uri"][len("es://"):].split("/", 1)[0] for c in self.catalog if c.get("source") == "es"}
        self._sources = catalog_sources(self.catalog, request) if self._mcp_names else {}

    def check(self, instance: str) -> str:
        """登记了检查工具的 MCP 实例：调一次，报错就返回说明（框架据此记运行失败）；没登记就不查。"""
        name = instance[len("mcp://"):] if instance.startswith("mcp://") else ""
        source = self._sources.get(name)
        if source is None or not source.check_tool:
            return ""
        try:
            text, is_error = call_tool(source, source.check_tool, {})
        except Exception as exc:
            return f"{instance} 检查工具 {source.check_tool} 调用失败（{type(exc).__name__}）：{str(exc)[:300]}"
        return f"{instance} 检查工具 {source.check_tool} 报错：{text[:300]}" if is_error else ""

    def axis_instances(self) -> dict[str, list[str]]:
        """场景里各轴框挑的实例（AxisLoop 的 axis_sources）；框里没引用的轴不限制。"""
        return {axis: uris for axis, uris in self.by_axis.items() if uris}

    def route(self, call: Call) -> tuple[str, str]:
        args = call.args
        if call.tool.startswith("material_") and "material_id" in args:
            uri = next((c["uri"] for c in self.catalog if str(c.get("id")) == str(args["material_id"])), "")
            return (KNOWLEDGE, uri)
        if call.tool in ("mcp_read", "mcp_find"):
            page = str(args.get("page_id") or "")
            origin = next((r for r in self.receipts if r.get("page_id") == page and r.get("tool") == "mcp_call"), None)
            return (KNOWLEDGE, self._uri(origin["source"], origin.get("arguments") or {}) if origin else "")
        for name in [*self._mcp_names, *self._es_names]:
            if call.tool.startswith(tool_prefix(name)):
                return (KNOWLEDGE, self._uri(name, args))
        return ("", "")

    def _uri(self, name: str, args: Mapping[str, Any]) -> str:
        if name in self._es_names:
            return "es://" + str(args.get("index") or "")
        return self._mcp_names.get(name, "")

    def instances(self, category: str) -> list[str]:
        return [c["uri"] for c in self.catalog] if category == KNOWLEDGE else []

    def describe(self, category: str, instances: list[str]) -> str:
        keep = ("uri", "title", "description", "notes", "doc_count")
        listing = [{k: c.get(k) for k in keep if c.get(k)} for c in self.catalog if c["uri"] in instances]
        hints = []
        for item in self.catalog:
            if item["uri"] not in instances:
                continue
            if item.get("source") == "es":
                name, _ = item["uri"][len("es://"):].split("/", 1)
                hints.append(f"{item['uri']}：用 {tool_prefix(name)}es_* 工具，index 参数填 {item['uri'][len('es://'):]}")
            elif item.get("source") == "mcp":
                hints.append(f"{item['uri']}：用 {tool_prefix(item['uri'][len('mcp://'):])}* 工具")
            else:
                hints.append(f"{item['uri']}：用 material_* 工具，material_id 填 {item.get('id')}")
        return ("知识源（只读）：" + json.dumps(listing, ensure_ascii=False) + "\n" + "\n".join(hints)
                + "\n返回很长时带 page_id：用 mcp_read 翻页、mcp_find 在全文里搜。")
