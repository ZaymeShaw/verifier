"""证据就是本次 loop 里模型实际看到的工具返回。

不另建台账：ToolLoop 的 History.calls 已记下每次调用的参数、返回与批次，pre_tool 只看得到此前批次——
正是"同批拿到的不能当场引用"。这里只做三件事：给知识源调用的返回盖上 call_id、按 call_id 找回调用、逐字核对引句。
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional

from impl.core.tool_loop import Call, History, Hook
from impl.projects.llm_probe.material_tools import quote_in_text


def call_id(call: Call) -> str:
    return f"c{call.id}"


class StampCallId(Hook):
    """post_tool：知识源工具的返回加上 call_id，模型据此引用。"""

    def __init__(self, tools: Iterable[str]) -> None:
        self.tools = set(tools)

    def post_tool(self, history: History, call: Call) -> Any:
        if call.tool in self.tools and isinstance(call.result, Mapping):
            # 盖在最后：工具自己的返回里若也有 call_id 之类的键，不能把证据编号覆盖掉。
            return {**call.result, "call_id": call_id(call)}
        return call.result


def failed(call: Call) -> str:
    """调用失败的原因；工具以 {'error': …} 报错（ES/MCP/资料工具都这样）也算失败。"""
    if not call.ok:
        return call.error or call.denied
    if isinstance(call.result, Mapping) and call.result.get("error"):
        return str(call.result["error"])
    return ""


def find(history: History, ref: str, tools: set[str]) -> Optional[Call]:
    """此前批次里、属于知识源工具的那次调用。"""
    for call in history.calls:
        if call.tool in tools and call_id(call) == ref:
            return call
    return None


def _leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        # 返回体本身可能是 JSON 字符串（MCP 常见）：原文里的换行转义成了 \n，也比对解出来的字段。
        out = [value]
        if value[:1] in "[{":
            try:
                out.extend(_leaves(json.loads(value)))
            except ValueError:
                pass
        return out
    if isinstance(value, Mapping):
        return [leaf for key, item in value.items() if key != "call_id" for leaf in _leaves(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item)]
    return []


def quote_ok(call: Call, quote: str) -> bool:
    return any(quote_in_text(quote, leaf) for leaf in _leaves(call.result))


def _compact(text: str) -> str:
    return "".join(text.split())


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _objects(value: Any):
    """JSON 里所有对象（含嵌在字符串里的 JSON），由内到外都给。"""
    if isinstance(value, str) and value[:1] in "[{":
        try:
            value = json.loads(value)
        except ValueError:
            return
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)


def window(call: Call, quote: str, chars: int = 3000, full_text: Optional[str] = None) -> str:
    """引句的上下文，给下游判定看（归属、条件、例外常在引句旁边）。

    结构化返回给包住引句、不超过 chars 的最大完整对象（整条记录），不把记录从中间切断；
    同一引句出现在几条记录里时都给（最多 3 条），由判定按归属取舍。
    full_text 是这次调用的完整返回（MCP 分页时模型只看到一页，记录要在整份返回里找）；引句核对仍只认模型看到的。
    对象超过 chars 或返回是纯文本时，取引句前后共约 chars 字。"""
    target = _compact(quote)
    if not target:
        return ""
    leaves = ([full_text] if full_text else []) + _leaves(call.result)
    for leaf in leaves:
        if target not in _compact(leaf):
            continue
        fits = [text for text in map(_dump, _objects(leaf)) if target in _compact(text) and len(text) <= chars]
        top = [t for t in fits if not any(t != o and t in o for o in fits)]
        if top:
            return "\n……\n".join(sorted(set(top), key=top.index)[:3])
    for leaf in leaves:
        compact, index = [], []
        for i, ch in enumerate(leaf):
            if not ch.isspace():
                compact.append(ch)
                index.append(i)
        at = "".join(compact).find(target)
        if at >= 0:
            start, end = index[at], index[at + len(target) - 1] + 1
            pad = max(0, (chars - (end - start)) // 2)
            return leaf[max(0, start - pad):end + pad]
    return ""
