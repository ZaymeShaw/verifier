#!/usr/bin/env python3
"""Real-time token monitoring for check1 test."""

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = ROOT / "impl/knowledge"

def get_token_stats():
    """Extract token usage from session files."""
    stats = {}

    for proj_dir in KNOWLEDGE_ROOT.iterdir():
        if not proj_dir.is_dir():
            continue

        session_file = proj_dir / "agno_memory.json/agno_sessions.json"
        if not session_file.exists():
            continue

        try:
            with open(session_file, 'r', encoding='utf-8') as f:
                sessions = json.load(f)

            # sessions can be dict or list
            if isinstance(sessions, list):
                session_list = sessions
            else:
                session_list = list(sessions.values())

            total_input = 0
            total_output = 0
            total_cache_read = 0
            run_count = 0

            for session in session_list:
                if not isinstance(session, dict):
                    continue
                runs = session.get('runs', [])
                for run in runs:
                    metrics = run.get('metrics', {})
                    if metrics:
                        total_input += metrics.get('input_tokens', 0)
                        total_output += metrics.get('output_tokens', 0)
                        total_cache_read += metrics.get('cache_read_tokens', 0)
                        run_count += 1

            if run_count > 0:
                stats[proj_dir.name] = {
                    'input_tokens': total_input,
                    'output_tokens': total_output,
                    'cache_read_tokens': total_cache_read,
                    'total_tokens': total_input + total_output,
                    'run_count': run_count,
                    'session_count': len(session_list),
                }
        except Exception as e:
            print(f"Error reading {proj_dir.name}: {e}")

    return stats


def main():
    print("Monitoring token usage in real-time...")
    print("Press Ctrl+C to stop\n")

    prev_stats = {}

    try:
        while True:
            stats = get_token_stats()

            print(f"\n{'='*60}")
            print(f"Token Usage Report - {time.strftime('%H:%M:%S')}")
            print(f"{'='*60}")

            grand_input = 0
            grand_output = 0
            grand_cache = 0
            grand_runs = 0

            for proj in ['client_search', 'QA', 'marketting-planning', 'marketting-planning-intent']:
                if proj in stats:
                    s = stats[proj]
                    inp = s['input_tokens']
                    out = s['output_tokens']
                    cache = s['cache_read_tokens']
                    total = s['total_tokens']
                    runs = s['run_count']

                    # Show delta if we have previous stats
                    delta = ""
                    if proj in prev_stats:
                        prev_runs = prev_stats[proj]['run_count']
                        if runs > prev_runs:
                            new_runs = runs - prev_runs
                            delta = f" (+{new_runs} runs)"

                    print(f"\n{proj}:")
                    print(f"  Sessions: {s['session_count']} | Runs: {runs}{delta}")
                    print(f"  Input: {inp:,} | Output: {out:,} | Cache: {cache:,}")
                    print(f"  Total: {total:,} tokens")

                    grand_input += inp
                    grand_output += out
                    grand_cache += cache
                    grand_runs += runs

            if grand_runs > 0:
                grand_total = grand_input + grand_output
                cost = grand_total / 1_000_000  # Assume $1/1M tokens

                print(f"\n{'─'*60}")
                print(f"GRAND TOTAL:")
                print(f"  Total runs: {grand_runs}")
                print(f"  Input: {grand_input:,} | Output: {grand_output:,} | Cache: {grand_cache:,}")
                print(f"  Total: {grand_total:,} tokens")
                print(f"  Estimated cost: ${cost:.2f}")
            else:
                print("\nNo token usage data yet")

            prev_stats = stats
            time.sleep(30)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")


if __name__ == '__main__':
    main()
