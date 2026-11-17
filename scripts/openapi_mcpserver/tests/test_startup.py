"""Exercise the deployed entry point with .env and real MCP transports."""
import asyncio
import json
import os
import shlex
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest
import yaml
from dotenv import dotenv_values
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects/insurance-tools"
EXAMPLES = json.loads((ROOT / "tests/fixtures/tool_arguments.json").read_text())


@pytest.fixture
def clean_environment(monkeypatch):
    for key in dotenv_values(ROOT / ".env.example"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)


def check(env_file, cwd, env=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "server.py"), "--env-file", str(env_file), "--check"],
        cwd=cwd, env=env, text=True, capture_output=True, timeout=15,
    )


def test_missing_ark_values_fail_closed(tmp_path, clean_environment):
    env_file = tmp_path / ".env"
    env_file.write_text((ROOT / ".env.example").read_text().replace(
        "projects/insurance-tools/config.local.yaml", str(PROJECT / "config.local.yaml")))
    result = check(env_file, tmp_path)
    assert result.returncode != 0
    for name in ("MCP_AGENT_NUMBER", "MCP_AUTH_SUBJECT"):
        assert name in result.stderr
    assert not result.stdout


@pytest.fixture
def upstream():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            parsed = urlsplit(self.path)
            calls.append((parsed, dict(self.headers), json.loads(body) if body else None))
            if parsed.path == "/token":
                query = parse_qs(parsed.query)
                response = {"code": "0", "access_token": "token-" + query["invokeInterface"][0], "expires_in": 60}
            else:
                response = {"code": 0, "data": {"fixture": True, "path": parsed.path}}
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def configured_env(tmp_path, clean_environment, upstream):
    base_url, _ = upstream
    project = tmp_path / "projects/insurance-tools"
    project.mkdir(parents=True)
    for name in ("config.local.yaml", "openapi.json"):
        (project / name).write_bytes((PROJECT / name).read_bytes())
    values = dict(dotenv_values(ROOT / ".env.example"))
    values.update(MCP_AGENT_NUMBER="fixture-agent", MCP_AUTH_SUBJECT="fixture-subject",
                  ARK_CLIENT_ID="fixture-client", ARK_CLIENT_SECRET="fixture-secret", ARK_TOKEN_URL=base_url + "/token")
    auth_dir = project / "auth_curls"
    auth_dir.mkdir()
    for name in EXAMPLES:
        text = (PROJECT / "auth_curls" / f"{name}.txt").read_text()
        text = text.replace("grant_type=待填写", "grant_type=fixture-grant").replace("invokeInterface=待填写", "invokeInterface=" + name)
        (auth_dir / f"{name}.txt").write_text(text)
    config_file = project / "config.local.yaml"
    config = yaml.safe_load(config_file.read_text())
    for operation in config["operations"].values():
        operation["url"] = base_url + urlsplit(operation["url"]).path
    config_file.write_text(yaml.safe_dump(config))
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    return env_file


def test_check_resolves_project_relative_to_env_without_http(configured_env, upstream):
    _, calls = upstream
    result = check(configured_env, ROOT)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert set(report["tools"]) == set(EXAMPLES)
    assert report["config"] == str(configured_env.parent / "projects/insurance-tools/config.local.yaml")
    assert calls == []
    client_path = Path(report["client_config"])
    exported = json.loads(client_path.read_text())
    entry = next(iter(exported["mcpServers"].values()))
    assert entry["command"] == sys.executable
    assert entry["args"] == [str(ROOT / "server.py"), "--env-file", str(configured_env),
                             "--config", report["config"], "--transport", "stdio"]
    assert "fixture-secret" not in client_path.read_text()
    assert str(client_path) in result.stderr


def test_process_environment_overrides_dotenv(configured_env):
    result = check(configured_env, ROOT, {**os.environ, "MCP_AGENT_NUMBER": ""})
    assert result.returncode != 0
    assert "Missing environment variables: MCP_AGENT_NUMBER" in result.stderr
    assert "fixture-secret" not in result.stderr


