#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/run_chain' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "", "id": "mock-agent-marketting-planning-82f2111f", "input": {"query": "帮我看一下我们上个月的营销活动效果怎么样，有什么地方可以改进吗？"}, "metadata": {"source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}, "project": "marketting-planning"}' --write-out '
__HTTP_STATUS__:%{http_code}'
