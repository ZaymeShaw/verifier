#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8021/api/batch_run' -H 'Content-Type: application/json' --data-raw '{"cases": [{"expected_intent": "", "id": "mock-agent-client_search-b4a575aa", "input": {"extra_input_params": {"pCategorys": ["年金险"]}, "session_id": "session-12345", "source": "web", "trace_id": "trace-12345", "user_id": "user123", "user_text": "帮我查一下所有买过年金险的客户"}, "metadata": {"live_request_mapped": true, "schema_ok": true, "source": "mock_agent_llm"}, "scenario": "single_condition", "source": "mock_agent_llm", "status": "pending"}], "concurrency": 1, "project": "client_search"}' --write-out '
__HTTP_STATUS__:%{http_code}'
