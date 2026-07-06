#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/batch_run' -H 'Content-Type: application/json' --data-raw '{"cases": [{"expected_intent": "", "id": "mock-agent-client_search-fea7185c", "input": {"query": "帮我找一下所有北京的客户"}, "metadata": {"source": "mock_agent_llm"}, "scenario": "single_condition", "source": "mock_agent_llm", "status": "pending"}], "concurrency": 1, "project": "client_search"}' --write-out '
__HTTP_STATUS__:%{http_code}'
