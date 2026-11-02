"""trace 源登记与场景选用（spec/alg/axis_loop.md §2.4、§8.2）：连接在登记、绑定在场景；登记页 / 场景页的测试连接经 trace 源 MCP 服务。"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from impl.projects.llm_probe_loop import business_trace
from impl.projects.llm_probe_loop.business_trace.providers import agno, langfuse
from impl.projects.llm_probe_loop.eval_axes import sources
from impl.projects.llm_probe_loop.eval_axes.sources import registry


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "knowledge_sources.json"
    monkeypatch.setattr(registry, "registry_path", lambda: path)
    return path


@pytest.mark.parametrize("provider", [agno, langfuse])
def test_provider_templates_split_connection_from_bindings(provider):
    described = provider.describe()
    assert "bindings" not in described["default_connection"]
    clean = provider.validate_config({**described["default_connection"], "bindings": described["default_bindings"]})
    assert clean == {**provider.validate_connection(described["default_connection"]), "bindings": clean["bindings"]}


def test_trace_source_registry_checks_connection_shape_and_rejects_bindings(store):
    assert "agno" in sources.list_sources()["types"] and "langfuse" in sources.list_sources()["types"]
    with pytest.raises(ValueError, match="base_url"):
        sources.save_source("a", {"type": "agno", "config": {"base_url": "ftp://x"}})
    with pytest.raises(ValueError, match="不含 bindings"):
        sources.save_source("a", {"type": "agno", "config": {"base_url": "http://127.0.0.1:1", "bindings": {}}})
    sources.save_source("a", {"type": "agno", "description": "", "config": {"base_url": "http://127.0.0.1:1"}})
    assert json.loads(store.read_text())["a"]["type"] == "agno"


def test_scenario_selection_needs_registered_source_and_valid_bindings(store):
    sources.save_source("a", {"type": "agno", "config": {"base_url": "http://127.0.0.1:1"}})
    with pytest.raises(ValueError, match="未登记"):
        business_trace.validate_selection({"source": "b", "bindings": {}})
    with pytest.raises(ValueError, match="session_id"):
        business_trace.validate_selection({"source": "a", "bindings": {}})
    picked = business_trace.validate_selection({"source": "a", "bindings": agno.describe()["default_bindings"]})
    assert picked["type"] == "agno" and picked["config"]["base_url"] == "http://127.0.0.1:1"


class _Traces(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"data": []}).encode()
        self.send_response(200 if self.path.startswith("/traces") else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def test_check_goes_through_the_trace_mcp_server(store, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Traces)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        sources.save_source("up", {"type": "agno", "config": {"base_url": url}})
        sources.save_source("down", {"type": "agno", "config": {"base_url": "http://127.0.0.1:9", "timeout_seconds": 1}})
        # 测试里登记在临时文件：MCP 服务在进程内建（不拉子进程），调的仍是它注册的 check 工具
        from impl.projects.llm_probe_loop.mcp_servers.trace.__main__ import build

        calls = []

        def call_tool(source, name, arguments):
            calls.append((source.name, source.tools, name))
            tool = build(source.name)._tool_manager.get_tool(name)
            try:
                return tool.fn(**arguments), False
            except Exception as exc:
                return str(exc), True

        monkeypatch.setattr("impl.projects.llm_probe_loop.eval_axes.sources.mcp_tools.call_tool", call_tool)
        checked = sources.check_source("up")
        assert checked["type"] == "agno" and any(url in item for item in checked["items"])
        with pytest.raises(ValueError, match="连接失败"):
            sources.check_source("down")
        assert business_trace.check_connection({"source": "up", "bindings": agno.describe()["default_bindings"]})["ok"]
        assert {c[2] for c in calls} == {"check"} and all("check" in c[1] for c in calls)
    finally:
        server.shutdown()
