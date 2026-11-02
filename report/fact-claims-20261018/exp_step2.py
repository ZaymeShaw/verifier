"""第 2 步：查不到的说法也带回执（加字段，verdict 三值不动；进程内替换，正式文件不改）。
v8 里取证（knowledge_evidence 轴）与判定（truthfulness 轴）是两步，方案里的 _verify_result 已不存在，落点对应为：
- lookups：程序从取证案卷的 search_calls → searches 接出（查了哪个工具、什么参数、返回落在哪个 call_id），不调模型；
- found{object, attribute}：取证提交 submit_item 时同一次输出里填（not_found 不走判定模型，只有取证这一步看过返回）。
用法：python exp_step2.py <reps> <outdir> [组,组]
"""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from impl.core.project_loader import load_project
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.runner import run_axes
import impl.projects.llm_probe.knowledge_loop.loop as lp
import impl.projects.llm_probe.eval_axes.adapters.truthfulness as tr

REPS, OUT = int(sys.argv[1]), Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
GROUPS = set(sys.argv[3].split(',')) if len(sys.argv) > 3 else None

FOUND_SCHEMA = {'type': 'object', 'description': '查询返回里看到了什么（只记看到的，不判对错）',
                'properties': {'object': {'type': 'boolean', 'description': '返回里有没有说法所说的那个对象（那个人、那张单、那款产品那个版本）'},
                               'attribute': {'type': 'boolean', 'description': '对象在时，返回里有没有说法说的那一项（那个字段、那条规定）；对象不在时填 false'}},
                'required': ['object', 'attribute'], 'additionalProperties': False}
lp._SUBMIT_PARAMETERS = {**lp._SUBMIT_PARAMETERS,
                         'properties': {**lp._SUBMIT_PARAMETERS['properties'], 'found': FOUND_SCHEMA},
                         'required': [*lp._SUBMIT_PARAMETERS['required'], 'found']}
lp.SYSTEM = lp.SYSTEM.replace('提交：每查完一条', 'found 字段记查询返回里看到了什么：对象在不在、对象的这一项在不在；found 和 not_found 都要填，只记看到的，不判对错。\n\n提交：每查完一条')
assert 'found 字段记' in lp.SYSTEM

_end = lp.KnowledgeLoop._end


def end_with_receipts(self, history):
    dossier = _end(self, history)
    accepted = self.checklist.accepted(history)
    by_ref = {s['call_id']: s for s in dossier['searches']}
    for item in dossier['items']:
        args = accepted[item['item_id']].args
        item['found'] = args.get('found')
        item['lookups'] = [{'source': by_ref[r]['source'], 'ref': r, 'tool': by_ref[r]['tool'], 'args': by_ref[r]['args']}
                           for r in item['search_calls'] if r in by_ref]
    return dossier


lp.KnowledgeLoop._end = end_with_receipts
_claim = tr._claim


def claim_with_receipts(item, judged):
    return {**_claim(item, judged), 'lookups': item.get('lookups', []), 'found': item.get('found')}


tr._claim = claim_with_receipts
SPEC = load_project('llm_probe')


def run_chain(item, rep):
    cid, scenario, trace, group, cat, exp = item
    axes, _ = load_scenario_axes('llm_probe', scenario)
    chosen = [a for a in axes if a.type_id in ('knowledge_evidence', 'truthfulness')]
    t0 = time.time()
    results = [r.as_dict() for r in run_axes(SPEC, trace, chosen, scenario_id=scenario, run_id=f's2-{rep}')]
    by = {r['type_id']: r for r in results}
    ke = by.get('knowledge_evidence', {}).get('output') or {}
    searches = {s['call_id']: s for s in ke.get('searches') or []}
    return {'rep': rep, 'wall_ms': int((time.time() - t0) * 1000), 'searches': {k: {'error': v.get('error'), 'tool': v.get('tool'), 'has_result': bool(v.get('result'))} for k, v in searches.items()},
            'axes': {k: {'status': r['status'], 'error': r['error'][:300], 'usage': r['usage'], 'elapsed_ms': common.elapsed_ms(r),
                         'output': r['output'] if k == 'truthfulness' else {'items': (r['output'] or {}).get('items')}} for k, r in by.items()}}


def task(item_rep):
    item, rep = item_rep
    cid = item[0]
    path = OUT / f'{cid}-r{rep}.json'
    if path.exists():
        return
    record = {'case_id': cid, 'scenario': item[1], 'group': item[3], 'category': item[4], 'expected': item[5], 'answer': common.answer_of(item[2])}
    record.update(run_chain(item, rep))
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    t = record['axes'].get('truthfulness', {})
    print(cid, rep, t.get('status'), [(c['verdict'], c.get('found')) for c in (t.get('output') or {}).get('claims') or []], flush=True)


if __name__ == '__main__':
    items = [it for it in common.samples() if GROUPS is None or it[3] in GROUPS]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in [pool.submit(task, (it, r)) for r in range(REPS) for it in items]:
            f.result()
    print('done', flush=True)
