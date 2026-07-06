#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/run_chain' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "customer_portrait", "id": "mock-agent-marketting-planning-intent-7b353b0e", "input": {"query": "帮我看看最近半年来我们主要客户是哪些人群？"}, "metadata": {"ready": ["reference"], "source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}, "project": "marketting-planning-intent"}' --write-out '
__HTTP_STATUS__:%{http_code}'
