#!/usr/bin/env python3
"""
Verification script for session isolation fix.

Run this after API recharge to confirm:
1. No "WARNING: trace_id was None" messages
2. Session IDs follow {project}:{trace_id}:{timestamp} format
3. No anomalous sessions like "client_search:judge"
4. Token consumption is reasonable (~15k per case, not millions)
"""

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from impl.core.judge import judge_trace
from impl.core.schema import ProjectSpec, RunTrace


def main():
    print("=" * 60)
    print("Verifying session isolation fix")
    print("=" * 60)
    print()

    spec = ProjectSpec(
        project_id="client_search",
        name="客户搜索",
        description="根据自然语言查询搜索客户",
    )

    # Load mock cases
    mock_file = ROOT / "impl/data/client_search/mock_cases.json"
    with open(mock_file, encoding="utf-8") as f:
        cases = json.load(f)[:2]

    results = []
    for i, case in enumerate(cases, 1):
        query = case["input"]["query"]
        print(f"[Case {i}] {query[:50]}...")

        trace = RunTrace(
            trace_id=str(uuid.uuid4()),
            project_id=spec.project_id,
            input=case["input"],
            normalized_request=case["input"],
            extracted_output=case.get("output", {}),
        )

        result = judge_trace(spec, trace)

        print(f"  ✓ Trace: {trace.trace_id}")
        print(f"  ✓ Verdict: {result.verdict}")
        print()

        results.append({
            "trace_id": trace.trace_id,
            "verdict": result.verdict,
        })

    # Check session file
    print("=" * 60)
    print("Session file check")
    print("=" * 60)

    session_file = ROOT / "impl/knowledge/client_search/agno_memory.json/agno_sessions.json"
    if not session_file.exists():
        print("✗ Session file not found")
        return

    with open(session_file, encoding="utf-8") as f:
        sessions = json.load(f)

    print(f"Total sessions: {len(sessions)}")
    print()

    # Verify session format
    anomalous = []
    for session_id, session_data in sessions.items():
        parts = session_id.split(":")
        if len(parts) != 3:
            anomalous.append(session_id)
            print(f"✗ Anomalous session ID: {session_id}")
        elif parts[1] in ["judge", "attribute"]:
            anomalous.append(session_id)
            print(f"✗ Old-style session ID: {session_id}")
        else:
            runs = len(session_data.get("runs", []))
            print(f"✓ Valid session: {session_id[:60]}... ({runs} runs)")

    print()
    if anomalous:
        print(f"✗ Found {len(anomalous)} anomalous sessions")
    else:
        print("✓ All sessions follow correct format")

    print()
    print("=" * 60)
    print("Next: Run check1 with all 4 projects to verify full system")
    print("=" * 60)


if __name__ == "__main__":
    main()
