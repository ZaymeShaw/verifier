#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/run_chain' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "customer_portrait", "id": "mock-agent-marketting-planning-intent-7be05816", "input": {"query": "最近来的新客户好像都挺年轻的，你能帮我具体看看他们的年龄分布吗？"}, "metadata": {"ready": ["reference"], "source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}, "project": "marketting-planning-intent"}' --write-out '
__HTTP_STATUS__:%{http_code}'
