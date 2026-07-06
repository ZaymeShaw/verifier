#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/batch_run' -H 'Content-Type: application/json' --data-raw '{"cases": [{"expected_intent": "target_value_adjustment", "id": "mock-agent-marketting-planning-intent-74d2e20d", "input": {"query": "今年的销售目标能调低一点吗？"}, "metadata": {"ready": ["reference"], "source": "mock_agent_llm"}, "scenario": "intent_recognition", "source": "mock_agent_llm", "status": "pending"}], "concurrency": 1, "project": "marketting-planning-intent"}' --write-out '
__HTTP_STATUS__:%{http_code}'
