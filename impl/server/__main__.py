from __future__ import annotations

import argparse

from impl.core.config import get_server_config


def main(argv=None):
    server_config = get_server_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=server_config.port)
    parser.add_argument("--host", default=server_config.host)
    args = parser.parse_args(argv)
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("FastAPI server requires uvicorn. Install fastapi and uvicorn before starting impl.server.") from exc
    print(f"serving http://{args.host}:{args.port}")
    uvicorn.run("impl.server.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
