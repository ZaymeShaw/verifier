#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/../.."

# 公共覆盖由统一 resolver 处理；脚本只消费类型化解析结果。
PYTHON_BIN=$(python -c "from impl.core.config import get_python_config; print(get_python_config().executable)")

"$PYTHON_BIN" -m impl.cli mock-check "$@"
