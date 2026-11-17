import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from fastmcp import Client

from .config import load, validate_environment
from .runtime import Runtime
from .client_config import export_client_config

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parser = argparse.ArgumentParser(description="Configuration-driven HTTP to MCP server")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env",
                        help="Defaults to .env beside server.py; process environment takes precedence")
    parser.add_argument("--config", type=Path, help="Override MCP_CONFIG; relative to the selected .env directory")
    parser.add_argument("--transport", choices=("stdio", "http"), help="Override MCP_TRANSPORT")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Validate configuration and list tools without HTTP calls")
    action.add_argument("--client-config", action="store_true", help="Export client JSON without starting or checking upstream credentials")
    args = parser.parse_args()
    env_file = args.env_file.resolve()
    if env_file.is_file():
        values = dotenv_values(env_file)
        env = {key: os.environ.get(key, value or "") for key, value in values.items()}
    else:
        parser.error(f"Environment file not found: {env_file}; copy .env.example and fill required values")

    mode = args.transport or env.get("MCP_TRANSPORT", "stdio")
    if mode not in {"stdio", "http"}:
        parser.error("MCP_TRANSPORT must be stdio or http")
    server_options = {}
    if mode == "http":
        host = env.get("MCP_HOST", "127.0.0.1").strip()
        path = env.get("MCP_PATH", "/mcp")
        try:
            port = int(env.get("MCP_PORT", "8000"))
        except ValueError:
            parser.error("MCP_PORT must be an integer between 1 and 65535")
        if not host or not 1 <= port <= 65535 or not path.startswith("/") or "?" in path or "#" in path:
            parser.error("Invalid MCP_HOST, MCP_PORT (1..65535), or MCP_PATH (absolute URL path)")
        server_options = {"host": host, "port": port, "path": path}

    configured = str(args.config) if args.config else env.get("MCP_CONFIG", "").strip()
    if not configured:
        parser.error("MCP_CONFIG is required")
    config_path = (env_file.parent / configured).resolve()
    client_dir = env.get("MCP_CLIENT_CONFIG_DIR", "").strip()
    if not client_dir:
        parser.error("MCP_CLIENT_CONFIG_DIR is required; set the client configuration output directory in .env")
    output_dir = (env_file.parent / client_dir).resolve()

    try:
        settings, spec = load(config_path)
        client_path, client_config = export_client_config(
            settings.name, mode, env_file, config_path, ROOT / "server.py", server_options, output_dir)
        print(f"MCP 客户端配置（不代表服务已就绪）：{client_path}", file=sys.stderr)
        print("输出规则：同名文件整体覆盖，另一传输方式的文件保持不变。", file=sys.stderr)
        if mode == "http":
            print(f"MCP HTTP 地址：{client_config['mcpServers'][settings.name]['url']}；需先启动服务。", file=sys.stderr)
        else:
            print("stdio：将配置加入客户端，由客户端启动进程。", file=sys.stderr)
        if args.client_config:
            print(json.dumps(client_config, ensure_ascii=False, indent=2))
            return
        validate_environment(settings, env)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))

    try:
        runtime = Runtime(settings, spec, env=env)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        if args.check:
            async with Client(runtime.server) as client:
                tools = await client.list_tools()
                print(json.dumps({"config": str(config_path), "transport": mode,
                                  "client_config": str(client_path),
                                  "tools": [t.name for t in tools]}, ensure_ascii=False))
        else:
            await runtime.server.run_async(transport=mode, show_banner=False, **server_options)
    finally:
        await runtime.aclose()


if __name__ == "__main__":
    asyncio.run(main())
