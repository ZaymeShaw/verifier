#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# verifier 统一入口：自动从 config.yaml 读取正确的 python 解释器（agno env），
# 无需使用者关心 conda 环境。所有需要 python 的子命令都通过此脚本转发。
#
# 用法：
#   bash run.sh server [--port PORT]     启动 verifier 服务（默认端口 8020）
#   bash run.sh uat [--port PORT]        启动 UAT 服务（默认读取 impl/config.yaml）
#   bash run.sh check1                   跑 checklist check1（自动启动 UAT 服务）
#   bash run.sh api-check                跑 api-check（自动启动/复用 UAT 服务）
#   bash run.sh config-check             校验三层配置、.env 和消费者旁路
#   bash run.sh cli <args>               跑 impl.cli，透传剩余参数
#   bash run.sh python <args>            用正确解释器跑任意 python 命令
#
# 环境变量：
#   PYTHON_EXECUTABLE  覆盖 config.yaml 的 python.executable（最高优先级）

# bootstrap：用系统默认 python 调统一 resolver（config.py 不依赖 agno）。
# process environment / .env 覆盖均由 resolver 处理，脚本不建立第二条解析链。
PYTHON_BIN=$(python -c "from impl.core.config import get_python_config; print(get_python_config().executable)")
export PYTHON_EXECUTABLE="$PYTHON_BIN"

CMD="${1:-help}"
shift || true

case "$CMD" in
    tracing)
        exec "$PYTHON_BIN" scripts/tracing.py "$@"
        ;;
    server)
        "$PYTHON_BIN" -m impl.core.runtime_preflight
        exec "$PYTHON_BIN" -m impl.server "$@"
        ;;
    uat)
        "$PYTHON_BIN" -m impl.core.runtime_preflight
        PORT="${1:-}"
        if [ -n "$PORT" ]; then shift; fi
        UAT_PORT=$("$PYTHON_BIN" -c "from impl.core.config import get_uat_config; print(get_uat_config().port)")
        PORT="${PORT:-$UAT_PORT}"
        exec "$PYTHON_BIN" -m impl.server --port "$PORT"
        ;;
    check1)
        exec bash impl/checklist/check1.sh "$@"
        ;;
    api-check)
        exec bash hooks/api-check/run.sh "$@"
        ;;
    config-check)
        exec "$PYTHON_BIN" -m impl.core.config_check "$@"
        ;;
    cli)
        exec "$PYTHON_BIN" -m impl.cli "$@"
        ;;
    python)
        exec "$PYTHON_BIN" "$@"
        ;;
    help|*)
        cat <<'USAGE'
verifier 统一入口（自动从 config.yaml 读取正确的 python 解释器）

用法：
  bash run.sh server [--port PORT]     启动 verifier 服务（直连 .env 上游）
  bash run.sh tracing <command>       中转 up/down/status/show/run；报告 runs/report；清理 cleanup
  bash run.sh tracing run server      经本地中转启动服务，保留原始 .env
  bash run.sh tracing runs --port 8022 列出该端口实例的采集批次
  bash run.sh tracing report --port 8022 --open  导出本实例最近一次执行 HTML
  bash run.sh tracing report --port 8022 --project llm_probe --open  导出当前用例池（含补跑）
  bash run.sh uat [--port PORT]        启动 UAT 服务
  bash run.sh check1                   跑 checklist check1
  bash run.sh api-check                跑 api-check
  bash run.sh config-check             校验公共、项目、知识路由配置合同
  bash run.sh cli <args>               跑 impl.cli
  bash run.sh python <args>            用正确解释器跑任意 python

环境变量：
  PYTHON_EXECUTABLE  覆盖 config.yaml 的 python.executable
USAGE
        ;;
esac
