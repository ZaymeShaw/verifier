"""记录集（spec/alg/resources.md §3）：按数据长相定义的类型，与数据从哪个信息源来无关。

长相：一条记录 = 一个 JSON 对象，``fields`` 下是字段（``{名字: {status, value, …}}``），其余键是记录属性。
trace 信息源（langfuse、agno）建成案卷后的记录都是这个长相。

两种资源：
- 直接资源：一条记录，挂载时登记，地址由提供它的组织方式定（如 ``trace://turn1/records/observations/14``）。
- 模板资源：``<记录地址>/fields/<字段名>``，读时从这条记录的规范文本里切出该字段那一段（一字不差）。

只报结构位置（整块 / 记录属性 / 哪个字段）；字段是不是某个环节的输入端、输出端由使用方判（resources.md §10.5）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mcp.types import ResourceTemplate, TextResourceContents

from ..spec import Block, pointer_join, pointer_tokens
from ..text import Span, find_all, render, smallest

FIELDS = "fields"
_FIELD_URI = re.compile(rf"^(?P<record>.+)/{FIELDS}/(?P<field>[^/]+)$")   # 记录编号本身带 /，以最后一个 /fields/ 为界


@dataclass(frozen=True)
class Hit:
    start: int
    end: int
    node: Span  # 包含命中的最小节点


@dataclass(frozen=True, order=True)
class Place:
    part: str                   # block 整块 / attribute 记录属性 / field 字段
    field: str = ""             # part=field 时的字段名；"" = 整个 fields


class RecordSet:
    name = "record_set"
    mime_type = "application/json"

    def text(self, body: Any) -> str:
        return render(body)[0]

    def templates(self, scheme: str) -> list[ResourceTemplate]:
        return [ResourceTemplate(
            uriTemplate=f"{scheme}://{{+record}}/{FIELDS}/{{field}}", name="record-field", title="记录的一个字段",
            description="某条记录 fields 下一个字段的内容；文本就是这条记录规范文本里该字段的那一段", mimeType=self.mime_type)]

    def resolve(self, uri: str) -> tuple[str, str] | None:
        """模板地址 → (记录地址, 记录正文里的节点)；不是本类型的模板地址返回 None。"""
        m = _FIELD_URI.match(uri)
        return (m["record"], pointer_join(f"/{FIELDS}", m["field"])) if m else None

    def read(self, block: Block, node: str = "", uri: str = "") -> TextResourceContents:
        """``node`` 为空读整条记录；否则读模板资源 ``uri``（该节点在整条记录规范文本里的原样）。"""
        text = self.text(block.body) if not node else self.slice(block.body, node)
        if text is None:
            raise LookupError(f"资源不存在：{uri}")
        return TextResourceContents(uri=uri or block.uri, mimeType=self.mime_type, text=text)

    def slice(self, body: Any, node: str) -> str | None:
        """一个节点在这份正文规范文本里的那一段；没有这个节点返回 None。"""
        text, spans = render(body)
        span = _value_span(spans, node)
        return None if span is None else text[span.start:span.end]

    def locate(self, block: Block, quote: str, node: str = "") -> list[Hit] | None:
        """在资源的规范文本里找摘句：``node`` 为空是整条记录，否则只在该节点里；没有该节点返回 None。"""
        text, spans = render(block.body)
        lo, hi = 0, len(text)
        if node:
            span = _value_span(spans, node)
            if span is None:
                return None
            lo, hi = span.start, span.end
        return [Hit(start, end, smallest(spans, start, end)) for start, end in find_all(quote, text)
                if lo <= start and end <= hi]

    def extract(self, block: Block, start: int, end: int) -> str:
        return self.text(block.body)[start:end]

    def place(self, block: Block, node: str) -> Place:
        tokens = pointer_tokens(node)
        if not tokens:
            return Place("block")
        if tokens[0] != FIELDS:
            return Place("attribute")
        return Place("field", tokens[1] if len(tokens) > 1 else "")

    def field_name(self, node: str) -> str:
        """模板节点 ``/fields/<名>`` → 字段名；整块或其他节点返回空串。"""
        tokens = pointer_tokens(node)
        return tokens[1] if len(tokens) == 2 and tokens[0] == FIELDS else ""

    def catalog_entry(self, block: Block, fields: set[str] | frozenset[str] | None = None) -> dict[str, Any]:
        """公共资源区的目录项：复用 MCP 描述符标签 + 当前已开放字段与字符数。"""
        body = block.body if isinstance(block.body, dict) else {}
        raw_fields = body.get(FIELDS) if isinstance(body.get(FIELDS), dict) else {}
        chosen = sorted(raw_fields if fields is None else (set(fields) & set(raw_fields)))
        chars = sum(int(raw_fields[n].get("chars") or len(render(raw_fields[n].get("value"))[0]))
                    for n in chosen if isinstance(raw_fields.get(n), dict) and "value" in raw_fields[n])
        entry: dict[str, Any] = {"id": block.descriptor.name, "uri": block.uri}
        if body.get("turn") is not None:
            entry["turn"] = body["turn"]
        if block.descriptor.title:
            entry["title"] = block.descriptor.title
        if block.descriptor.description:
            entry["description"] = block.descriptor.description
        if body.get("parent_ref"):
            entry["parent_ref"] = body["parent_ref"]
        if body.get("scope") == "history":
            entry["scope"] = "history"
        entry["fields"] = chosen
        entry["chars"] = chars
        return entry

    def present(self, block: Block, fields: set[str] | frozenset[str] | None = None) -> dict[str, Any]:
        """公共资源区内联或按需读取的记录视图：``fields=None`` 为整块直接资源，否则仅暴露指定模板字段。"""
        body = block.body if isinstance(block.body, dict) else {}
        raw_fields = body.get(FIELDS) if isinstance(body.get(FIELDS), dict) else {}
        names = set(raw_fields) if fields is None else (set(fields) & set(raw_fields))
        src_fields = ((block.meta("source") or {}).get("fields") or {}) if isinstance(block.meta("source"), dict) else {}
        seen_src: dict[str, str] = {}
        same: dict[str, str] = {}
        for name in sorted(names, key=lambda n: (n != "exact_request", n)):
            src = src_fields.get(name)
            if src and src in seen_src:
                same[name] = seen_src[src]
            elif src:
                seen_src[src] = name
        carried: dict[str, list[str]] = {}
        for name in names - set(same):
            src = src_fields.get(name)
            if src:
                sub = [cs[len(src) + 1:] for cs, cn in seen_src.items() if cn != name and cs.startswith(src + "/")]
                if sub:
                    carried[name] = sub
        if "exact_request" in (names - set(same)) and "raw_attributes" in (names - set(same)):
            carried.setdefault("raw_attributes", []).append("llm.tools")
        out_fields: dict[str, Any] = {}
        sibling_texts: dict[str, str] = {}
        for name in names - set(same):
            info = raw_fields.get(name)
            if isinstance(info, dict) and "value" in info:
                sibling_texts[name] = render(info["value"])[0]
        for name in sorted(names):
            info = raw_fields.get(name)
            if not isinstance(info, dict):
                out_fields[name] = info
                continue
            if name in same:
                out_fields[name] = {"status": info.get("status"), "same_as": same[name]}
                continue
            item = {k: v for k, v in info.items() if k != "ref"}
            val = item.get("value")
            if name in carried and isinstance(val, dict):
                prefixes = tuple(carried[name])
                others = [t for k, t in sibling_texts.items() if k != name]
                dropped = sorted(k for k in val if any(k == p or k.startswith(p + ".") for p in prefixes)
                                 or (isinstance(val[k], str) and len(val[k]) >= 80 and any(val[k] in t for t in others)))
                if dropped:
                    item["value"] = {k: v for k, v in val.items() if k not in dropped}
                    item["omitted_keys_delivered_elsewhere"] = dropped
            out_fields[name] = item
        head = {k: v for k, v in body.items() if k not in (FIELDS, "ref")}
        head["id"] = block.descriptor.name
        head[FIELDS] = out_fields
        return head


def _value_span(spans: list[Span], node: str) -> Span | None:
    return next((s for s in spans if s.pointer == node and not s.member), None)

