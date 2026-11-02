"""ES 知识源的本地 MCP server（spec/alg/axis_loop.md §8）：评测侧访问外部信息源一律走 MCP。

检索语义不变：直接用 eval_axes/sources/es_tools.py 的 EsTools（空白拆词、子串匹配、命中词多者排前）。
连接取自知识源登记（同一个数据根，靠父进程传下来的 VERIFIER_INSTANCE_ID 定位）；
场景选用的索引由 --indices 传入，只能查这些。工具出错时抛异常，MCP 返回 isError=true。

    python -m impl.projects.llm_probe_loop.mcp_servers.es --source local-es --indices hr_handbook,clause_kb
"""

import argparse
from typing import Annotated, Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from impl.projects.llm_probe_loop.eval_axes.sources.es_tools import INDEX_PARAM, EsTools


def build(source: str, indices: list[str]) -> FastMCP:
    tools = EsTools([{"source": "es", "uri": f"es://{source}/{index}"} for index in indices], recorder=[])
    server = FastMCP(f"es-{source}")
    described = {name: description for name, _, description, _ in tools.specs()}

    def checked(result: dict[str, Any]) -> dict[str, Any]:
        if "error" in result:
            raise ValueError(result["error"])
        return result

    Index = Annotated[str, Field(description=INDEX_PARAM["description"])]
    params = {name: p for _, _, _, spec in tools.specs() for name, p in spec.items()}

    def es_outline(index: Index) -> dict[str, Any]:
        return checked(tools.es_outline(index))

    def es_search(index: Index, query: Annotated[str, Field(description=params["query"]["description"])],
                  fields: Annotated[Optional[list[str]], Field(description=params["fields"]["description"])] = None) -> dict[str, Any]:
        return checked(tools.es_search(index, query, fields))

    def es_read(index: Index, locator: Annotated[str, Field(description=params["locator"]["description"])]) -> dict[str, Any]:
        return checked(tools.es_read(index, locator))

    for fn in (es_outline, es_search, es_read):
        server.add_tool(fn, name=fn.__name__, description=described[fn.__name__])
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--indices", required=True, help="逗号分隔的索引名")
    args = parser.parse_args()
    build(args.source, [i for i in args.indices.split(",") if i]).run("stdio")


if __name__ == "__main__":
    main()
