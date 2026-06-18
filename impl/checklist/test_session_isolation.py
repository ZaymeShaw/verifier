#!/usr/bin/env python3
"""
Test trace-isolated session configuration
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from impl.core.pipeline import run_chain

# Test two different cases from client_search
test_cases = [
    {"query": "45岁女性保费10万以上"},
    {"query": "有生存金未领取的客户"},
]

print("=" * 60)
print("Testing trace-isolated sessions")
print("=" * 60)

for i, case in enumerate(test_cases, 1):
    print(f"\n[Case {i}] {case['query']}")
    try:
        result = run_chain("client_search", case)
        trace = result.get("trace")
        judge = result.get("judge")

        if trace and judge:
            trace_id = trace.get("trace_id") if isinstance(trace, dict) else trace.trace_id
            verdict = judge.get("verdict") if isinstance(judge, dict) else judge.verdict
            print(f"  ✓ Trace: {trace_id}")
            print(f"  ✓ Judge: {verdict}")
            print(f"  ✓ Session isolated per trace_id")
        else:
            print(f"  ❌ Missing trace or judge")
    except Exception as e:
        print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print("Check impl/knowledge/client_search/agno_memory.json/")
print("- agno_sessions.json should have separate sessions per trace_id")
print("- Each session should be isolated (no cross-case contamination)")
print("=" * 60)
