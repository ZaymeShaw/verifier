from pathlib import Path

from impl.core.endpoint_discovery import EndpointDiscovery, load_discovered_tools, write_discovered_tools
from impl.core.path_contract import PathResolver, PathRoots
from impl.core.schema import ProjectSpec


def _spec(tmp_path: Path) -> ProjectSpec:
    repository_root = tmp_path / "verifier"
    project_root = repository_root / "impl" / "projects" / "demo"
    project_root.mkdir(parents=True)
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
    service = {
        "base_url": "http://127.0.0.1:9",
        "endpoint": "/api/v1/parse",
        "method": "POST",
        "timeout_seconds": 17,
    }
    roots = PathRoots(
        verifier_repo=repository_root.resolve(),
        business_source=source_root.resolve(),
        project_package=project_root.resolve(),
        knowledge_route=(tmp_path / "route").resolve(),
        artifact_package=(tmp_path / "artifacts").resolve(),
    )
    spec = ProjectSpec(
        project_id="demo",
        name="demo",
        verifier={
            "endpoint_discovery": {
                "enabled": True,
                "framework": "fastapi",
                "route_prefix": "/api/v1",
                "scan_patterns": ["*.py"],
                "exclude_patterns": [],
                "blacklist": {"methods": [], "route_keywords": []},
                "source_roots": ["business://."],
            }
        },
        path_roots=roots,
        path_resolver=PathResolver(roots),
    )
    spec.require_service = lambda _service_id="primary": dict(service)
    return spec


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


def test_discovered_tool_uses_project_service_timeout(tmp_path, monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(_request, timeout):
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    spec = _spec(tmp_path)
    write_discovered_tools(spec)
    parse_tool = next(tool for tool in load_discovered_tools(spec) if tool.tool_id == "demo.api.parse")

    result = parse_tool.execute_fn(body={"query": "x"})

    assert result.status == "succeeded"
    assert captured["timeout"] == 17
