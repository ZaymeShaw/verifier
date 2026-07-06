#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/run_chain' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "", "id": "mock-agent-client_search-f45a2db2", "input": {"query": "帮我查一下北京地区的客户有哪些？"}, "metadata": {"source": "mock_agent_llm"}, "scenario": "single_condition", "source": "mock_agent_llm", "status": "pending"}, "project": "client_search"}' --write-out '
__HTTP_STATUS__:%{http_code}'
