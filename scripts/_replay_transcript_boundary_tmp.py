"""两次已授权的冻结 trace 评判重放；不调用业务，不读取在线网关日志。"""
import hashlib
import json
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'report/llmtracing-calibration-draft/boundary-replay'
SOURCE = ROOT / 'report/business-trace-provider-ab-20261001/traces.json'


def child(rep):
    from impl.core.project_loader import load_project
    from impl.core.schema import normalize_run_trace, to_dict
    from impl.core.llm_client import LlmClient
    from impl.projects.llm_probe.judge import LlmProbeJudge

    # 记录真实入口产生的评判输入和客户端返回的用量，不另造模型调用。
    original = LlmClient.complete_json
    calls = []

    def observed(self, *args, **kwargs):
        row = {'stage': kwargs.get('stage', ''), 'system': args[0] if args else kwargs.get('system'),
               'user': args[1] if len(args) > 1 else kwargs.get('user')}
        started = time.monotonic()
        try:
            payload = original(self, *args, **kwargs)
            if isinstance(payload, dict):
                row['metrics'] = payload.get('metrics')
            return payload
        except Exception as exc:
            row['error_type'] = type(exc).__name__
            raise
        finally:
            row['elapsed_seconds'] = round(time.monotonic() - started, 3)
            calls.append(row)
            (OUT / f'r{rep}-calls.json').write_text(json.dumps(calls, ensure_ascii=False, indent=2, default=str))

    LlmClient.complete_json = observed
    started = time.monotonic()
    trace = normalize_run_trace(json.loads((OUT / 'input.json').read_text()))
    try:
        judge = LlmProbeJudge(load_project('llm_probe'))
        result = judge.judge_trace(trace)
        body = {'rep': rep, 'judge': to_dict(result), 'axes': getattr(trace, '_pending_process_report', None)}
    except Exception:
        body = {'rep': rep, 'error': traceback.format_exc()}
    body['elapsed_seconds'] = round(time.monotonic() - started, 1)
    (OUT / f'r{rep}.json').write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str))
    print('completed', rep, body['elapsed_seconds'], 'error' in body, flush=True)


def run(rep):
    # 不自动补跑失败；用户批准的是每个 rep 一次整链运行。
    with (OUT / f'r{rep}.log').open('w') as log:
        try:
            result = subprocess.run([sys.executable, __file__, '--child', str(rep)], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=1800)
            status = {'rep': rep, 'returncode': result.returncode}
        except subprocess.TimeoutExpired:
            status = {'rep': rep, 'failure_class': 'timeout', 'wall_clock_limit_s': 1800}
    (OUT / f'r{rep}-process.json').write_text(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        child(int(sys.argv[2]))
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        data = json.loads(SOURCE.read_text())['llmtracing']
        (OUT / 'input.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))
        files = ['impl/projects/llm_probe/eval_axes/adapters/transcript_axes.py',
                 'impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py',
                 'impl/projects/llm_probe/eval_axes/adapters/process_common.py',
                 'impl/projects/llm_probe/judge.py']
        hashes = {}
        for f in files:
            raw = (ROOT / f).read_bytes()
            hashes[f] = hashlib.sha256(raw).hexdigest()
            (OUT / Path(f).name).write_bytes(raw)
        (OUT / 'manifest.json').write_text(json.dumps({'source': str(SOURCE.relative_to(ROOT)),
            'input_sha256': hashlib.sha256((OUT / 'input.json').read_bytes()).hexdigest(),
            'reps': 2, 'max_workers': 2, 'per_rep_timeout_s': 1800, 'source_hashes': hashes,
            'scope': 'judge-only; no business calls; existing real HTTP trace'}, ensure_ascii=False, indent=2))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, (1, 2)))
