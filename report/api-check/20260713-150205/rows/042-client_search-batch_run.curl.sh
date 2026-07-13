#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8021/api/batch_run' -H 'Content-Type: application/json' --data-raw '{"cases": [{"expected_intent": "", "id": "mock-agent-client_search-cdd7df11", "input": {"extra_input_params": {"pCategorys": "重疾险"}, "session_id": "session_001", "source": "insurance_search", "trace_id": "trace_001", "user_id": "default_user", "user_text": "帮我看看公司里所有买了重疾险的客户都有谁"}, "metadata": {"live_request_mapped": true, "project_id": "client_search", "schema_ok": true, "source": "mock_agent_llm"}, "scenario": "single_condition", "source": "mock_agent_llm", "status": "pending", "table_row": {"input": "帮我看看公司里所有买了重疾险的客户都有谁"}}], "concurrency": 1, "project": "client_search"}' --write-out '
__HTTP_STATUS__:%{http_code}'
