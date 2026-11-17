"""Export client connection settings without copying deployment credentials."""
import json
import os
from pathlib import Path
import sys
import tempfile


def export_client_config(name: str, mode: str, env_file: Path, config_path: Path,
                         server_script: Path, server_options: dict, output_dir: Path) -> tuple[Path, dict]:
    if mode == "stdio":
        server = {
            # Do not resolve the executable symlink: that can bypass the selected virtualenv.
            "command": str(Path(sys.executable).absolute()),
            "args": [str(server_script), "--env-file", str(env_file),
                     "--config", str(config_path), "--transport", "stdio"],
        }
    else:
        host = server_options["host"]
        if host == "0.0.0.0":
            host = "127.0.0.1"
        elif host == "::":
            host = "::1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        server = {"url": f"http://{host}:{server_options['port']}{server_options['path']}"}
    config = {"mcpServers": {name: server}}
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"mcp.client.{mode}.json"
    encoded = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    # A client-launched process may export the same file again; keep readers safe.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                     prefix=".mcp-client-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(encoded)
            handle.close()
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target, config
