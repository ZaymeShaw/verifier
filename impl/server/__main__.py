from __future__ import annotations

import argparse

from impl.core.config import initialize_runtime_config


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    parser.add_argument("--host")
    args = parser.parse_args(argv)
    cli_overrides = {}
    if args.port is not None:
        cli_overrides["server.port"] = args.port
    if args.host is not None:
        cli_overrides["server.host"] = args.host
    server_config = initialize_runtime_config(cli_overrides=cli_overrides).server
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("FastAPI server requires uvicorn. Install fastapi and uvicorn before starting impl.server.") from exc
    print(f"serving http://{server_config.host}:{server_config.port}")
    uvicorn.run("impl.server.app:app", host=server_config.host, port=server_config.port, reload=False)


if __name__ == "__main__":
    main()