async def test_live_config_stdio_calls_all_ten_with_fresh_ark_tokens(configured_env, upstream, tmp_path):
    _, calls = upstream
    result = check(configured_env, tmp_path)
    assert result.returncode == 0, result.stderr
    exported = json.loads(Path(json.loads(result.stdout)["client_config"]).read_text())
    # Launch the real MCP subprocess directly from the exported connection config.
    async with Client(exported) as client:
        assert {tool.name for tool in await client.list_tools()} == set(EXAMPLES)
        for name, args in EXAMPLES.items():
            result = await client.call_tool(name, args)
            assert result.data["data"]["fixture"] is True
            parsed, headers, body = calls[-1]
            assert headers["token"] == "token-" + name
            for identity in ("empno", "agentno", "agentNo"):
                if identity in body:
                    assert body[identity] == "fixture-agent"
        # A repeat obtains a fresh token before the next business request.
        await client.call_tool("policy_query", EXAMPLES["policy_query"])
    token_calls = [call for call in calls if call[0].path == "/token"]
    assert len(token_calls) == 11
    assert len(calls) == 22
    for parsed, _, body in token_calls:
        assert body is None
        query = parse_qs(parsed.query)
        assert query["client_secret"] == ["fixture-secret"]
        assert query["client_id"] == ["fixture-client"]
        assert query["grant_type"] == ["fixture-grant"]


def test_missing_curl_auth_credential_fails_startup(configured_env, upstream, tmp_path):
    configured_env.write_text(configured_env.read_text().replace("ARK_CLIENT_SECRET=fixture-secret", "ARK_CLIENT_SECRET="))
    result = check(configured_env, tmp_path)
    assert result.returncode != 0
    assert "Cannot load auth handler" in result.stderr
    assert upstream[1] == []


async def test_auth_receives_only_declared_env_keys_with_process_override(configured_env, tmp_path, monkeypatch):
    script = configured_env.parent / "projects/insurance-tools/auth.py"
    script.write_text('''async def main(env):
    assert "UNDECLARED_SECRET" not in env
    assert env["ARK_CLIENT_SECRET"] == "overridden"
    return "test-token"
''')
    config_file = script.with_name("config.local.yaml")
    config = yaml.safe_load(config_file.read_text())
    for operation in config["operations"].values():
        operation["auth"] = "auth.py:main"
    config_file.write_text(yaml.safe_dump(config))
    monkeypatch.setenv("UNDECLARED_SECRET", "must-not-be-forwarded")
    monkeypatch.setenv("ARK_CLIENT_SECRET", "overridden")
    transport = StdioTransport(command=sys.executable,
                               args=[str(ROOT / "server.py"), "--env-file", str(configured_env)],
                               cwd=str(tmp_path), env={"ARK_CLIENT_SECRET": "overridden",
                                                       "UNDECLARED_SECRET": "must-not-be-forwarded"})
    async with Client(transport) as client:
        result = await client.call_tool("policy_query", EXAMPLES["policy_query"])
        assert result.data["code"] == 0


async def test_http_entrypoint_lists_and_calls_tools(configured_env, upstream, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    text = configured_env.read_text().replace("MCP_TRANSPORT=stdio", "MCP_TRANSPORT=http")
    text = text.replace("MCP_PORT=8000", f"MCP_PORT={port}").replace("MCP_PATH=/mcp", "MCP_PATH=/insurance")
    configured_env.write_text(text)
    with (tmp_path / "server.log").open("w+") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "server.py"), "--env-file", str(configured_env),
            cwd=tmp_path, stdout=log, stderr=log,
        )
        try:
            url = f"http://127.0.0.1:{port}/insurance"
            async with asyncio.timeout(15):
                async with httpx.AsyncClient(trust_env=False, timeout=1) as probe:
                    while True:
                        if process.returncode is not None:
                            log.seek(0)
                            pytest.fail(log.read())
                        try:
                            await probe.get(url)
                            break
                        except httpx.TransportError:
                            await asyncio.sleep(0.05)
                # Keep loopback fixtures independent of the host's system proxy settings.
                output_dir = (configured_env.parent / dotenv_values(configured_env)["MCP_CLIENT_CONFIG_DIR"]).resolve()
                exported = json.loads((output_dir / "mcp.client.http.json").read_text())
                client_url = next(iter(exported["mcpServers"].values()))["url"]
                assert client_url == url
                transport = StreamableHttpTransport(
                    client_url, httpx_client_factory=lambda **kwargs: httpx.AsyncClient(trust_env=False, **kwargs)
                )
                async with Client(transport) as client:
                    assert {tool.name for tool in await client.list_tools()} == set(EXAMPLES)
                    for name, args in EXAMPLES.items():
                        result = await client.call_tool(name, args)
                        parsed, headers, body = upstream[1][-1]
                        assert result.data == {"code": 0, "data": {"fixture": True, "path": parsed.path}}
                        assert headers["token"] == "token-" + name
                        assert "traceId" not in body
                        if name == "policy_parse":
                            assert body["trace_id"] and body["trace_id"] != body["session_id"]
                        else:
                            assert "trace_id" not in body
                        for identity in ("empno", "agentno", "agentNo"):
                            if identity in body:
                                assert body[identity] == "fixture-agent"
                    await client.call_tool("policy_query", EXAMPLES["policy_query"])
                assert len(upstream[1]) == 22
                assert sum(call[0].path == "/token" for call in upstream[1]) == 11
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await process.wait()


