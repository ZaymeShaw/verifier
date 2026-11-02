#!/bin/sh
eval "$(grep -E '^LANGFUSE_INIT_PROJECT_(PUBLIC|SECRET)_KEY=' /Users/xiaozijian/WorkSpace/package/langfuse-deploy/.env | sed -e 's/^LANGFUSE_INIT_PROJECT_PUBLIC_KEY=/export LANGFUSE_PUBLIC_KEY=/' -e 's/^LANGFUSE_INIT_PROJECT_SECRET_KEY=/export LANGFUSE_SECRET_KEY=/')"
cd "$(dirname "$0")"
exec /Users/xiaozijian/miniconda3/envs/agno/bin/python -I exp_step4.py 3 out/step4 > out-step4.log 2>&1
