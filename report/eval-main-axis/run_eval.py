"""主轴三态评测：对 cases/ 每条样本跑评测链路（知识查证 → 真实性 → 兑现），把主轴结论和 gold.json 对答案。

正式代码取 verifier-integrate（与 main 同步），不打补丁。每完成一条就写一行，按 (case, rep) 续跑；
链路崩溃或超时记进 errors.jsonl，不占结果行、下次重跑。
用法（在 verifier-integrate 的 Python 环境下）：python run_eval.py <variant> [--reps N] [--split dev|holdout|all]
"""
import argparse, json, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

HERE = Path(__file__).parent
import os  # noqa: E402
# 跑哪份代码：默认 verifier-integrate；新旧对照时用 EVAL_CODE 指到旧代码的隔离副本。
CODE = Path(os.environ.get('EVAL_CODE') or '/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier-integrate')
sys.path.insert(0, str(CODE))
os.environ.setdefault('VERIFIER_INSTANCE_ID', 'inst-f105511930554648')

from impl.core.project_loader import load_project  # noqa: E402
from impl.server.service import normalize_run_trace  # noqa: E402
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes  # noqa: E402
from impl.projects.llm_probe.eval_axes.runner import run_axes  # noqa: E402
from impl.projects.llm_probe.eval_axes.main_verdict import main_verdict  # noqa: E402

CHAIN = ('expectations', 'knowledge_evidence', 'truthfulness', 'fulfillment')
CASE_SECONDS = 1500  # 单条墙钟上限：三轴各自 600 s 上限之外再兜一层
SPEC = load_project('llm_probe')
LOCK = threading.Lock()


def run_case(case, rep, variant):
    axes, _ = load_scenario_axes('llm_probe', case['scenario'])
    chosen = [a for a in axes if a.type_id in CHAIN]
    ran = [r.as_dict() for r in run_axes(SPEC, normalize_run_trace(case['trace']), chosen,
                                         scenario_id=case['scenario'], run_id=f'eval-{variant}-{rep}')]
    results = {r['type_id']: r for r in ran}
    ff = results.get('fulfillment') or {}
    if ff.get('status') != 'succeeded':
        raise RuntimeError(f"fulfillment {ff.get('status')}: {str(ff.get('error'))[:300]}")
    out = ff.get('output') or {}
    truth = (results.get('truthfulness') or {}).get('output') or {}
    return {'pred': (out.get('overall_fulfillment') or {}).get('status'),
            'main_verdict': main_verdict(ran),
            'reasoning': out.get('reasoning_summary') or '',
            'expectations': [{k: e.get(k) for k in ('expectation_id', 'expected_outcome', 'blocking')} for e in out.get('business_expectations') or []],
            'assessments': [{k: a.get(k) for k in ('expectation_id', 'status', 'claim_refs', 'downstream_impact')} for a in out.get('fulfillment_assessments') or []],
            'claims': [{k: c.get(k) for k in ('claim_id', 'text', 'verdict', 'gap', 'qualifies', 'reason')} for c in truth.get('claims') or []],
            'axis_status': {k: r['status'] for k, r in results.items()},
            'axis_errors': {k: str(r.get('error') or '')[:500] for k, r in results.items() if r.get('error')},
            'usage': {k: r['usage'] for k, r in results.items()}}


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
            with ThreadPoolExecutor(max_workers=1) as one:  # 墙钟上限：超时只回收名额，后台调用可能仍在跑
                run = one.submit(run_case, case, rep, args.variant).result(timeout=CASE_SECONDS)
        except FutureTimeout:
            err = {**row, 'failure_class': 'timeout', 'error': f'>{CASE_SECONDS}s'}
        except Exception as exc:
            err = {**row, 'failure_class': 'harness_or_axis_error', 'error': repr(exc)[:500]}
        else:
            g = gold[case['id']]['gold']
            row.update({'status': 'ok', 'gold': g, 'grade': grade(g, run['pred']), 'latency_s': round(time.monotonic() - start, 1),
                        'llm_calls': sum((u or {}).get('llm_calls', 0) for u in run['usage'].values()),
                        'tool_calls': sum((u or {}).get('tool_calls', 0) for u in run['usage'].values()), **run})
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