async def test_saved_draft_http_server_calls_all_tools(configured_env, upstream, tmp_path):
    """Use the actual on-disk draft artifact, not a freshly generated stand-in."""
    project = configured_env.parent / "projects/insurance-tools"
    draft = project / "draft"
    draft.mkdir()
    original_spec = (PROJECT / "draft/openapi.draft.json").read_bytes()
    (draft / "openapi.draft.json").write_bytes(original_spec)
    config = yaml.safe_load((PROJECT / "draft/config.draft.yaml").read_text())
    for operation in config["operations"].values():
        operation["url"] = upstream[0] + urlsplit(operation["url"]).path
        assert operation["auth"]["curl"].startswith("../auth_curls/")
    (draft / "config.draft.yaml").write_text(yaml.safe_dump(config))
    configured_env.write_text(configured_env.read_text().replace("config.local.yaml", "draft/config.draft.yaml"))
    checked = check(configured_env, tmp_path)
    assert checked.returncode == 0, checked.stderr
    assert set(json.loads(checked.stdout)["tools"]) == set(EXAMPLES)
    assert upstream[1] == []
    await test_http_entrypoint_lists_and_calls_tools(configured_env, upstream, tmp_path)
    assert (draft / "openapi.draft.json").read_bytes() == original_spec
    report = {
        "source": str(PROJECT / "draft"), "transport": "http",
        "upstream": "local mock HTTP services", "server_stopped_after_test": True,
        "tools": list(EXAMPLES), "business_requests": 11, "auth_requests": 11,
        "example": {"tool": "policy_query", "arguments": EXAMPLES["policy_query"],
                    "sent_body": upstream[1][-1][2],
                    "response": {"code": 0, "data": {"fixture": True, "path": upstream[1][-1][0].path}}},
    }
    report_path = tmp_path / "draft-http-result.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"\nDraft HTTP test report: {report_path}")


