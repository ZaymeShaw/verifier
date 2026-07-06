#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/../.."

# 从 config.yaml 读取 python.executable；优先 PYTHON_EXECUTABLE 环境变量覆盖
PYTHON_BIN="${PYTHON_EXECUTABLE:-}"
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN=$(python -c "from impl.core.config import get_python_config; print(get_python_config().executable)" 2>/dev/null || echo "python")
fi
UAT_PORT=$("$PYTHON_BIN" -c "from impl.core.config import get_uat_config; print(get_uat_config().port)" 2>/dev/null || echo "8021")
export VERIFIER_UAT_PORT="${VERIFIER_UAT_PORT:-$UAT_PORT}"

kill -9 $(lsof -ti:"$VERIFIER_UAT_PORT") 2>/dev/null || true

# 预检：固化 mock 数据是否符合 live_schema/ready 协议；失败直接退出，避免 E2E 跑到一半才发现。
"$PYTHON_BIN" -m impl.cli mock-check

"$PYTHON_BIN" -m impl.server --port "$VERIFIER_UAT_PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

sleep "${VERIFIER_SERVER_WAIT:-10}"
"$PYTHON_BIN" impl/checklist/check1.py