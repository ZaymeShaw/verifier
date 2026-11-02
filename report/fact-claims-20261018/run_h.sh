#!/bin/sh
# 用法：sh run_h.sh <old|new> <reps> <outdir> <H|all>
eval "$(grep -E '^LANGFUSE_INIT_PROJECT_(PUBLIC|SECRET)_KEY=' /Users/xiaozijian/WorkSpace/package/langfuse-deploy/.env | sed -e 's/^LANGFUSE_INIT_PROJECT_PUBLIC_KEY=/export LANGFUSE_PUBLIC_KEY=/' -e 's/^LANGFUSE_INIT_PROJECT_SECRET_KEY=/export LANGFUSE_SECRET_KEY=/')"
cd "$(dirname "$0")"
exec /Users/xiaozijian/miniconda3/envs/agno/bin/python -I exp_h.py "$@"