async def test_curl_directory_to_matching_drafts_to_stdio_calls(configured_env, upstream, tmp_path):
    project = configured_env.parent / "projects/insurance-tools"
    sources = project / "curls"
    sources.mkdir()
    formal = yaml.safe_load((project / "config.local.yaml").read_text())
    samples = json.loads((ROOT / "tests/fixtures/source_requests.json").read_text())
    for name in EXAMPLES:
        url = formal["operations"][name]["url"]
        body = samples[name]["body"]
        body.pop("trace_id", None)
        body.pop("traceId", None)
        (sources / f"{name}.txt").write_text(
            "curl " + shlex.quote(url) + " --header 'token: ${token}' --json " + shlex.quote(json.dumps(body)))
    generated = subprocess.run(
        [sys.executable, str(ROOT / "generate_openapi.py"), str(sources), "--output-dir", str(project / "draft")],
        cwd=tmp_path, capture_output=True, text=True, timeout=15,
    )
    assert generated.returncode == 0, generated.stderr
    assert upstream[1] == []
    configured_env.write_text(configured_env.read_text().replace("config.local.yaml", "draft/config.draft.yaml"))
    config = yaml.safe_load((project / "draft/config.draft.yaml").read_text())
    for name, operation in config["operations"].items():
        original = formal["operations"][name]
        assert operation["auth"]["token_path"] == original["auth"]["token_path"]
        assert operation.get("inject_body", {}) == original.get("inject_body", {})
        assert (project / "draft" / operation["auth"]["curl"]).resolve() == (project / original["auth"]["curl"]).resolve()
    assert not (project / "draft/auth_curls").exists()
    assert not (project / "draft/.env").exists()
    # No hand-written fixes between generation and startup.
    checked = check(configured_env, tmp_path)
    assert checked.returncode == 0, checked.stderr
    assert set(json.loads(checked.stdout)["tools"]) == set(EXAMPLES)
    assert upstream[1] == []
    transport = StdioTransport(command=sys.executable,
                               args=[str(ROOT / "server.py"), "--env-file", str(configured_env)],
                               cwd=str(tmp_path))
    async with Client(transport) as client:
        assert {tool.name for tool in await client.list_tools()} == set(EXAMPLES)
        for name, args in EXAMPLES.items():
            result = await client.call_tool(name, args)
            path = urlsplit(formal["operations"][name]["url"]).path
            assert result.data == {"code": 0, "data": {"fixture": True, "path": path}}
            parsed, headers, body = upstream[1][-1]
            assert parsed.path == path
            assert headers["token"] == "token-" + name
            if name == "policy_query":
                assert body == {**args, "empno": "fixture-agent"}
            if name == "policy_parse":
                assert body["extra_input_params"]["policySearchParseArgs"]["agentCode"] == "fixture-agent"
                assert body["extra_input_params"]["policySearchParseArgs"]["query"] == args["extra_input_params"]["policySearchParseArgs"]["query"]
    assert len(upstream[1]) == 20
    assert sum(call[0].path == "/token" for call in upstream[1]) == 10


@pytest.mark.parametrize('absolute_output', [False, True])
def test_export_only_works_without_credentials_and_preserves_draft_selection(tmp_path, clean_environment, absolute_output):
    project = tmp_path / "project"
    project.mkdir()
    for name in ("config.local.yaml", "openapi.json"):
        (project / name).write_bytes((PROJECT / name).read_bytes())
    env_file = tmp_path / ".env"
    env_file.write_text("MCP_CONFIG=wrong.yaml\nMCP_CLIENT_CONFIG_DIR=exports/client files\nMCP_TRANSPORT=http\nMCP_HOST=0.0.0.0\nMCP_PORT=8123\nMCP_PATH=/tools/mcp\n")
    if absolute_output:
        env_file.write_text(env_file.read_text().replace('=exports/client files', '=' + str(tmp_path / 'exports/client files')))
    command = [sys.executable, str(ROOT / "server.py"), "--env-file", str(env_file),
               "--config", str(project / "config.local.yaml"), "--client-config"]
    exported = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert exported.returncode == 0, exported.stderr
    config = json.loads(exported.stdout)
    assert next(iter(config["mcpServers"].values())) == {"url": "http://127.0.0.1:8123/tools/mcp"}
    assert config == json.loads((tmp_path / "exports/client files/mcp.client.http.json").read_text())
    assert str(tmp_path / "exports/client files/mcp.client.http.json") in exported.stderr
    assert "同名文件整体覆盖" in exported.stderr
    exported = subprocess.run(command + ["--transport", "stdio"], cwd=tmp_path,
                              capture_output=True, text=True, timeout=15)
    assert exported.returncode == 0, exported.stderr
    entry = next(iter(json.loads(exported.stdout)["mcpServers"].values()))
    assert entry["args"][-2:] == ["--transport", "stdio"]
    assert str(project / "config.local.yaml") in entry["args"]
    assert (tmp_path / "exports/client files/mcp.client.stdio.json").is_file()
    assert config == json.loads((tmp_path / "exports/client files/mcp.client.http.json").read_text())
    assert not list(project.glob('mcp.client.*.json'))
    assert not (project / "auth_curls").exists()  # Export does not import auth or require its credentials.


def test_missing_client_output_directory_is_explicit_error(configured_env, tmp_path):
    configured_env.write_text('\n'.join(line for line in configured_env.read_text().splitlines()
                                       if not line.startswith('MCP_CLIENT_CONFIG_DIR=')))
    result = check(configured_env, tmp_path)
    assert result.returncode != 0
    assert 'MCP_CLIENT_CONFIG_DIR is required' in result.stderr
