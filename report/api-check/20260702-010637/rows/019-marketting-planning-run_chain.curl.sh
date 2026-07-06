#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/run_chain' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "", "id": "mock-agent-marketting-planning-038580e1", "input": {"query": "我们公司打算推出新产品，需要做一个市场推广计划，你能帮我规划一下吗？", "user_intent": {"expected_path_types": ["create_plan", "product_launch"], "expected_stage": "planning"}}, "metadata": {"source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}, "project": "marketting-planning"}' --write-out '
__HTTP_STATUS__:%{http_code}'
