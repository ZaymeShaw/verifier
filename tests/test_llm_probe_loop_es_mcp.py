"""ES 经本地 MCP server 访问：返回与直连 EsTools 逐字一致（实施 P5）。需要本机 ES（local-es 登记），连不上就跳过。"""
from __future__ import annotations

import json
from urllib.request import urlopen

import pytest

from impl.projects.llm_probe_loop.eval_axes.sources import es_mcp_source, knowledge_tools
from impl.projects.llm_probe_loop.eval_axes.sources.es_tools import EsTools
from impl.projects.llm_probe_loop.eval_axes.sources.mcp_tools import McpTools
from impl.projects.llm_probe_loop.eval_axes.sources.registry import load_es_source


def _es_up() -> bool:
    try:
        with urlopen(load_es_source("local-es").base_url, timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _es_up(), reason="本机 ES 不可用")

INDEX = "local-es/hr_handbook"


def _mcp(name: str):
    tools = {t.tool_id: t for t in McpTools({"local-es": es_mcp_source("local-es", ["hr_handbook"])}, []).tools()}
    return tools[f"local_es__{name}"].execute_fn


def test_mcp_search_and_read_match_direct_es_tools_verbatim():
    direct = EsTools([{"source": "es", "uri": "es://" + INDEX}], [])
    want = direct.es_search(INDEX, "年休假 试用期")
    got = _mcp("es_search")(index=INDEX, query="年休假 试用期")
    assert got["isError"] is False and not got["truncated"]
    assert json.loads(got["text"]) == want
    locator = want["hits"][0]["locator"]
    assert json.loads(_mcp("es_read")(index=INDEX, locator=locator)["text"]) == direct.es_read(INDEX, locator)


def test_mcp_errors_are_flagged_and_other_indices_are_refused():
    got = _mcp("es_search")(index="local-es/clause_kb", query="犹豫期")
    assert got["isError"] is True and "目录" in got["error"]


def test_knowledge_tools_expose_es_through_mcp_with_described_params():
    tools = {t.tool_id: t for t in knowledge_tools([{"source": "es", "uri": "es://" + INDEX}], [])}
    assert set(tools) >= {"local_es__es_search", "local_es__es_read", "local_es__es_outline", "mcp_read", "mcp_find"}
    props = tools["local_es__es_search"].parameters["properties"]
    assert props["query"]["description"].startswith("空白分隔的关键词") and "<知识源名>/<索引>" in props["index"]["description"]
    assert "子串" in tools["local_es__es_search"].description
