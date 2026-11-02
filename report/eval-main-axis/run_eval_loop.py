"""主轴三态评测（axis loop 路线，llm_probe_loop）：与 run_eval.py 同一批样本、同一份 gold、同一判分。

一个 case 跑一次 axis loop（需求 → 说法 → 真实性 → 兑现 → 主轴结论），取兑现的整体状态和 gold 对答案。
代码取本目录所在仓库（EVAL_CODE 可改）；数据取 VERIFIER_INSTANCE_ID 实例里的 llm_probe_loop。
用法：python run_eval_loop.py <variant> [--reps N] [--split dev|holdout|all] [--ids ...] [--workers N]
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

HERE = Path(__file__).parent
CODE = Path(os.environ.get('EVAL_CODE') or HERE.parents[1])
sys.path.insert(0, str(CODE))
os.environ.setdefault('VERIFIER_INSTANCE_ID', 'inst-f105511930554648')

from impl.core.project_loader import load_project  # noqa: E402
from impl.server.service import normalize_run_trace  # noqa: E402
from impl.projects.llm_probe_loop.eval_axes import build_report  # noqa: E402

PROJECT = 'llm_probe_loop'
CASE_SECONDS = 1800
SPEC = load_project(PROJECT)
LOCK = threading.Lock()


def run_case(case, rep, variant):
    trace = normalize_run_trace(case['trace'])
    report = build_report(SPEC, trace, run_id=f'eval-{variant}-{rep}-{case["id"]}', scenario_id=case['scenario'])
    results = {r['type_id']: r for r in report['results']}
    ff = results.get('fulfillment') or {}
    if ff.get('status') != 'succeeded':
        raise RuntimeError(f"fulfillment {ff.get('status')}: {str(ff.get('error'))[:300]}")
    out = ff.get('output') or {}
    truth = (results.get('truthfulness') or {}).get('output') or {}
    loop = report.get('loop') or {}
    return {'pred': (out.get('overall_fulfillment') or {}).get('status'),
            'main_verdict': report.get('main_verdict'),
            'reasoning': out.get('reasoning_summary') or '',
            'expectations': [{k: e.get(k) for k in ('expectation_id', 'expected_outcome', 'blocking')} for e in out.get('business_expectations') or []],
            'assessments': [{k: a.get(k) for k in ('expectation_id', 'status', 'claim_refs', 'downstream_impact')} for a in out.get('fulfillment_assessments') or []],
            'claims': [{k: c.get(k) for k in ('claim_id', 'text', 'verdict', 'gap', 'qualifies', 'reason')} for c in truth.get('claims') or []],
            'axis_status': {k: r['status'] for k, r in results.items()},
            'axis_errors': {k: str(r.get('error') or '')[:500] for k, r in results.items() if r.get('error')},
            'usage': {'loop': {**(loop.get('usage') or {}), 'llm_calls': loop.get('llm_calls', 0), 'tool_calls': loop.get('tool_calls', 0),
                               'seconds': loop.get('seconds'), 'archived': loop.get('archived', 0)}},
            'loop': {k: loop.get(k) for k in ('status', 'reason', 'states', 'events')}}


def grade(gold, pred):
    return {'hit': float(pred == gold),
            'false_pass': float(pred == 'fulfilled' and gold != 'fulfilled'),
            'false_kill': float(gold == 'fulfilled' and pred != 'fulfilled')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('variant')
    ap.add_argument('--reps', type=int, default=1)
    ap.add_argument('--split', default='all', choices=('dev', 'holdout', 'all'))
    ap.add_argument('--ids', nargs='*', help='只跑这些样本（试跑用）')
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()
    out = HERE / 'runs' / args.variant
    out.mkdir(parents=True, exist_ok=True)
    gold = json.loads((HERE / 'gold.json').read_text())
    cases = [json.loads(f.read_text()) for f in sorted((HERE / 'cases').glob('*.json'))]
    cases = [c for c in cases if args.split in ('all', c['split']) and (not args.ids or c['id'] in args.ids)]
    results_path, errors_path = out / 'results.jsonl', out / 'errors.jsonl'
    done = set()
    if results_path.exists():
        done = {(r['prompt_id'], r['rep']) for r in map(json.loads, results_path.read_text().splitlines())}
    todo = [(c, rep) for c in cases for rep in range(args.reps) if (c['id'], rep) not in done]
    print(f'{len(todo)} to run ({len(done)} done)', flush=True)

    def task(case, rep):
        start = time.monotonic()
        row = {'prompt_id': case['id'], 'rep': rep, 'split': case['split'], 'tags': [case['source']], 'variant': args.variant}
        try:
            with ThreadPoolExecutor(max_workers=1) as one:
                run = one.submit(run_case, case, rep, args.variant).result(timeout=CASE_SECONDS)
        except FutureTimeout:
            err = {**row, 'failure_class': 'timeout', 'error': f'>{CASE_SECONDS}s'}
        except Exception as exc:
            err = {**row, 'failure_class': 'harness_or_axis_error', 'error': repr(exc)[:500]}
        else:
            g = gold[case['id']]['gold']
            row.update({'status': 'ok', 'gold': g, 'grade': grade(g, run['pred']), 'latency_s': round(time.monotonic() - start, 1),
                        'llm_calls': run['usage']['loop']['llm_calls'], 'tool_calls': run['usage']['loop']['tool_calls'], **run})
            with LOCK, results_path.open('a') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
            print(case['id'], rep, run['pred'], 'gold=' + g, 'OK' if row['grade']['hit'] else 'MISS', flush=True)
            return
        with LOCK, errors_path.open('a') as f:
            f.write(json.dumps(err, ensure_ascii=False) + '\n')
        print(case['id'], rep, 'ERROR', err['error'][:200], flush=True)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in [pool.submit(task, c, r) for c, r in todo]:
            fut.result()
    print(f'done wall_clock_s {round(time.monotonic() - started, 1)}', flush=True)


if __name__ == '__main__':
    main()
