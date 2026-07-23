#!/bin/bash
set -euo pipefail

# bootstrap 用系统默认 python 调统一 resolver（config.py 不依赖 agno）。
PYTHON_BIN=$(python -c "from impl.core.config import get_python_config; print(get_python_config().executable)")

SERVER_PORT=$("$PYTHON_BIN" -c "from impl.core.config import get_server_config; print(get_server_config().port)" 2>/dev/null || echo "8020")
kill -9 $(lsof -ti:"$SERVER_PORT") 2>/dev/null || true

"$PYTHON_BIN" -m impl.core.runtime_preflight

exec "$PYTHON_BIN" -m impl.server "$@"
