"""主轴重放：给定 (trace, 已存过程轴报告)，只重跑主轴；变体在本进程内替换主判函数，不改正式代码文件。
用法: python exp_main.py <variant> <reps> <sample-filter> <outdir>
"""
import json, sys, time, copy, importlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
HERE = Path(__file__).parent
ROOT = Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier')
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
import samples
from impl.core.project_loader import load_project
from impl.core.schema import to_dict
import impl.projects.llm_probe.eval_axes as eval_axes_pkg
import impl.projects.llm_probe.need_judge as need_judge
from impl.projects.llm_probe.judge import LlmProbeJudge, ProcessJudgeExecution

variant, reps, flt, outdir = sys.argv[1], int(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
outdir.mkdir(parents=True, exist_ok=True)
mod = None
if variant != 'baseline':
    mod = importlib.import_module(f'variant_{variant}')
    need_judge.run_need_judge = mod.run_need_judge

REPORTS = {}
eval_axes_pkg.build_report = lambda spec, trace: copy.deepcopy(REPORTS[trace.trace_id])

items = []
if 'target' in flt or flt == 'all':
    items += [(n, t, r, {}) for n, t, r in samples.target_samples()]
if 'ctl' in flt or flt == 'all':
    items += samples.control_samples()
spec = load_project('llm_probe')


def run(name, trace, report, meta, rep):
    path = outdir / f'{name}-r{rep}.json'
    if path.exists():
        return
    trace = copy.deepcopy(trace); trace.trace_id = f'{name}-{variant}-r{rep}'
    REPORTS[trace.trace_id] = report
    if variant != 'baseline' and hasattr(mod, 'DOSSIERS'):
        an = next(x for x in report['results'] if x['type_id'] == 'trace_analysis')
        mod.DOSSIERS[trace.trace_id] = an['output']['dossier']
    started = time.monotonic()
    try:
        judge = LlmProbeJudge(spec)
        result = ProcessJudgeExecution().run(judge, trace, '')
        payload = {'name': name, 'variant': variant, 'rep': rep, 'meta': meta, 'judge': to_dict(result)}
    except Exception as e:
        payload = {'name': name, 'variant': variant, 'rep': rep, 'meta': meta, 'error': f'{type(e).__name__}: {e}'}
    payload['elapsed'] = round(time.monotonic() - started)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(name, rep, (payload.get('judge') or {}).get('overall_fulfillment', payload.get('error')), payload['elapsed'], 's', flush=True)


with ThreadPoolExecutor(max_workers=6) as pool:
    for f in [pool.submit(run, n, t, r, m, k) for k in range(1, reps + 1) for n, t, r, m in items]:
        f.result()
print('done', flush=True)
