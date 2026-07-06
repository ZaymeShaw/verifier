#!/bin/bash
set -euo pipefail

# 从 config.yaml 读取 python.executable；优先 PYTHON_EXECUTABLE 环境变量覆盖
# bootstrap 用系统默认 python 读 config（config.py 不依赖 agno）
PYTHON_BIN="${PYTHON_EXECUTABLE:-}"

if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN=$(python -c "from impl.core.config import get_python_config; print(get_python_config().executable)" 2>/dev/null || echo "python")
fi

SERVER_PORT=$("$PYTHON_BIN" -c "from impl.core.config import get_server_config; print(get_server_config().port)" 2>/dev/null || echo "8020")
kill -9 $(lsof -ti:"$SERVER_PORT") 2>/dev/null || true

exec "$PYTHON_BIN" -m impl.server "$@"
