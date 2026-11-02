"""MCP 知识源：把业务系统以 MCP 暴露的查询工具原样交给评测模型，返回原文进回执供引用回读。

- 连接用 fastmcp Client + stdio（与 .mcp.json 的 command/args/env 同形），每次调用拉起一次、用完即关：
  不持有跨调用的会话，评测侧没有生命周期要管；拉起约 1 秒，相对模型一轮可忽略。
- 只暴露登记里 tools 白名单列出的工具（评测只读）；工具名、说明、入参 schema 全部取自 MCP 的 tools/list，不二次推导；对模型暴露为 ``<知识源名>__<工具名>``（非字母数字一律换成 _，工具名协议只收这些字符）。
- 每次调用产生一个翻页句柄（``mcp://<知识源>#<序号>``），完整返回原文存进回执；模型看到的是截断视图，
  用 mcp_read 按偏移翻页。证据与引用核对在知识查证 loop 里统一做（knowledge_loop/evidence.py）：只认模型实际看到的返回。
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from impl.tools.protocol import VerifiableTool, build_agno_tools
from .registry import McpSource, load_mcp_source

_TOOL_NAME = re.compile(r"[^A-Za-z0-9_]")
_TOOL_SPECS: dict[McpSource, list[dict[str, Any]]] = {}


def _run(coro_factory, timeout: float):
    # 调用方可能已在事件循环里（服务端线程）：一律在独立线程里起新循环，不碰调用方的循环。
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(asyncio.wait_for(coro_factory(), timeout))).result()


def _client(source: McpSource):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    return Client(StdioTransport(command=source.command, args=list(source.args), env=dict(source.env)))


def tool_prefix(name: str) -> str:
    return _TOOL_NAME.sub("_", name) + "__"


def list_tools(source: McpSource) -> list[dict[str, Any]]:
    if source not in _TOOL_SPECS:
        async def fetch():
            async with _client(source) as client:
                return [{"name": t.name, "description": t.description or "", "schema": t.inputSchema or {"type": "object", "properties": {}}}
                        for t in await client.list_tools()]
        _TOOL_SPECS[source] = _run(fetch, source.timeout_seconds)
    return _TOOL_SPECS[source]


def call_tool(source: McpSource, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    async def call():
        async with _client(source) as client:
            # 原始结果：isError 要自己看，fastmcp 默认会把它抛成异常、丢掉返回正文。
            return await client.call_tool(name, arguments, _return_raw_result=True)
    result = _run(call, source.timeout_seconds)
    text = "\n".join(getattr(item, "text", "") or json.dumps(getattr(item, "model_dump", lambda: {})(), ensure_ascii=False)
                     for item in result.content)
    return text, bool(result.isError)


def recorded_response(receipts, page_id: str) -> str | None:
    for receipt in receipts:
        if receipt.get("page_id") == page_id and "response_text" in receipt:
            return receipt["response_text"]
    return None


def _described(schema: dict[str, Any]) -> dict[str, Any]:
    """工具协议要求每个入参有说明；MCP 服务没写的补一句中性占位，不要求业务方为评测改 schema。"""
    properties = {name: (prop if not isinstance(prop, dict) or str(prop.get("description") or "").strip()
                         else {**prop, "description": f"{name}（MCP 服务未提供说明）"})
                  for name, prop in (schema.get("properties") or {}).items()}
    return {**schema, "properties": properties}


_REQUEST_FIELD = re.compile(r"\{request\.([A-Za-z0-9_]+)\}")


def bind_request(source: McpSource, request) -> McpSource:
    """登记 env 里的 {request.<字段>} 取自本样本的请求体（如工号）：业务按谁的身份答，评测就按谁的身份查。
    样本里没有该字段就报错，不换成别的身份去查。"""
    def value(text: str) -> str:
        def replace(match):
            key = match.group(1)
            got = (request or {}).get(key)
            if not isinstance(got, (str, int)) or str(got) == "":
                raise ValueError(f"MCP 知识源 {source.name} 需要样本请求里的身份字段 {key}，本样本没有")
            return str(got)
        return _REQUEST_FIELD.sub(replace, text)
    return dataclasses.replace(source, env=tuple((k, value(v)) for k, v in source.env))


_FIND_CONTEXT = 400  # 命中处前后各带多少字原文

class McpTools:
    def __init__(self, catalog, recorder, request=None):
        self.sources = {item["uri"][len("mcp://"):]: bind_request(load_mcp_source(item["uri"][len("mcp://"):]), request)
                        for item in catalog if item.get("source") == "mcp"}
        self.recorder = recorder

    def _call(self, source: McpSource, tool: str, arguments: dict[str, Any]):
        page_id = f"mcp://{source.name}#{sum(r.get('tool', '').startswith('mcp') for r in self.recorder) + 1}"
        receipt: dict[str, Any] = {"tool": "mcp_call", "source": source.name, "mcp_tool": tool, "arguments": arguments,
                                   "page_id": page_id, "returned_locators": []}
        try:
            text, is_error = call_tool(source, tool, arguments)
            receipt["response_text"] = text
            receipt["returned_locators"] = [page_id]
            if is_error:
                receipt["error"] = f"MCP 工具 {tool} 返回错误：{text[:300]}"
                return {"error": receipt["error"]}
            limit = source.max_chars
            return {"page_id": page_id, "text": text[:limit], "truncated": len(text) > limit, "total_chars": len(text)}
        except Exception as exc:  # 进程拉不起、超时、协议错误：都如实记成工具失败，不能伪装成"查不到"
            receipt["error"] = f"MCP 调用失败（{type(exc).__name__}）：{str(exc)[:300]}"
            return {"error": receipt["error"]}
        finally:
            self.recorder.append(receipt)

    def _response(self, page_id: str) -> str | None:
        return recorded_response(self.recorder, page_id)

    def mcp_read(self, page_id: str, start: int = 0):
        receipt: dict[str, Any] = {"tool": "mcp_read", "page_id": page_id, "start": start, "returned_locators": []}
        try:
            text = self._response(page_id)
            if text is None:
                raise ValueError("page_id 必须是本轮 MCP 调用返回的 page_id")
            source = self.sources[page_id[len("mcp://"):].split("#", 1)[0]]
            start = max(0, int(start))
            receipt["returned_locators"] = [page_id]
            end = start + source.max_chars
            return {"page_id": page_id, "start": start, "text": text[start:end], "truncated": end < len(text), "total_chars": len(text)}
        except (ValueError, KeyError) as exc:
            receipt["error"] = str(exc)
            return {"error": str(exc)}
        finally:
            self.recorder.append(receipt)

    def mcp_find(self, page_id: str, keyword: str):
        """在本轮某次 MCP 调用的完整返回里搜关键词，交回命中处前后的原文（返回很长、翻页找不现实时用）。"""
        receipt: dict[str, Any] = {"tool": "mcp_find", "page_id": page_id, "keyword": keyword, "returned_locators": []}
        try:
            text = self._response(page_id)
            if text is None:
                raise ValueError("page_id 必须是本轮 MCP 调用返回的 page_id")
            if not isinstance(keyword, str) or not keyword.strip():
                raise ValueError("keyword 不能为空")
            source = self.sources[page_id[len("mcp://"):].split("#", 1)[0]]
            receipt["returned_locators"] = [page_id]
            spans, at = [], text.find(keyword)
            while at >= 0:
                start, end = max(0, at - _FIND_CONTEXT), min(len(text), at + len(keyword) + _FIND_CONTEXT)
                if spans and start <= spans[-1][1]:
                    spans[-1][1] = end
                else:
                    spans.append([start, end])
                at = text.find(keyword, at + len(keyword))
            hits, used = [], 0
            for start, end in spans:
                if used + end - start > source.max_chars:
                    break
                hits.append({"start": start, "text": text[start:end]})
                used += end - start
            return {"page_id": page_id, "keyword": keyword, "matches": text.count(keyword), "hits": hits,
                    "truncated": len(hits) < len(spans), "total_chars": len(text)}
        except (ValueError, KeyError) as exc:
            receipt["error"] = str(exc)
            return {"error": str(exc)}
        finally:
            self.recorder.append(receipt)

    def tools(self):
        specs = []
        for source in self.sources.values():
            offered = {spec["name"]: spec for spec in list_tools(source)}
            absent = [name for name in source.tools if name not in offered]
            if absent:
                raise ValueError(f"MCP 知识源 {source.name} 登记的工具 {absent} 不在服务提供的工具里：{sorted(offered)}")
            for spec in (offered[name] for name in source.tools):
                def execute(_source=source, _tool=spec["name"], **arguments):
                    return self._call(_source, _tool, arguments)
                specs.append(VerifiableTool(
                    tool_id=tool_prefix(source.name) + _TOOL_NAME.sub("_", spec["name"]),
                    description=f"[MCP 知识源 {source.name}] " + spec["description"]
                                + "\n返回原文（可能截断：带 page_id，用 mcp_read 翻页，或用 mcp_find 在全文里搜关键词）。",
                    execute_fn=execute, parameters=_described(spec["schema"])))
        if specs:
            specs.append(VerifiableTool(
                tool_id="mcp_read", description="按偏移翻看本轮某次 MCP 调用的完整返回原文（page_id 取自那次调用的返回）。", execute_fn=self.mcp_read,
                parameters={"type": "object", "properties": {
                    "page_id": {"type": "string", "description": "MCP 调用返回的 page_id"},
                    "start": {"type": "integer", "description": "起始字符偏移，缺省 0"}}, "required": ["page_id"]}))
            specs.append(VerifiableTool(
                tool_id="mcp_find", description="在本轮某次 MCP 调用的完整返回原文里搜关键词（字段名、中文名、数值等，原样匹配），"
                                                "交回每处命中前后的原文和偏移；返回很长时用它找，不必逐页翻。", execute_fn=self.mcp_find,
                parameters={"type": "object", "properties": {
                    "page_id": {"type": "string", "description": "MCP 调用返回的 page_id"},
                    "keyword": {"type": "string", "description": "要搜的关键词，原样匹配"}}, "required": ["page_id", "keyword"]}))
        return build_agno_tools(specs)


def build_mcp_tools(catalog, recorder, request=None):
    return McpTools(catalog, recorder, request).tools() if any(item.get("source") == "mcp" for item in catalog) else []
