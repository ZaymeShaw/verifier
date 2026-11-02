"""llm_probe_loop 的业务 Trace 接入点（spec/alg/axis_loop.md §8.2）。

外部的事归信息源，case 里的事归框架：
- 连接配置在全局登记（knowledge_sources.json，type=agno / langfuse），场景只写 `{source: 登记名, bindings: {...}}`；
- 跑完业务时经 trace 源的本地 MCP server（mcp_servers/trace）采集，快照原样存进运行记录；
- 评测时只读存档（内置材料 case.trace），不连 trace 平台。
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any

from .providers import agno, langfuse

_PROVIDERS = {"agno": agno, "langfuse": langfuse}
_ENV_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
COLLECT_SECONDS = 600


def provider_descriptions() -> list[dict[str, Any]]:
    return [module.describe() for module in _PROVIDERS.values()]


def validate_selection(value: Any) -> dict[str, Any]:
    """场景的 trace 选用：登记存在、类型对，登记的连接 + 场景的绑定能过 provider 的配置校验。返回合并后的 provider 配置。"""
    from impl.projects.llm_probe_loop.eval_axes.sources.registry import load_trace_source

    if not isinstance(value, Mapping) or not value.get("source") or not isinstance(value.get("bindings"), Mapping):
        raise ValueError("business_trace 写成 {source: trace 源登记名, bindings: {...}}")
    registered = load_trace_source(str(value["source"]))
    return {"type": registered.type,
            "config": _PROVIDERS[registered.type].validate_config({**registered.config, "bindings": dict(value["bindings"])})}


def check_connection(value: Any) -> dict[str, Any]:
    """场景页"测试 Trace 连接"：选用写得对（登记存在、绑定合法），再经 trace 源的 MCP 服务连一次平台。"""
    validate_selection(value)
    return check_source(str(value["source"]))


def check_source(name: str) -> dict[str, Any]:
    """经 trace 源的 MCP 服务 `check` 连一次平台；连不上如实报错。"""
    from impl.projects.llm_probe_loop.eval_axes.sources.mcp_tools import call_tool

    text, is_error = call_tool(trace_mcp_source(name), "check", {})
    if is_error:
        raise ValueError(f"trace 源 {name} 连接失败：{text[:500]}")
    return json.loads(text)


def trace_mcp_source(name: str):
    """trace 源的本地 MCP server：登记里 ${VAR} 引用的凭据从本进程环境传下去（子进程不继承父进程环境）。"""
    from impl.core.config import ROOT
    from impl.core.config_bootstrap import effective_environment_snapshot
    from impl.core.instances import INSTANCE_ENV
    from impl.projects.llm_probe_loop.eval_axes.sources.registry import McpSource, load_trace_source

    registered = load_trace_source(name)
    snapshot = effective_environment_snapshot(ROOT / ".env")
    env = {"PYTHONPATH": str(ROOT), "NO_PROXY": "*", "no_proxy": "*"}
    for var in _ENV_REF.findall(json.dumps(registered.config)):
        if snapshot.get(var):
            env[var] = str(snapshot[var])
    if os.environ.get(INSTANCE_ENV):
        env[INSTANCE_ENV] = os.environ[INSTANCE_ENV]
    return McpSource(name=name, command=sys.executable,
                     args=("-m", "impl.projects.llm_probe_loop.mcp_servers.trace", "--source", name),
                     env=tuple(sorted(env.items())), tools=("collect", "check"), timeout_seconds=COLLECT_SECONDS, max_chars=10**9)


def collect(value: Mapping[str, Any], *, request: Mapping[str, Any], response: Any) -> dict[str, Any]:
    """跑完业务时采集这一轮：成功、部分、失败都如实返回一份快照（失败写明原因），存进运行记录。"""
    from impl.projects.llm_probe_loop.eval_axes.sources.mcp_tools import call_tool

    source = str(value["source"])
    try:
        text, is_error = call_tool(trace_mcp_source(source), "collect",
                                   {"bindings": dict(value["bindings"]), "request": dict(request), "response": response})
    except Exception as exc:  # 进程拉不起、超时：采集失败，如实存档
        return {"status": "failed", "source": source, "errors": [f"trace 采集调用失败（{type(exc).__name__}）：{str(exc)[:300]}"]}
    if is_error:
        return {"status": "failed", "source": source, "errors": [f"trace 源报错：{text[:500]}"]}
    return json.loads(text)


def open_reader(snapshot: Mapping[str, Any]):
    """存档的确定性读取器（案卷路线）。"""
    provider = str(snapshot.get("provider") or "").strip().lower()
    module = _PROVIDERS.get(provider)
    if module is None:
        raise ValueError(f"业务 Trace 快照使用了未注册 provider {provider!r}")
    return module.open_reader(snapshot)


__all__ = ["check_connection", "check_source", "collect", "open_reader", "provider_descriptions", "trace_mcp_source", "validate_selection"]
