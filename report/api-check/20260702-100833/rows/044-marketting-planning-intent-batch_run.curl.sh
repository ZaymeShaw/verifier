#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/batch_run' -H 'Content-Type: application/json' --data-raw '{"cases": [{"expected_intent": "customer_portrait", "id": "mock-agent-marketting-planning-intent-2641c607", "input": {"query": "我想了解一下我们现有的客户都是什么样的，有没有什么共同点？"}, "metadata": {"ready": ["reference"], "source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}], "concurrency": 1, "project": "marketting-planning-intent"}' --write-out '
__HTTP_STATUS__:%{http_code}'
