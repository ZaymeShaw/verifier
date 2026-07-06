#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/live_run' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "customer_portrait", "id": "mock-agent-marketting-planning-intent-99e095af", "input": {"query": "帮我分析一下，过去半年成交的客户里，哪些行业的占比最高？"}, "metadata": {"ready": ["reference"], "source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}, "project": "marketting-planning-intent"}' --write-out '
__HTTP_STATUS__:%{http_code}'
