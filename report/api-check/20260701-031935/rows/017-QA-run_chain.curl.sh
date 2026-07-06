#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8021/api/run_chain' -H 'Content-Type: application/json' --data-raw '{"input": {"expected_intent": "", "id": "qa-gold-exact-1", "input": {"question": "什么是保险合同犹豫期？"}, "metadata": {"category": "insurance_contract", "expected_error_type": "none", "previous_output": {"actual_answer": "犹豫期是投保人收到保险合同后，在合同约定期限内可以申请解除合同，保险公司通常退还已交保费的期间。"}, "quality_dimension": "correctness"}, "reference": {"golden_answer": "犹豫期是投保人收到保险合同后，在合同约定期限内可以申请解除合同，保险公司通常退还已交保费的期间。"}, "scenario": "qa_gold_answer", "source": "data_mock_seed", "status": "pending"}, "project": "QA"}' --write-out '
__HTTP_STATUS__:%{http_code}'
