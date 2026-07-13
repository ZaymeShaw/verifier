#!/usr/bin/env bash
set -euo pipefail
curl -sS -X POST 'http://127.0.0.1:8021/api/cluster' -H 'Content-Type: application/json' --data-raw '{"attributes": [{"case_id": "", "evidence": ["llm_output_validation_failed", "scenario=qa_gold_answer", "question_present=True", "actual_answer_present=True", "reference_answer_present=True"], "evidence_strength": "none", "project_id": "QA", "root_cause_hypothesis": "当前证据不足以定位 QA 业务根因，需要语义 judge 或人工复核补足证据。", "summary": {"attribution_count": 0, "is_complete": false, "is_formal_attribution": false, "probe_count": 0, "summary_text": "当前证据不足以定位 QA 业务根因，需要语义 judge 或人工复核补足证据。"}, "trace_id": "QA:mock-agent-QA-87e78ff7:1783851250048"}], "project": "QA"}' --write-out '
__HTTP_STATUS__:%{http_code}'
