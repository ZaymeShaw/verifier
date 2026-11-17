"""Run the real insurance MCP against local, authenticated mock HTTP endpoints."""
import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import yaml
from fastmcp import Client

from curl_mcp.client_config import export_client_config

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "projects/insurance-tools"
OUTPUT = ROOT / ".mock/insurance-tools"
CLIENT_ID = "mock-client"
CLIENT_SECRET = "mock-secret"


def mock_handler(operations, events):
    tokens = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Default HTTP logs would expose the auth query string.

        def reply(self, status, data):
            encoded = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/token":
                query = parse_qs(parsed.query)
                name = query.get("invokeInterface", [""])[0]
                if (query.get("client_id") != [CLIENT_ID]
                        or query.get("client_secret") != [CLIENT_SECRET]
                        or query.get("grant_type") != ["mock-grant"]
                        or name not in operations):
                    events.append(("auth_denied", name))
                    print(f"[mock] auth denied: {name}", flush=True)
                    return self.reply(401, {"error": "invalid_mock_credentials"})
                token = secrets.token_urlsafe(24)
                tokens[token] = name
                events.append(("auth", name))
                print(f"[mock] auth OK: {name}", flush=True)
                return self.reply(200, {"code": "0", "access_token": token})

            name = parsed.path.removeprefix("/business/")
            if parsed.path != f"/business/{name}" or name not in operations:
                return self.reply(404, {"error": "unknown_mock_operation"})
            if tokens.get(self.headers.get("token")) != name:
                events.append(("business_denied", name))
                return self.reply(401, {"error": "invalid_mock_token"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            except (ValueError, TypeError):
                return self.reply(400, {"error": "invalid_json"})
            events.append(("business", name))
            print(f"[mock] business OK: {name} (token verified)", flush=True)
            self.reply(200, {"code": 0, "data": {
                "mock": True, "operation": name, "token_verified": True,
                "received_body": body,
            }})

    return Handler


def prepare(config, base_url, mode, mcp_port):
    """Generate only disposable mock files; retain the real schemas/injection rules."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "auth_curls").mkdir(exist_ok=True)
    (OUTPUT / "openapi.json").write_bytes((SOURCE / config["openapi"]).read_bytes())
    config.update(name="insurance-tools-mock", openapi="openapi.json")
    for name, operation in config["operations"].items():
        operation["url"] = f"{base_url}/business/{name}"
        operation["auth"] = {"curl": f"auth_curls/{name}.txt", "token_path": "/access_token"}
        curl = (SOURCE / "auth_curls" / f"{name}.txt").read_text()
        curl = curl.replace("grant_type=待填写", "grant_type=mock-grant")
        curl = curl.replace("invokeInterface=待填写", f"invokeInterface={name}")
        (OUTPUT / "auth_curls" / f"{name}.txt").write_text(curl)
    config_path = OUTPUT / "config.local.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    env = {
        "MCP_CONFIG": "config.local.yaml", "MCP_TRANSPORT": mode,
        "MCP_CLIENT_CONFIG_DIR": "client-configs",
        "MCP_HOST": "127.0.0.1", "MCP_PORT": str(mcp_port), "MCP_PATH": "/mcp",
        "MCP_AGENT_NUMBER": "mock-agent", "MCP_AUTH_SUBJECT": "mock-subject",
        "ARK_TOKEN_URL": base_url + "/token",
        "ARK_CLIENT_ID": CLIENT_ID, "ARK_CLIENT_SECRET": CLIENT_SECRET,
    }
    env_file = OUTPUT / ".env"
    env_file.write_text("# Generated local mock settings; no real credentials.\n" +
                        "".join(f"{key}={value}\n" for key, value in env.items()))
    return config_path, env_file, env


async def verify(client_config, base_url, events):
    examples = json.loads((ROOT / "tests/fixtures/tool_arguments.json").read_text())
    async with Client(client_config) as client:
        assert {tool.name for tool in await client.list_tools()} == set(examples)
        for name, args in examples.items():
            result = await client.call_tool(name, args)
            assert result.data["data"]["mock"] is True
            assert result.data["data"]["token_verified"] is True
            assert result.data["data"]["operation"] == name
            assert events[-2:] == [("auth", name), ("business", name)]
            print(f"[PASS] MCP → auth cURL → token → {name}", flush=True)
    # Bad credentials must fail inside the real MCP path before business HTTP.
    server = next(iter(client_config["mcpServers"].values()))
    server["env"] = {"ARK_CLIENT_SECRET": "wrong-mock-secret"}
    before = len(events)
    async with Client(client_config) as client:
        result = await client.call_tool("policy_query", examples["policy_query"], raise_on_error=False)
        assert result.is_error
    assert events[before:] == [("auth_denied", "policy_query")]
    print("[PASS] 错误凭据：MCP 调用失败，没有发送业务请求", flush=True)
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post(base_url + "/business/policy_query", json={}, headers={"token": "wrong"})
        assert response.status_code == 401
    print("[PASS] 业务接口拒绝无效 token", flush=True)
    print(f"完成：{len(examples)} 个工具鉴权链路 + 2 项失败检查。全部使用本地 mock。", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="Test all tools over real MCP stdio, then exit")
    parser.add_argument("--upstream-port", type=int, default=8765)
    parser.add_argument("--mcp-port", type=int, default=8766)
    args = parser.parse_args()
    config = yaml.safe_load((SOURCE / "config.local.yaml").read_text())
    events = []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0 if args.test else args.upstream_port),
                                   mock_handler(config["operations"], events))
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{upstream.server_port}"
        mode = "stdio" if args.test else "http"
        config_path, env_file, env = prepare(config, base_url, mode, args.mcp_port)
        # Process env takes priority over dotenv. Pin mock values in this demo process
        # and its children, independently of the user's shell or production .env.
        os.environ.update(env)
        client_path, client_config = export_client_config(
            config["name"], mode, env_file, config_path, ROOT / "server.py",
            {"host": "127.0.0.1", "port": args.mcp_port, "path": "/mcp"},
            env_file.parent / env["MCP_CLIENT_CONFIG_DIR"])
        print(f"本地 mock 上游：{base_url}\n测试配置：{env_file}\n客户端配置：{client_path}", flush=True)
        if args.test:
            asyncio.run(verify(client_config, base_url, events))
        else:
            print("保持此终端运行；将上述 HTTP 客户端配置加入 MCP 客户端。Ctrl+C 停止。", flush=True)
            with subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--env-file", str(env_file)]) as process:
                try:
                    return process.wait()
                except KeyboardInterrupt:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
