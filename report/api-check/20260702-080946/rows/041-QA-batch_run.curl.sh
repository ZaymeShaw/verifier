#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8020/api/batch_run' -H 'Content-Type: application/json' --data-raw '{"cases": [{"expected_intent": "", "id": "mock-agent-QA-1018356e", "input": {"query": "你好，请问怎么更改我的收货地址？"}, "metadata": {"ready": ["output", "reference"], "source": "mock_agent_llm"}, "scenario": "qa_gold_answer", "source": "mock_agent_llm", "status": "pending"}], "concurrency": 1, "project": "QA"}' --write-out '
__HTTP_STATUS__:%{http_code}'
