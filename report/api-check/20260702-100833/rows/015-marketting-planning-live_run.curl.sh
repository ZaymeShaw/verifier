#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/live_run' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "", "id": "mock-agent-marketting-planning-9e876377", "input": {"query": "哎，我们公司下个月要搞个促销，你帮我弄个营销计划呗？"}, "metadata": {"source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}, "project": "marketting-planning"}' --write-out '
__HTTP_STATUS__:%{http_code}'
