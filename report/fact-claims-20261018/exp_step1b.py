"""第 1 步重做：说法 = 主张 + 原文片段（修订版方案 §2 第 1 步）。叠在第 2 步（回执）之上，只多改提取这一处。
对照基线：第 2 步 out/step2/*-r0.json（旧提取 + 回执）；提取次数对照 out/step1-extract-old。
用法：python exp_step1b.py <extract|chain> <reps> <outdir>
"""
import json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import patches
from impl.core.project_loader import load_project
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.runner import run_axes
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
import impl.projects.llm_probe.knowledge_loop.extract as ex

MODE, REPS, OUT = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3]); OUT.mkdir(parents=True, exist_ok=True)
_local = threading.local()
patches.apply_step2()
patches.apply_claims_extraction(counter=lambda: _local.__dict__.setdefault('rejections', []))
SPEC = load_project('llm_probe')


def run_extract(item, rep):
    cid, scenario, trace = item[:3]
    _local.rejections = []
    runtime = AxisRuntime(spec=SPEC, run_id=f's1b-{rep}', trace_id=f's1b-{rep}:{cid}', scenario_id=scenario, case_id=cid,
                          enabled_axes=('knowledge_evidence', 'truthfulness'))
    usage = {'llm_calls': 0, 'tool_calls': 0}
    t0 = time.time()
    try:
        items, error = ex.extract_claims(trace, runtime, usage), ''
    except Exception as exc:
        items, error = [], str(exc)[:300]
    return {'rep': rep, 'claims': [{'claim': i['text'], 'span': i['span'], 'context': i['context']} for i in items], 'error': error,
            'rejections': list(_local.rejections), 'usage': usage, 'elapsed_ms': int((time.time() - t0) * 1000)}


def run_chain(item):
    cid, scenario, trace = item[:3]
    _local.rejections = []
    axes, _ = load_scenario_axes('llm_probe', scenario)
    chosen = [a for a in axes if a.type_id in ('knowledge_evidence', 'truthfulness')]
    t0 = time.time()
    results = [r.as_dict() for r in run_axes(SPEC, trace, chosen, scenario_id=scenario, run_id='s1b-chain')]
    by = {r['type_id']: r for r in results}
    ke = by.get('knowledge_evidence', {}).get('output') or {}
    searches = {s['call_id']: s for s in ke.get('searches') or []}
    return {'wall_ms': int((time.time() - t0) * 1000), 'rejections': list(_local.rejections),
            'searches': {k: {'error': v.get('error'), 'tool': v.get('tool'), 'has_result': bool(v.get('result'))} for k, v in searches.items()},
            'axes': {k: {'status': r['status'], 'error': r['error'][:300], 'usage': r['usage'], 'elapsed_ms': common.elapsed_ms(r),
                         'output': r['output'] if k == 'truthfulness' else {'items': (r['output'] or {}).get('items')}} for k, r in by.items()}}


def task(item):
    cid = item[0]
    path = OUT / f'{cid}.json'
    if path.exists():
        return
    record = {'case_id': cid, 'scenario': item[1], 'group': item[3], 'category': item[4], 'expected': item[5], 'answer': common.answer_of(item[2])}
    if MODE == 'extract':
        record['reps'] = [run_extract(item, r) for r in range(REPS)]
        print(cid, [len(r['claims']) for r in record['reps']], 'rej', [len(r['rejections']) for r in record['reps']],
              'err', [bool(r['error']) for r in record['reps']], flush=True)
    else:
        record['chain'] = run_chain(item)
        t = record['chain']['axes'].get('truthfulness', {})
        print(cid, t.get('status'), [(c['verdict'], c['text'][:20]) for c in (t.get('output') or {}).get('claims') or []], flush=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    items = common.samples()
    with ThreadPoolExecutor(max_workers=6 if MODE == 'extract' else 4) as pool:
        for f in [pool.submit(task, it) for it in items]:
            f.result()
    print('done', flush=True)
