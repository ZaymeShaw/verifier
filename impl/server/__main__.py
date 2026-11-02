from __future__ import annotations

import argparse

from impl.core.config import initialize_runtime_config, resolve_runtime_config
from impl.core.instances import resolve_instance, instance_lock, activate
import os


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
    initial = resolve_runtime_config(cli_overrides=cli_overrides)
    instance = resolve_instance(initial.server.port)
    try:
        with instance_lock(instance):
            activate(instance)
            if os.environ.get('VERIFIER_TRACING_ENABLED') == '1':
                from scripts.tracing import start_relays
                os.environ.update(start_relays(instance, initial.llm))
            server_config = initialize_runtime_config(cli_overrides=cli_overrides, force=True).server
            try:
                import uvicorn
            except ImportError as exc:
                raise SystemExit('FastAPI server requires uvicorn. Install fastapi and uvicorn before starting impl.server.') from exc
            print(f"serving http://{server_config.host}:{server_config.port} instance={instance['id']}")
            uvicorn.run('impl.server.app:app', host=server_config.host, port=server_config.port, reload=False)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
