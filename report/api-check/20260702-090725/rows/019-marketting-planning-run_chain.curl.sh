#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/run_chain' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "", "id": "mock-agent-marketting-planning-22603f89", "input": {"query": "我想制定下个季度的营销计划，但是不知道从哪里开始，你能帮我理一下思路吗？"}, "metadata": {"source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}, "project": "marketting-planning"}' --write-out '
__HTTP_STATUS__:%{http_code}'
