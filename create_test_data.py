#!/usr/bin/env python3
"""
直接测试 attribute agent 是否调用 search_source_file tool
"""
import json
import sys
from pathlib import Path

# 模拟一个简单的 trace 和 judge result
trace_data = {
    "trace_id": "test-tool-call",
    "project_id": "marketting-planning-intent",
    "input": {
        "case_id": "test-1",
        "query": "我想优化健康险和年金险的产品组合",
        "reference": {"intent": "nbev_planning"}
    },
    "normalized_request": {"query": "我想优化健康险和年金险的产品组合"},
    "extracted_output": {
        "intent": "other",
        "confidence": 0.5,
        "raw_intent": "4001"
    },
    "project_fields": {
        "reference": {"intent": "nbev_planning"},
        "expected_intent": "nbev_planning"
    },
    "execution_trace": [
        {"stage": "request_normalization", "status": "ok"},
        {"stage": "intent_api_call", "status": "ok"},
        {"stage": "label_mapping", "status": "failed", "evidence": {"intent": "other"}}
    ],
    "status": "completed"
}

judge_data = {
    "trace_id": "test-tool-call",
    "project_id": "marketting-planning-intent",
    "verdict": "incorrect",
    "score": 0,
    "confidence": 1.0,
    "judge_method": "test",
    "business_expectations": [
        {
            "expectation_id": "exp1",
            "user_goal": "识别为 nbev_planning",
            "required_outcome": "intent=nbev_planning",
            "fulfillment_status": "not_fulfilled",
            "blocking": True
        }
    ],
    "overall_fulfillment": {"status": "not_fulfilled"},
    "missing": [{"requirement": "intent", "expected": "nbev_planning", "actual": "other"}]
}

# Save to files
Path("tmp").mkdir(exist_ok=True)
with open("tmp/test_trace.json", "w") as f:
    json.dump(trace_data, f, indent=2, ensure_ascii=False)
with open("tmp/test_judge.json", "w") as f:
    json.dump(judge_data, f, indent=2, ensure_ascii=False)

print("✅ Test data created:")
print("  - tmp/test_trace.json")
print("  - tmp/test_judge.json")
print()
print("Now run:")
print("  python3 test_attribute_tool_call.py")
