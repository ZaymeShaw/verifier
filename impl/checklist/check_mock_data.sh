#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/../.."

# 从 config.yaml 读取 python.executable；优先 PYTHON_EXECUTABLE 环境变量覆盖
PYTHON_BIN="${PYTHON_EXECUTABLE:-}"
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN=$(python -c "from impl.core.config import get_python_config; print(get_python_config().executable)" 2>/dev/null || echo "python")
fi

"$PYTHON_BIN" -m impl.cli mock-check "$@"
