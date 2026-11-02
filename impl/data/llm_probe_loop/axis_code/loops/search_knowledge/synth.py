"""取证案卷：每条引文补上判定要的上下文——查询用的工具与参数、引句所在的整条记录（window 同 llm_probe knowledge_loop）。"""
import json
from collections.abc import Mapping

from impl.core.axis_loop.text import leaves as _leaves

WINDOW_CHARS = 3000


def _compact(text):
    return "".join(text.split())


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _objects(value):
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


def window(text, quote, chars=WINDOW_CHARS):
    """包住引句、不超过 chars 的最大完整对象（整条记录）；没有就取引句前后约 chars 字。"""
    target = _compact(quote)
    leaves = _leaves(text)
    for leaf in leaves:
        if target not in _compact(leaf):
            continue
        fits = [t for t in map(_dump, _objects(leaf)) if target in _compact(t) and len(t) <= chars]
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


def synthesize(view):
    """唯一性原则：同一条整条记录、同一次调用的工具与参数只给一份；cite_records 按条给出每条引文的记录编号（与 citations 一一对应）。"""
    records, calls, cite_records, ids = {}, {}, {}, {}
    for item in view.own["items"]:
        keys = []
        for cite in item["citations"]:
            call = view.call(cite["ref"])
            calls.setdefault(cite["ref"], {"tool": call.tool, "args": dict(call.args)})
            text = window(call.text, cite["quote"])
            key = ids.setdefault((cite["ref"], text), f"r{len(ids) + 1}")
            records[key] = text
            keys.append(key)
        cite_records[item["item_id"]] = keys
    return {"records": records, "calls": calls, "cite_records": cite_records}
