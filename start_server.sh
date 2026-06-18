#!/bin/bash
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-$LLM_API_KEY}"
/Users/xiaozijian/miniconda3/envs/agno/bin/python -m impl.server --port 8020
