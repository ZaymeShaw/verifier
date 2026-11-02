"""D18 实测：同一份真实性轴结果，fulfillment 用改动前 / 改动后提示词各跑 N 次。正式代码文件不改。
用法：python exp_d18.py <reps> <outdir>
"""
import copy, glob, json, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT = Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier-integrate'); sys.path.insert(0, str(ROOT))
from impl.core.project_loader import load_project
from impl.server.service import normalize_run_trace
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.runner import run_axes
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
import impl.projects.llm_probe.eval_axes.adapters.fulfillment as ful

REPS, OUT = int(sys.argv[1]), Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
HEAD = "上游已对回答中的事实断言逐条核验。`refuted` 的断言视为事实错误，据此判相关期望 not_fulfilled"
NEW = (HEAD + "。\n`unverifiable` 表示评测侧在知识源里没找到支持它的原文——可能是业务编造，也可能是评测侧没检索到，"
       "不能据此判对，也不能据此判错：结论依赖该断言的期望判 not_evaluable，不判 fulfilled，也不判 not_fulfilled；"
       "trace 里有业务自己核实过该事实的记录时除外。\n不要重复核验，也不要发明核验结果里没有的断言。")
OLD = HEAD + "；`unverifiable` 不构成失败依据；不要重复核验，也不要发明核验结果里没有的断言。"
_orig = ful.build_context


def build_old(*args, **kwargs):
    context = _orig(*args, **kwargs)
    context["system_prompt_extras"] = [s.replace(NEW, OLD) for s in context["system_prompt_extras"]]
    return context

HR = [  # (id, 问题, 回答, 类别, 预期)
    ("hr-annual-ok", "我在公司累计工龄3年，年休假有几天？", "年休假十天。", "correct", "fulfilled"),
    ("hr-annual-wrong", "我在公司累计工龄3年，年休假有几天？", "年休假十五天。", "wrong", "not_fulfilled"),
    ("hr-annual-side", "我在公司累计工龄3年，年休假有几天？", "年休假十天，没休完的年假可以在年底折算成现金发放。", "core_ok_side_unverifiable", "fulfilled"),
    ("hr-probation-ok", "劳动合同签两年，试用期最长多久？", "试用期不超过二个月。", "correct", "fulfilled"),
    ("hr-probation-wrong", "劳动合同签两年，试用期最长多久？", "试用期不超过六个月。", "wrong", "not_fulfilled"),
    ("hr-probation-side", "劳动合同签两年，试用期最长多久？", "试用期不超过二个月，试用期内每月要向直属上级提交一次书面工作总结。", "core_ok_side_unverifiable", "fulfilled"),
    ("hr-resign-ok", "正式员工辞职要提前多久通知公司？", "正式员工须提前三十日以书面形式通知公司。", "correct", "fulfilled"),
    ("hr-resign-wrong", "正式员工辞职要提前多久通知公司？", "正式员工须提前十五日通知公司。", "wrong", "not_fulfilled"),
    ("hr-resign-side", "正式员工辞职要提前多久通知公司？", "正式员工须提前三十日以书面形式通知公司，发邮件给直属上级即视为书面通知。", "core_ok_side_unverifiable", "fulfilled"),
    ("hr-housing-core", "公司有没有住房补贴？每月多少？", "有，每月住房补贴一千五百元，随工资发放。", "core_unverifiable", "not_evaluable"),
    ("hr-petleave-core", "宠物去世可以请几天丧假？", "宠物丧假一天，需提前一天申请。", "core_unverifiable", "not_evaluable"),
]
CLAUSE_EXPECT = {"clause-verified-kn-hesitation": ("correct", "fulfilled"), "clause-refuted-xx-hesitation-stale": ("wrong", "not_fulfilled"),
                 "clause-unverifiable-kn-cashvalue": ("core_unverifiable", "not_evaluable"), "clause-multi-ax": ("multi", "?"),
                 "clause-noclaim-opinion": ("no_claim", "?")}


