#!/bin/bash
# Schema propagation hook/check
# Runs a global schema audit and blocks when config.yaml marks findings as blocking.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# 从 config.yaml 读取 python.executable；优先 PYTHON_EXECUTABLE 环境变量覆盖
PYTHON_BIN="${PYTHON_EXECUTABLE:-}"
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN=$(python -c "from impl.core.config import get_python_config; print(get_python_config().executable)" 2>/dev/null || echo "python3")
fi
"$PYTHON_BIN" "$SCRIPT_DIR/schema_audit.py" "$@"
