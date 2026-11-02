"""复用真实 eval_axes.build_report；冻结输入的过程范围评测。每条一次，失败不自动重跑。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = Path(__file__).resolve().parent
INPUTS = BASE / 'frozen-inputs'
OUT = BASE / 'process-baseline-v0'
CASES = ('B', 'C', 'D', 'E')


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def check_frozen():
    source = json.loads((BASE / 'toolloop-replay-1/manifest.json').read_text())['files']
    changed = [f for f, digest in source.items()
               if not (ROOT / f).is_file() or hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != digest]
    if changed:
        raise RuntimeError('被测源码已变化，停止评测：' + ', '.join(changed))
    inputs = json.loads((INPUTS / 'manifest.json').read_text())
    for key in CASES:
        row = inputs['entries'][key]
        if hashlib.sha256((INPUTS / row['trace_file']).read_bytes()).hexdigest() != row['trace_sha256']:
            raise RuntimeError('冻结输入已变化：' + key)
    from impl.projects.llm_probe.process_loop.evaluation import criteria_for
    criteria, entry = criteria_for('llm_probe', 'insurance-llmtracing')
    expected = json.loads((INPUTS / 'evaluation-contract.json').read_text())
    if criteria != expected['criteria'] or (entry.get('process_obligations') or []) != expected['process_obligations']:
        raise RuntimeError('被测业务契约已变化，停止评测')
    return source, inputs


def child(label):
    from impl.core import llm_client
    from impl.core.project_loader import load_project
    from impl.core.schema import normalize_run_trace
    from impl.projects.llm_probe.eval_axes import build_report
    from impl.projects.llm_probe.process_loop import llmtracing as instance

    target = OUT / label
    started = time.monotonic()
    count, requested_steps = 0, 0
    original_track, original_step, original_client = llm_client._track_context, llm_client.LlmClient.complete_step, instance.axis_llm

    def track(client, request, result, trace_id, token_metrics, elapsed_ms, error, **kwargs):
        nonlocal count
        count += 1
        dump(target / f'call-{count:03}.json', {
            'trace_id': trace_id, 'request': request, 'metrics': token_metrics, 'elapsed_ms': elapsed_ms,
            'error': error, 'runtime': kwargs.get('runtime'),
            'response_messages': llm_client._extract_messages(result) if result is not None else []})
        return original_track(client, request, result, trace_id, token_metrics, elapsed_ms, error, **kwargs)

    def step(client, messages, functions, **kwargs):
        nonlocal requested_steps
        requested_steps += 1
        dump(target / f'step-{requested_steps:03}-input.json', {'stage': kwargs.get('stage'), 'messages': messages,
             'tools': [{'name': f.name, 'description': f.description, 'parameters': f.parameters} for f in functions]})
        return original_step(client, messages, functions, **kwargs)

    def client_factory(*args, **kwargs):
        client = original_client(*args, **kwargs)
        # 只记录非凭据设置，不保存 base_url/api_key 或整个配置对象。
        dump(target / 'effective-settings.json', {k: getattr(client, k, None) for k in (
            'model', 'reasoning_effort', 'temperature', 'stream', 'request_timeout_seconds')})
        return client

    llm_client._track_context = track
    llm_client.LlmClient.complete_step = step
    instance.axis_llm = client_factory
    try:
        check_frozen()
        trace = normalize_run_trace(json.loads((INPUTS / f'{label}.trace.json').read_text()))
        report = build_report(load_project('llm_probe'), trace, run_id=f'calibration-v0-{label}')
        check_frozen()
        body = {'case': label, 'scope': 'process_only', 'report': report,
                'execution_status': 'succeeded' if all(r['status'] == 'succeeded' for r in report['results']) else 'failed'}
    except Exception:
        body = {'case': label, 'execution_status': 'failed', 'error': traceback.format_exc()}
    body.update(elapsed_seconds=round(time.monotonic() - started, 1), requested_steps=requested_steps,
                recorded_model_calls=count)
    dump(target / 'result.json', body)
    print(label, body['execution_status'], body['elapsed_seconds'], requested_steps, flush=True)


def run(label):
    target = OUT / label
    target.mkdir()
    started = time.monotonic()
    with (target / 'run.log').open('w') as log:
        try:
            p = subprocess.run([sys.executable, __file__, '--child', label], cwd=ROOT,
                               stdout=log, stderr=subprocess.STDOUT, timeout=1200)
            status = {'returncode': p.returncode}
        except subprocess.TimeoutExpired:
            status = {'failure_class': 'timeout', 'timeout_seconds': 1200,
                      'note': 'worker terminated; upstream request may continue; no automatic retry'}
    status.update(case=label, elapsed_seconds=round(time.monotonic() - started, 1))
    dump(target / 'process.json', status)
    print(label, status, flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child' and sys.argv[2] in CASES:
        child(sys.argv[2])
    elif sys.argv[1:] == ['--run']:
        sources, inputs = check_frozen()
        OUT.mkdir(exist_ok=False)
        dump(OUT / 'manifest.json', {'cases': list(CASES), 'reps': 1, 'workers': 2,
             'case_wall_clock_limit_s': 1200, 'loop_tool_limit': 40, 'main_judge': False,
             'business_calls': False, 'scope': 'process_only', 'source_hashes': sources,
             'input_manifest_sha256': hashlib.sha256((INPUTS / 'manifest.json').read_bytes()).hexdigest(),
             'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'grading': 'manual provisional rubric; not tool accepted flags'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, CASES))
    else:
        check_frozen()
        print('Frozen inputs/source/contracts checked. --run executes the approved four cases once.')
