"""第二期对照基线：llm_probe 工作流路线在同 22 条 trace 存档上重判，记主判结论与六轴轴级值（spec/implementation/axis_loop.md §9 S8）。
改自 report/eval-main-axis/verify33/run_new.py：加记六轴 verdict、组成与问题；只跑 agno / langfuse。
agno / langfuse 走过程路线（需求轴 + 六轴 + 主判），mcp 走无 trace 主轴（兑现自推期望 + 知识查证 + 核事实）。
用法（verifier-integrate 的 Python 环境）：python run_new.py <variant> [--workers N]
"""
import argparse, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
SAMPLES = HERE.parents[1] / 'report/eval-main-axis/verify33/old.jsonl'
PROCESS = ('intent_understanding', 'planning_routing', 'tool_execution', 'context_memory', 'knowledge_data', 'model_capability')
CODE = Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier-integrate')
sys.path.insert(0, str(CODE))
os.chdir(CODE)
os.environ.setdefault('VERIFIER_INSTANCE_ID', 'inst-f105511930554648')

from impl.core.project_loader import load_project  # noqa: E402
from impl.core import pipeline  # noqa: E402
from impl.server.service import normalize_run_trace  # noqa: E402

LOCK = threading.Lock()


def run_one(row, spec):
    trace = normalize_run_trace(row['trace'])
    start = time.monotonic()
    result = pipeline.judge('llm_probe', trace)
    elapsed = round(time.monotonic() - start, 1)
    report = getattr(trace, '_pending_process_report', None) or {}
    res = report.get('results') or []
    by = {r['type_id']: r for r in res}
    ff = (by.get('fulfillment') or {}).get('output') or {}
    truth = (by.get('truthfulness') or {}).get('output') or {}
    exp = (by.get('expectations') or {}).get('output') or {}
    return {
        'id': row['id'], 'scenario': row['scenario'], 'latency_s': elapsed,
        'judge_status': (result.overall_fulfillment or {}).get('status'),
        'main_verdict': report.get('main_verdict'),
        'reason': result.reasoning_summary,
        'axis_status': {r['type_id']: r['status'] for r in res},
        'axis_errors': {r['type_id']: str(r.get('error') or '')[:400] for r in res if r.get('error')},
        'axis_calls': sum((r.get('usage') or {}).get('llm_calls', 0) for r in res),
        'axis_elapsed_ms': {r['type_id']: (r.get('usage') or {}).get('elapsed_ms') for r in res},
        'expectations': exp.get('business_expectations') or exp.get('expectations') or ff.get('business_expectations') or result.business_expectations,
        'assessments': ff.get('fulfillment_assessments') or result.fulfillment_assessments,
        'placements': ((by.get('carryability') or {}).get('output') or {}).get('placements'),
        'six': {a: ((by.get(a) or {}).get('output') or {}).get('assessment', {}).get('verdict') for a in PROCESS},
        'six_counts': {a: (((by.get(a) or {}).get('output') or {}).get('assessment', {}).get('composition') or {}).get('counts') for a in PROCESS},
        'six_issues': {a: [i.get('phenomenon') for i in ((by.get(a) or {}).get('output') or {}).get('issues') or []] for a in PROCESS},
        'claims': [{k: c.get(k) for k in ('claim_id', 'text', 'verdict', 'gap', 'qualifies', 'reason')} for c in truth.get('claims') or []],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('variant')
    ap.add_argument('--workers', type=int, default=3)
    args = ap.parse_args()
    spec = load_project('llm_probe')
    out = HERE / 'runs' / f'{args.variant}.jsonl'
    done = {json.loads(x)['id'] for x in out.read_text().splitlines()} if out.exists() else set()
    rows = [json.loads(x) for x in SAMPLES.read_text().splitlines()]
    todo = [r for r in rows if r['id'] not in done and 'mcp' not in r['scenario']]
    print(f'{len(todo)} to run ({len(done)} done)', flush=True)

    def task(row):
        try:
            rec = run_one(row, spec)
        except Exception as exc:  # 记下来、下次续跑
            print(row['id'], 'CRASH', repr(exc)[:300], flush=True)
            return
        with LOCK, out.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')
        mv = (rec['main_verdict'] or {}).get('verdict')
        print(row['id'], rec['judge_status'], mv, rec['latency_s'], flush=True)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(task, todo))
    print(f'wall_clock_s {round(time.monotonic() - started, 1)}', flush=True)


if __name__ == '__main__':
    main()
