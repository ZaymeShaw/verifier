#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/../.."

# 公共覆盖由统一 resolver 处理；脚本只消费类型化解析结果。
PYTHON_BIN=$(python -c "from impl.core.config import get_python_config; print(get_python_config().executable)")
UAT_PORT=$("$PYTHON_BIN" -c "from impl.core.config import get_uat_config; print(get_uat_config().port)")

kill -9 $(lsof -ti:"$UAT_PORT") 2>/dev/null || true

# 预检：固化 mock 数据是否符合 live_schema/ready 协议；失败直接退出，避免 E2E 跑到一半才发现。
"$PYTHON_BIN" -m impl.cli mock-check

"$PYTHON_BIN" -m impl.server --port "$UAT_PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

sleep "${VERIFIER_SERVER_WAIT:-10}"
"$PYTHON_BIN" impl/checklist/check1.py
