#!/bin/sh
# 用法：sh run.sh <variant> [--workers N]；Langfuse 项目密钥以进程环境变量传入
eval "$(grep -E '^LANGFUSE_INIT_PROJECT_(PUBLIC|SECRET)_KEY=' /Users/xiaozijian/WorkSpace/package/langfuse-deploy/.env | sed -e 's/^LANGFUSE_INIT_PROJECT_PUBLIC_KEY=/export LANGFUSE_PUBLIC_KEY=/' -e 's/^LANGFUSE_INIT_PROJECT_SECRET_KEY=/export LANGFUSE_SECRET_KEY=/')"
exec /Users/xiaozijian/miniconda3/envs/agno/bin/python -I "$(dirname "$0")/run_new.py" "$@"
