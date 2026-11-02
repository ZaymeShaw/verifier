"""第 1 步：提取规则拆单位（只换提取提示词，进程内替换，正式文件不改）。
用法：python exp_step1.py <old|new> <extract|chain> <reps> <outdir>
  extract：只跑提取，看条数、隔离检查打回、变义；chain：跑知识查证 + 真实性，看调用数与耗时，并存下真实性结果给第 2、3 步。
"""
import json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402  (设置路径与实例)
from impl.core.project_loader import load_project
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.runner import run_axes
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
import impl.projects.llm_probe.knowledge_loop.extract as ex

VARIANT, MODE, REPS, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
OUT.mkdir(parents=True, exist_ok=True)

OLD_EXAMPLE = ('例如“甲产品投保年龄十八周岁，年交保费五千元”抽两条：text=“投保年龄十八周岁” context=[“甲产品”]；'
               'text=“年交保费五千元” context=[“甲产品”]。')
NEW_EXAMPLE = ('一个数带的单位、币种、时点、所属对象各自是一条断言，与那个数分开：值那条 text 摘到数字为止；'
               '单位、币种、时点那条 text 只摘它自己，context 放这个数所属对象的标识和这个数的事项名称。'
               '例如“甲产品投保年龄十八周岁，年交保费五千元”抽四条：text=“投保年龄十八” context=[“甲产品”]；'
               'text=“周岁” context=[“甲产品”,“投保年龄”]；text=“年交保费五千” context=[“甲产品”]；'
               'text=“元” context=[“甲产品”,“年交保费”]。')
assert OLD_EXAMPLE in ex.EXTRACT_SYSTEM
if VARIANT == 'new':
    ex.EXTRACT_SYSTEM = ex.EXTRACT_SYSTEM.replace(OLD_EXAMPLE, NEW_EXAMPLE)

_local = threading.local()
_parse = ex.parse_claims


def counting_parse(payload, output_text):
    try:
        return _parse(payload, output_text)
    except ValueError as exc:
        getattr(_local, 'rejections', []).append(str(exc)[:300])
        raise


ex.parse_claims = counting_parse
SPEC = load_project('llm_probe')


def run_extract(item, rep):
    cid, scenario, trace, group, cat, exp = item
    _local.rejections = []
    runtime = AxisRuntime(spec=SPEC, run_id=f's1-{VARIANT}-{rep}', trace_id=f's1-{VARIANT}-{rep}:{cid}', scenario_id=scenario,
                          case_id=cid, enabled_axes=('knowledge_evidence', 'truthfulness'))
    usage = {'llm_calls': 0, 'tool_calls': 0}
    t0 = time.time()
    try:
        claims, error = ex.extract_claims(trace, runtime, usage), ''
    except Exception as exc:
        claims, error = [], str(exc)[:300]
    return {'rep': rep, 'claims': [{'text': c['text'], 'context': c['context']} for c in claims], 'error': error,
            'rejections': list(_local.rejections), 'usage': usage, 'elapsed_ms': int((time.time() - t0) * 1000)}


def run_chain(item):
    cid, scenario, trace, group, cat, exp = item
    _local.rejections = []
    axes, _ = load_scenario_axes('llm_probe', scenario)
    chosen = [a for a in axes if a.type_id in ('knowledge_evidence', 'truthfulness')]
    t0 = time.time()
    results = [r.as_dict() for r in run_axes(SPEC, trace, chosen, scenario_id=scenario, run_id=f's1-{VARIANT}-chain')]
    by = {r['type_id']: r for r in results}
    return {'wall_ms': int((time.time() - t0) * 1000), 'rejections': list(_local.rejections),
            'axes': {k: {'status': r['status'], 'error': r['error'][:300], 'usage': r['usage'], 'elapsed_ms': common.elapsed_ms(r),
                         'output': r['output']} for k, r in by.items()}}


def task(item):
    cid, scenario, trace, group, cat, exp = item
    path = OUT / f'{cid}.json'
    if path.exists():
        return
    record = {'case_id': cid, 'scenario': scenario, 'group': group, 'category': cat, 'expected': exp, 'variant': VARIANT,
              'answer': common.answer_of(trace)}
    if MODE == 'extract':
        record['reps'] = [run_extract(item, r) for r in range(REPS)]
        print(cid, [len(r['claims']) for r in record['reps']], 'rej', [len(r['rejections']) for r in record['reps']], flush=True)
    else:
        record['chain'] = run_chain(item)
        truth = record['chain']['axes'].get('truthfulness', {})
        print(cid, truth.get('status'), [c.get('verdict') for c in ((truth.get('output') or {}).get('claims') or [])], flush=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    items = common.samples()
    with ThreadPoolExecutor(max_workers=6 if MODE == 'extract' else 4) as pool:
        for f in [pool.submit(task, it) for it in items]:
            f.result()
    print('done', flush=True)