def samples():
    out = []
    template = None
    for f in sorted(glob.glob(str(Path('/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier') / 'report/axes-validation-20260909/live/clause/clause-*.json'))):
        x = json.loads(Path(f).read_text()); t = x['trace']; template = template or t
        cat, exp = CLAUSE_EXPECT[x['compact']['case_id']]
        out.append((x['compact']['case_id'], 'policy-clause-qa', normalize_run_trace(t), cat, exp, 'real'))
    for cid, q, a, cat, exp in HR:
        t = copy.deepcopy(template)
        t['trace_id'] = t['case_id'] = cid
        req = t['normalized_request']; req['capability_ref'] = 'hr-handbook-qa'
        req['body']['input']['messages'] = [{"role": "user", "content": q}]
        t['input'] = req
        t['extracted_output'] = {'output_text': json.dumps({"output": {"choices": [{"message": {"role": "assistant", "content": a}}]}}, ensure_ascii=False)}
        t['raw_response'] = json.loads(t['extracted_output']['output_text'])
        out.append((cid, 'hr-handbook-qa', normalize_run_trace(t), cat, exp, 'synthetic'))
    return out


def status_of(outcome):
    return ((outcome.output or {}).get('overall_fulfillment') or {}).get('status') if not outcome.failed else 'FAILED'


def run_case(item):
    cid, scenario, trace, cat, exp, origin = item
    path = OUT / f'{cid}.json'
    if path.exists():
        return
    spec = load_project('llm_probe')
    axes, rep = load_scenario_axes('llm_probe', scenario)
    truth_axis = next(a for a in axes if a.type_id == 'truthfulness')
    ful_axis = next(a for a in axes if a.type_id == 'fulfillment')
    ke_axis = next(a for a in axes if a.type_id == 'knowledge_evidence')
    results = run_axes(spec, trace, [ke_axis, truth_axis], scenario_id=scenario)
    truth = next(r.as_dict() for r in results if r.type_id == 'truthfulness')
    if truth.get('status') != 'succeeded':
        print(cid, 'truthfulness', truth.get('status'), str(truth.get('error'))[:200], flush=True)
    truth_out = truth.get('output') or {}
    record = {'case_id': cid, 'scenario': scenario, 'category': cat, 'expected': exp, 'origin': origin,
              'answer': json.loads(trace.extracted_output['output_text'])['output']['choices'][0]['message']['content'],
              'truth_status': truth.get('status'),
              'claims': [{'text': c.get('text'), 'verdict': c.get('verdict')} for c in truth_out.get('claims') or []],
              'runs': {'old': [], 'new': []}}
    for variant in ('old', 'new'):
        for rep_i in range(REPS):
            ful.build_context = build_old if variant == 'old' else _orig
            runtime = AxisRuntime(spec=spec, run_id=f'd18-{variant}-{rep_i}', trace_id=f'd18-{variant}-{rep_i}:{cid}',
                                  scenario_id=scenario, case_id=cid, enabled_axes=('truthfulness', 'fulfillment'))
            outcome = ful.run_fulfillment({'trace': trace, 'truth': {'claims': truth_out.get('claims') or [], 'coverage': truth_out.get('coverage')}}, ful_axis, runtime)
            record['runs'][variant].append({'status': status_of(outcome),
                                            'reason': ((outcome.output or {}).get('reasoning_summary') or '')[:300]})
    ful.build_context = _orig
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print(cid, 'truth', [c['verdict'] for c in record['claims']], 'old', [r['status'] for r in record['runs']['old']],
          'new', [r['status'] for r in record['runs']['new']], flush=True)


if __name__ == '__main__':
    items = samples()
    print('samples', len(items), flush=True)
    for it in items:  # 串行：build_context 在进程内切换，不能并发
        run_case(it)
    print('done', flush=True)
