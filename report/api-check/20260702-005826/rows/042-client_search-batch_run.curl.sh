#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/batch_run' -H 'Content-Type: application/json' --data-raw '{"cases": [{"expected_intent": "", "id": "mock-agent-client_search-a55d78af", "input": {"query": "帮我查一下北京地区的客户"}, "metadata": {"source": "mock_agent_llm"}, "scenario": "single_condition", "source": "mock_agent_llm", "status": "pending"}], "concurrency": 1, "project": "client_search"}' --write-out '
__HTTP_STATUS__:%{http_code}'
