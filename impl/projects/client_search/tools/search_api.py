"""客户端搜索 API 可执行验证 tool。

把"调业务搜索 API"封装成 VerifiableTool，attribute agent 可以按需调用，
拿到 actual 响应作为归因的证据。

核心理念：不是搬运静态信息，而是真调业务系统跑出 actual，用 actual 做证据。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from impl.tools import ToolResult, VerifiableTool


def build_search_api_tool(
    api_base: str,
    endpoint: str,
    method: str = "POST",
    timeout: float = 10.0,
) -> VerifiableTool:
    """创建"调搜索 API"可执行验证 tool。"""
    url = urljoin(str(api_base).rstrip("/") + "/", str(endpoint).lstrip("/"))
    tool_id = "client_search.search_api"

    def execute(**kwargs: Any) -> ToolResult:
        # agno 用 validate_call 包装函数，LLM 按 JSON schema 的 properties 传 kwargs
        # （如 query=..., user_id=...）。用 **kwargs 接收，避免 pydantic 校验
        # `params: Dict[str, Any]` 时 kwargs 对不上单个参数名。
        params = kwargs
        query = params.get("query") or params.get("user_text") or ""
        if not query:
            return ToolResult(
                tool_id=tool_id,
                status="inconclusive",
                evidence="no query provided; cannot execute search API call",
            )
        payload = {
            "user_text": query,
            "user_id": params.get("user_id") or "eval-verifier",
            "trace_id": params.get("trace_id") or f"verifier-tool-{int(time.time() * 1000)}",
            "session_id": params.get("session_id") or "verifier-tool-session",
            "source": params.get("source") or "askbob",
            "extra_input_params": params.get("extra_input_params") or {},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8")
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                result = {"raw_text": text}
            result_data = result.get("data") if isinstance(result, dict) else {}
            extra = result_data.get("extra_output_params") if isinstance(result_data, dict) else {}
            return ToolResult(
                tool_id=tool_id,
                status="succeeded",
                actual={
                    "code": result.get("code") if isinstance(result, dict) else None,
                    "query": extra.get("rewritten_query") or payload.get("user_text"),
                    "conditions": extra.get("conditions") or [],
                    "logic": extra.get("query_logic") or "AND",
                    "matched_level": extra.get("matched_level"),
                    "matched_patterns": extra.get("matched_patterns") or [],
                    "summary": extra.get("intent_summary") or "",
                },
                evidence=f"called {url} with query={query} in {timeout}s",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return ToolResult(
                tool_id=tool_id,
                status="failed",
                error=f"search API call failed: {exc}",
                evidence=f"called {url} with query={query}; error={exc}",
            )

    execute.__name__ = tool_id.replace(".", "_")
    execute.__doc__ = f"调业务搜索解析接口，传入自然语言查询，返回解析出的搜索条件、匹配级别、匹配模式。用于验证业务系统当前行为是否和 trace 记录一致。"
    return VerifiableTool(
        tool_id=tool_id,
        description="调业务搜索解析接口，传入自然语言查询，返回解析出的搜索条件、匹配级别、匹配模式。用于验证业务系统当前行为是否和 trace 记录一致。",
        applicable_scenario="attr",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言搜索查询，如'45岁女性保费10万以上'"},
                "user_id": {"type": "string", "description": "用户ID，默认 eval-verifier"},
            },
            "required": ["query"],
        },
        execute_fn=execute,
    )