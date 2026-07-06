#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8021/api/batch_run' -H 'Content-Type: application/json' --data-raw '{"cases": [{"expected_intent": "", "id": "mock-agent-client_search-348911af", "input": {"extra_input_params": {"vip_level": "high"}, "session_id": "session_20260514_001", "source": "agent_portal", "trace_id": "trace_20260514_001", "user_id": "user_001", "user_text": "帮我找出所有VIP等级比较高的客户信息"}, "metadata": {"live_request_mapped": true, "schema_ok": true, "source": "mock_agent_llm"}, "scenario": "single_condition", "source": "mock_agent_llm", "status": "pending"}], "concurrency": 1, "project": "client_search"}' --write-out '
__HTTP_STATUS__:%{http_code}'
