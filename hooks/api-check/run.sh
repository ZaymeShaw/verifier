#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/../.."

# 从 config.yaml 读取 python.executable；优先 PYTHON_EXECUTABLE 环境变量覆盖
PYTHON_BIN="${PYTHON_EXECUTABLE:-}"
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN=$("python" -c "from impl.core.config import get_python_config; print(get_python_config().executable)" 2>/dev/null || true)
    if [ -z "$PYTHON_BIN" ]; then
        echo "ERROR: 无法读取 python.executable，请设置 PYTHON_EXECUTABLE 环境变量或在 config.yaml 中配置" >&2
        exit 1
    fi
fi
UAT_PORT=$("$PYTHON_BIN" -c "from impl.core.config import get_uat_config; print(get_uat_config().port)" 2>/dev/null || echo "8021")
export VERIFIER_UAT_PORT="${VERIFIER_UAT_PORT:-${UAT_PORT}}"

# 自动重启：先停掉旧服务，再启动新服务
if lsof -ti:"$VERIFIER_UAT_PORT" >/dev/null 2>&1; then
    echo "[api-check] killing existing verifier on port $VERIFIER_UAT_PORT..."
    kill "$(lsof -ti:"$VERIFIER_UAT_PORT")" 2>/dev/null || true
    sleep 2
    # 如果还没死，强杀
    if lsof -ti:"$VERIFIER_UAT_PORT" >/dev/null 2>&1; then
        echo "[api-check] force killing stuck verifier..."
        kill -9 "$(lsof -ti:"$VERIFIER_UAT_PORT")" 2>/dev/null || true
        sleep 1
    fi
fi

# 启动方式：优先用 START_SCRIPT 环境变量指定的 sh 脚本，否则用 python -m impl.server
START_SCRIPT="${API_CHECK_START_SCRIPT:-}"
if [ -n "$START_SCRIPT" ]; then
    echo "[api-check] starting via start script: $START_SCRIPT"
    if [ -x "$START_SCRIPT" ]; then
        bash "$START_SCRIPT" &
    else
        echo "ERROR: START_SCRIPT 不可执行或不存在: $START_SCRIPT" >&2
        exit 1
    fi
else
    echo "[api-check] starting verifier via python -m impl.server on port $VERIFIER_UAT_PORT..."
    "$PYTHON_BIN" -m impl.server --port "$VERIFIER_UAT_PORT" &
fi
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

# 等待服务就绪
echo "[api-check] waiting for server to be ready..."
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:$VERIFIER_UAT_PORT/health" >/dev/null 2>&1; then
        echo "[api-check] server ready on port $VERIFIER_UAT_PORT"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: server failed to start within 30s" >&2
        exit 1
    fi
    sleep 1
done

"$PYTHON_BIN" hooks/api-check/write_api_check_excel.py