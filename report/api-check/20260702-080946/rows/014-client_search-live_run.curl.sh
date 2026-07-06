#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/live_run' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "", "id": "mock-agent-client_search-7ad5d20e", "input": {"query": "帮我查一下客户张三的详细资料"}, "metadata": {"source": "mock_agent_llm"}, "scenario": "single_condition", "source": "mock_agent_llm", "status": "pending"}, "project": "client_search"}' --write-out '
__HTTP_STATUS__:%{http_code}'
