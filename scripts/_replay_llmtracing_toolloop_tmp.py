"""已授权：一个完整冻结 llmtracing case，一次ToolLoop六轴+现有主裁决；不调用业务。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'report/llmtracing-calibration-draft/toolloop-replay-1'
SOURCE = ROOT / 'report/business-trace-provider-ab-20261001/traces.json'


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def child():
    from impl.core import llm_client
    from impl.core.project_loader import load_project
    from impl.core.schema import normalize_run_trace, to_dict
    from impl.projects.llm_probe.judge import LlmProbeJudge

    # 只在本次独立worker里记录，生产方法保持原样执行。不替换模型/工具结果，不做额外重试。
    track = llm_client._track_context
    step = llm_client.LlmClient.complete_step
    counter = 0

    def observe_context(client, request, result, trace_id, token_metrics, elapsed_ms, error, **kwargs):
        nonlocal counter
        counter += 1
        record = {'trace_id': trace_id, 'request': request, 'metrics': token_metrics,
                  'elapsed_ms': elapsed_ms, 'error': error, 'runtime': kwargs.get('runtime'),
                  'response_messages': llm_client._extract_messages(result) if result is not None else []}
        write_json(OUT / f'call-{counter:03}.json', record)
        return track(client, request, result, trace_id, token_metrics, elapsed_ms, error, **kwargs)

    def observe_step(client, messages, functions, **kwargs):
        write_json(OUT / 'latest-step-input.json', {'stage': kwargs.get('stage'), 'messages': messages,
                   'tools': [{'name': f.name, 'description': f.description, 'parameters': f.parameters} for f in functions]})
        return step(client, messages, functions, **kwargs)

    llm_client._track_context = observe_context
    llm_client.LlmClient.complete_step = observe_step
    started = time.monotonic()
    trace = normalize_run_trace(json.loads((OUT / 'input.json').read_text()))
    try:
        judge = LlmProbeJudge(load_project('llm_probe'))
        result = judge.judge_trace(trace)
        body = {'judge': to_dict(result), 'axes': getattr(trace, '_pending_process_report', None)}
    except Exception:
        body = {'error': traceback.format_exc(), 'axes': getattr(trace, '_pending_process_report', None)}
    body.update(elapsed_seconds=round(time.monotonic() - started, 1), recorded_model_calls=counter)
    write_json(OUT / 'result.json', body)
    print('finished', body['elapsed_seconds'], counter, 'error' in body, flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--child']:
        child()
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        write_json(OUT / 'input.json', json.loads(SOURCE.read_text())['llmtracing'])
        from impl.projects.llm_probe.process_loop.llmtracing_report import FILES
        paths = list(FILES) + ['impl/projects/llm_probe/eval_axes/__init__.py', 'impl/projects/llm_probe/judge.py',
                              'impl/core/llm_client.py', 'scripts/_replay_llmtracing_toolloop_tmp.py']
        paths += [str(p.relative_to(ROOT)) for p in (ROOT / 'impl/projects/llm_probe/eval_axes/adapters').glob('*.py')]
        hashes = {}
        for name in dict.fromkeys(paths):
            raw = (ROOT / name).read_bytes()
            hashes[name] = hashlib.sha256(raw).hexdigest()
            dest = OUT / 'source' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        write_json(OUT / 'manifest.json', {'source': str(SOURCE.relative_to(ROOT)), 'reps': 1, 'workers': 1,
                   'input_sha256': hashlib.sha256((OUT / 'input.json').read_bytes()).hexdigest(),
                   'loop_tool_limit': 40, 'loop_deadline_s': 1200, 'whole_process_timeout_s': 2400,
                   'files': hashes, 'scope': 'frozen judge-only; no business or gateway log collection'})
        with (OUT / 'run.log').open('w') as log:
            try:
                proc = subprocess.run([sys.executable, __file__, '--child'], cwd=ROOT, stdout=log,
                                      stderr=subprocess.STDOUT, timeout=2400)
                status = {'returncode': proc.returncode}
            except subprocess.TimeoutExpired:
                status = {'failure_class': 'timeout', 'seconds': 2400}
        write_json(OUT / 'process.json', status)
