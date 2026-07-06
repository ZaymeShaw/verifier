#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/run_chain' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "", "id": "mock-agent-QA-ffa2efb1", "input": {"query": "你好，我想问一下，咱们国家的首都是哪里啊？"}, "metadata": {"ready": ["output", "reference"], "source": "mock_agent_llm"}, "scenario": "qa_gold_answer", "source": "mock_agent_llm", "status": "pending"}, "project": "QA"}' --write-out '
__HTTP_STATUS__:%{http_code}'
