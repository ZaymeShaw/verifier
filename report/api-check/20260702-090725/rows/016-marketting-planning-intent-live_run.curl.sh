#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/live_run' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "team_portrait", "id": "mock-agent-marketting-planning-intent-228b3c9f", "input": {"query": "哎，帮我看看华东区销售团队这个季度的业绩画像呗"}, "metadata": {"ready": ["reference"], "source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}, "project": "marketting-planning-intent"}' --write-out '
__HTTP_STATUS__:%{http_code}'
