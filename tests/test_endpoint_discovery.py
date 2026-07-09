from pathlib import Path
from types import SimpleNamespace

from impl.core.endpoint_discovery import EndpointDiscovery, load_discovered_tools, write_discovered_tools


def _spec(tmp_path: Path) -> SimpleNamespace:
    source_root = tmp_path / "app"
    source_root.mkdir()
    (source_root / "main.py").write_text(
        "from fastapi import Request\n"
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.post('/parse')\n"
        "async def parse(request: Request):\n"
        "    '''解析查询'''\n"
        "    return {}\n\n"
        "@router.get('/items/{item_id}')\n"
        "def get_item(item_id: str):\n"
        "    '''读取条目'''\n"
        "    return {}\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        project_id="demo",
        root=str(tmp_path),
        api={"base_url": "http://127.0.0.1:9"},
        endpoint_discovery={"source_roots": ["app"], "framework": "fastapi", "route_prefix": "/api/v1"},
    )


def test_endpoint_discovery_hides_framework_request_param(tmp_path):
    endpoints = EndpointDiscovery(_spec(tmp_path)).discover_raw()
    parse = next(endpoint for endpoint in endpoints if endpoint.function_name == "parse")

    assert parse.params == []
    assert parse.has_request_body is True


def test_discovered_tool_schema_uses_body_not_framework_request(tmp_path):
    spec = _spec(tmp_path)
    write_discovered_tools(spec)
    tools = load_discovered_tools(spec)
    parse_tool = next(tool for tool in tools if tool.tool_id == "demo.api.parse")

    assert "request" not in parse_tool.parameters["properties"]
    assert parse_tool.parameters["required"] == ["body"]
    assert "通用" not in parse_tool.description
    assert parse_tool.parameters["properties"]["body"]["description"]


def test_endpoint_discovery_preserves_business_route_params(tmp_path):
    endpoints = EndpointDiscovery(_spec(tmp_path)).discover_raw()
    get_item = next(endpoint for endpoint in endpoints if endpoint.function_name == "get_item")

    assert get_item.params == ["item_id"]
    assert get_item.has_request_body is False
