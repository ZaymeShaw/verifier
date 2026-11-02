"""被测系统调用失败：返回命中场景预先维护的错误码，这条 case 记运行失败、不出结论（demand/main_axis.md §3.6）。

错误码在场景配置 business_failure 里维护：http_status（状态码列表）、body（响应体里某个字段的错误码取值）。
没命中的返回——包括没登记的非 2xx——照常进 axis loop。没配就不判失败。这段判断只在这一处，不进任何轴。
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from impl.core.live_protocol import business_call_failure

_HTTP = re.compile(r"^HTTP (\d{3}):?\s*(.*)$", re.S)


def _status_and_body(trace: Any) -> tuple[int | None, Any]:
    failure = business_call_failure(trace)  # 非 2xx：live 记的是 "HTTP <码>: <响应体 JSON>"
    if failure:
        match = _HTTP.match(failure)
        if match:
            try:
                return int(match.group(1)), json.loads(match.group(2)) if match.group(2) else None
            except ValueError:
                return int(match.group(1)), match.group(2)
        return None, failure
    text = (trace.extracted_output or {}).get("output_text") if isinstance(trace.extracted_output, Mapping) else None
    try:
        return 200, json.loads(text) if isinstance(text, str) else text
    except ValueError:
        return 200, text


def _pointer(value: Any, pointer: str) -> Any:
    for part in pointer.lstrip("/").split("/") if pointer.strip("/") else []:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, Mapping):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def matched(trace: Any, scenario: Mapping[str, Any]) -> str:
    """命中返回原因（写进运行失败），否则空串。"""
    rule = scenario.get("business_failure") or {}
    if not rule:
        return ""
    status, body = _status_and_body(trace)
    if status is not None and status in (rule.get("http_status") or []):
        return f"被测系统返回 HTTP {status}（场景登记的调用失败状态码）"
    spec = rule.get("body")
    if spec:
        got = _pointer(body, spec["pointer"])
        if got is not None and str(got) in spec["values"]:
            return f"被测系统返回错误码 {spec['pointer']}={got}（场景登记的调用失败错误码）"
    return ""
