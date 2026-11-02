"""引文比对与稳定序列化（spec/alg/axis_loop.md §4.4、§5）。

引文 = 逐字出现在某段原文里。比对时忽略空白与反斜杠：原文常是"JSON 里套 JSON 字符串"（MCP 返回），
模型看到的是转义后的 \"，摘的时候去掉了转义，转义符不是内容，不该让引句对不上；改字仍判不是原文。
结构化的值逐个字符串叶子比对。
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


def dump(value: Any) -> str:
    """放进上下文的稳定文本：同一份值每次序列化都一样，才能逐字引用。"""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _normalize(text: str) -> str:
    # 先把转义写法的换行、制表（两个字符 \n、\t、\r）当空白去掉，再去空白与反斜杠。
    return re.sub(r"[\s\\]+", "", re.sub(r"\\+[ntr]", " ", str(text or "")))


def quote_in_text(quote: str, text: str) -> bool:
    target = _normalize(quote)
    return bool(target) and target in _normalize(text)


def leaves(value: Any) -> list[str]:
    """值里的全部字符串叶子；字符串本身是 JSON 时也解出来比（MCP 返回常见）。"""
    if isinstance(value, str):
        out = [value]
        if value[:1] in "[{":
            try:
                out.extend(leaves(json.loads(value)))
            except ValueError:
                pass
        return out
    if isinstance(value, Mapping):
        return [leaf for item in value.values() for leaf in leaves(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in leaves(item)]
    return []


def quote_in_value(quote: str, value: Any) -> bool:
    return any(quote_in_text(quote, leaf) for leaf in leaves(value))
