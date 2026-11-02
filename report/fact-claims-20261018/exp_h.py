"""H：说做不到被判办成（spec/adapter/claims-extraction-plan-20261019.md H）。进程内替换，正式文件不改。
三处一起改：抽取收"没有/查不到"类说法；真实性判定这类说法；主轴提示词"如实说做不到≠办成"。
用法：python exp_h.py <old|new|new2> <reps> <outdir> <H|all|E01>
"""
import json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from impl.core.project_loader import load_project
from impl.server.service import normalize_run_trace
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.runner import run_axes
import impl.projects.llm_probe.knowledge_loop.extract as ex
import impl.projects.llm_probe.eval_axes.adapters.truthfulness as tr
import impl.projects.llm_probe.eval_axes.adapters.fulfillment as fu

VARIANT, REPS, OUT, WHICH = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
OUT.mkdir(parents=True, exist_ok=True)
H_DIR = Path(__file__).parent / 'out/h-samples'
EXTRA_DIR = Path(__file__).parent / 'out/c1-samples'  # C1：10-19 第二次复跑答案变了的 F01、B02
H_EXPECT = {'F01': 'not_fulfilled', 'neg-unknown': 'not_fulfilled', 'E01': 'not_fulfilled', 'B02': '?', 'G01': '?'}

EXTRACT_ADD = ('回答说某对象的某项没有、查不到、未返回、无法确认（如“未检索到该保单”“未返回累计已交保费”“没有找到该产品的等待期条款”），'
               '也是一条断言——断言信息源里没有这一项，同样要抽：text 摘说“没有”的那段原文（含所说的事项），context 放对象标识。'
               '只说回答者自己做了什么（“我查了两次”“调用了某工具”）、不涉及对象有没有某项的，不抽。')
JUDGE_ANCHOR = '② 和 ③ 不给任何对象的属性赋值，不能作为 refuted 的依据。'
JUDGE_ADD = ('\n说法断言某项没有、查不到时（如“未检索到该保单”“未返回某项”“没有找到某条款”）：\n'
             '- ① 里有同一对象的这一项（有值）→ refuted，reason 写出原文给的值；\n'
             '- ② 明确表明按这个对象查过、结果读全了，而对象不存在、或对象在但没有这一项 → verified；\n'
             '- 查回来的是别的对象、没读全、或没有按这个对象查 → unverifiable：没查到不等于不存在。')
FULFILL_ADD = ('## 说做不到不是结果\n'
               '用户要的是结果（查一个值、讲一段条款、给出名单）时，回答说查不到、没取到、无法确认，只是如实的态度，不是结果；'
               '如实说明本身不能让这条期望判 fulfilled。\n'
               '这类期望看真实性核验里对应"没有/查不到"的那条说法：verified（信息源里确实没有）→ 回答说的就是事实，判 fulfilled；'
               'refuted（信息源里有）→ not_fulfilled；unverifiable → not_evaluable；没有对应的核验结果 → not_fulfilled。\n')

if VARIANT == 'new2':  # 第二轮：E01 漏抽 + 主判自称"核验 verified"
    EXTRACT_ADD += '回答通篇是在说查不到时，这些“没有”的说法就是它的主要断言，不能漏。'
    FULFILL_ADD = FULFILL_ADD.replace('没有对应的核验结果 → not_fulfilled。', '核验结果里找不到这样一条说法时，就是没有对应的核验结果，不得自行认定它已核过，判 not_fulfilled。')
if VARIANT in ('new', 'new2'):
    ex.EXTRACT_SYSTEM = ex.EXTRACT_SYSTEM + EXTRACT_ADD
    assert JUDGE_ANCHOR in tr._JUDGE_SYSTEM
    tr._JUDGE_SYSTEM = tr._JUDGE_SYSTEM.replace(JUDGE_ANCHOR, JUDGE_ANCHOR + JUDGE_ADD)
    _build = fu.build_context

    def build_context(*args, **kwargs):
        context = _build(*args, **kwargs)
        context['system_prompt_extras'].append(FULFILL_ADD)
        return context
    fu.build_context = build_context

SPEC = load_project('llm_probe')
CHAIN = ('knowledge_evidence', 'truthfulness', 'fulfillment')


def h_samples():
    out = []
    for f in sorted(H_DIR.glob('*.json')) + sorted(EXTRA_DIR.glob('*.json')):
        x = json.loads(f.read_text())
        cid = x['case_id']
        exp = next((v for k, v in H_EXPECT.items() if k in cid), '?')
        out.append((cid, 'verify-insurance-mcp', normalize_run_trace(x['trace']), 'H', 'mcp_live', exp))
    return out


def run_once(item, rep):
    cid, scenario, trace = item[:3]
    axes, _ = load_scenario_axes('llm_probe', scenario)
    chosen = [a for a in axes if a.type_id in CHAIN]
    results = {r.type_id: r.as_dict() for r in run_axes(SPEC, trace, chosen, scenario_id=scenario, run_id=f'h-{VARIANT}-{rep}')}
    truth = (results.get('truthfulness') or {}).get('output') or {}
    ff = results.get('fulfillment') or {}
    return {'rep': rep,
            'status': {k: r['status'] for k, r in results.items()},
            'errors': {k: r['error'][:300] for k, r in results.items() if r.get('error')},
            'usage': {k: r['usage'] for k, r in results.items()},
            'claims': [{k: c.get(k) for k in ('text', 'context', 'verdict', 'reason')} for c in truth.get('claims') or []],
            'fulfillment': ((ff.get('output') or {}).get('overall_fulfillment') or {}).get('status') if ff.get('status') == 'succeeded' else 'axis_' + str(ff.get('status')),
            'reasoning': ((ff.get('output') or {}).get('reasoning_summary') or '')[:800]}


def task(item, rep):
    cid = item[0]
    path = OUT / f'{cid}.r{rep}.json'
    if path.exists():
        return
    try:
        run = run_once(item, rep)
    except Exception as exc:  # 记下来，不中断整批
        run = {'rep': rep, 'crash': repr(exc)[:500]}
    record = {'case_id': cid, 'group': item[3], 'expected': item[5], 'variant': VARIANT, 'answer': common.answer_of(item[2])[:600], **run}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print(cid, rep, run.get('fulfillment') or run.get('crash'), [(c['verdict'], (c['text'] or '')[:24]) for c in run.get('claims') or []], flush=True)


if __name__ == '__main__':
    items = h_samples() + ([] if WHICH in ('H', 'E01') else common.f_samples() + common.samples())
    items = [it for it in items if WHICH != 'E01' or 'E01' in it[0]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for f in [pool.submit(task, it, r) for it in items for r in range(REPS)]:
            f.result()
    print('done', flush=True)
