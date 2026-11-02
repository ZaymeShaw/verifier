"""兑现轴新旧对照：同一份冻结交付，只跑 fulfillment 一个框（描述 = 预设的 capability），记结论、期望、调用、用量、耗时。

样本：report/regression/llm_probe/baseline-20260830.json 的 16 条（client_search / policy_search / 营销意图）。
用法（在 verifier-integrate 的 Python 环境下）：python ab_fulfill.py <代码根目录> <variant> [--reps N]
代码根目录下要有 .env 与 .runtime/instances/<实例>/data（场景配置、资料）。
"""
import argparse, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
CASES = HERE.parents[1] / 'report/regression/llm_probe/baseline-20260830.json'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('code')
    ap.add_argument('variant')
    ap.add_argument('--reps', type=int, default=1)
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()
    code = Path(args.code).resolve()
    sys.path.insert(0, str(code))
    os.chdir(code)
    os.environ.setdefault('VERIFIER_INSTANCE_ID', 'inst-f105511930554648')
    from impl.core.project_loader import load_project
    from impl.core.capability_store import load_capability_map
    from impl.core.schema import RunTrace
    from impl.projects.llm_probe.eval_axes.runner import run_axes
    from impl.projects.llm_probe.eval_axes.types import ScenarioAxis

    spec = load_project('llm_probe')
    presets = load_capability_map('llm_probe')
    out = HERE / 'runs-ab' / f'{args.variant}.jsonl'
    out.parent.mkdir(exist_ok=True)
    done = {(r['case_id'], r['rep']) for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    lock = threading.Lock()

    def one(rep, case):
            ref = case['capability_ref']
            trace = RunTrace(trace_id=f"ab-{case['case_id']}", project_id='llm_probe', case_id=case['case_id'],
                             normalized_request={'body': case['input'], 'capability_ref': ref, 'method': 'POST', 'url': ''},
                             extracted_output={'output_text': case['output_text']})
            axis = ScenarioAxis('fulfillment', True, presets[ref]['capability'])
            start = time.monotonic()
            result = run_axes(spec, trace, [axis], scenario_id=ref, run_id=f'ab-{args.variant}-{rep}')[0].as_dict()
            output = result.get('output') or {}
            assessments = {a.get('expectation_id'): a for a in output.get('fulfillment_assessments') or []}
            row = {'case_id': case['case_id'], 'scenario': ref, 'rep': rep, 'status': result['status'],
                   'verdict': (output.get('overall_fulfillment') or {}).get('status'), 'error': result.get('error'),
                   'latency_s': round(time.monotonic() - start, 1), 'usage': result.get('usage'),
                   'expectations': [{'id': e.get('expectation_id'), 'blocking': e.get('blocking'), 'outcome': e.get('expected_outcome'),
                                     'status': (assessments.get(e.get('expectation_id')) or {}).get('status')}
                                    for e in output.get('business_expectations') or []],
                   'reasoning': output.get('reasoning_summary')}
            with lock, out.open('a') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
            print(case['case_id'], rep, row['status'], row['verdict'], row['latency_s'], flush=True)

    todo = [(rep, case) for rep in range(args.reps) for case in json.loads(CASES.read_text()) if (case['case_id'], rep) not in done]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in [pool.submit(one, rep, case) for rep, case in todo]:
            fut.result()
    print(f'wall_clock_s {round(time.monotonic() - started, 1)}', flush=True)


if __name__ == '__main__':
    main()
