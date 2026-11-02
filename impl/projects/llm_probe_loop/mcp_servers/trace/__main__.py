"""trace 源的本地 MCP server（spec/alg/axis_loop.md §8.2）：去 trace 平台把这一轮取回来，是信息源的事。

跑完业务时由 live 层调 `collect`；登记页 / 场景页"测试连接"调 `check`（只用登记的连接，不涉及绑定）。
`collect`：连接配置取自全局登记（--source 指名），字段绑定由场景给；
返回 provider 的原样快照（status / association / records / errors…）。采集本身失败也是一份 status=failed 的快照，
如实存档；只有服务自己出错（登记不对、配置不合法）才 isError。

    python -m impl.projects.llm_probe_loop.mcp_servers.trace --source agno-insurance
"""

import argparse
import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from impl.projects.llm_probe_loop.business_trace.providers import agno, langfuse
from impl.projects.llm_probe_loop.eval_axes.sources.registry import load_trace_source

PROVIDERS = {"agno": agno, "langfuse": langfuse}


def build(source: str) -> FastMCP:
    registered = load_trace_source(source)
    provider = PROVIDERS[registered.type]
    server = FastMCP(f"trace-{source}")

    def collect(bindings: Annotated[dict[str, Any], Field(description="场景的字段绑定：关联标识从请求 / 响应的哪里取")],
                request: Annotated[dict[str, Any], Field(description="这一轮发给被测系统的请求（含 body）")],
                response: Annotated[Any, Field(description="被测系统这一轮的原始响应")]) -> str:
        config = provider.validate_config({**registered.config, "bindings": bindings})
        return json.dumps(provider.collect(config, request=request, response=response), ensure_ascii=False, default=str)

    def check() -> str:
        result = provider.check_connection(registered.config)
        if result.get("ok") is False:
            raise ValueError(f"trace 平台连不上：{result.get('error')}")
        return json.dumps(result, ensure_ascii=False, default=str)

    server.add_tool(collect, name="collect", description="取回这一轮的业务 trace 快照（按场景绑定关联到这一轮）。")
    server.add_tool(check, name="check", description="用登记的连接配置连一次 trace 平台，连不上就报错（登记页、场景页的测试连接用）。")
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    build(parser.parse_args().source).run("stdio")


if __name__ == "__main__":
    main()
