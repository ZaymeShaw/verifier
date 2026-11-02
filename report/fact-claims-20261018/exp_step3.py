"""第 3 步：主判按条引用 + 程序后检查（单次回答路线；进程内替换，正式文件不改）。
同一份真实性结果（第 2 步存下的 r0），兑现轴旧 / 新提示词各 REPS 次。
- 新：每个 fulfillment_assessment 的 actual_evidence 里放 {"claim_ids": [...]}（通用 schema 不动；模型输出结构
  JudgeFulfillmentAssessmentOutput 没有 evidence_refs，那是代码事后挂的，方案原写法放不进去）；
- 程序后检查挂在 core judge 的 _judge_self_check 上：引用了 unverifiable 断言却判 fulfilled/not_fulfilled、或引用了不存在的
  claim_id → 作为不一致退回重判一次（沿用现有一次 reprompt；第二次仍不一致时 core 只在 reasoning 里标 self_check_failed）。
用法：python exp_step3.py <reps> <truth_dir> <outdir>
"""
import json, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from impl.core.project_loader import load_project
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
import impl.core.judge as cj
import impl.projects.llm_probe.eval_axes.adapters.fulfillment as ful

REPS, TRUTH, OUT = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]); OUT.mkdir(parents=True, exist_ok=True)
SPEC = load_project('llm_probe')
OLD_HEAD = "上游已对回答中的事实断言逐条核验。"
NEW_HEAD = ("上游已对回答中的事实断言逐条核验，每条有 claim_id。"
            "每个 fulfillment_assessment 的 actual_evidence 里放一项 {\"claim_ids\": [...]}，列出这条期望的结论所依赖的断言 claim_id；"
            "不依赖任何断言时列 []。程序会检查：引用了 `unverifiable` 断言却判 fulfilled 或 not_fulfilled，输出作废重判。")
_local = threading.local()
_build, _check = ful.build_context, cj._judge_self_check


def build_new(spec, trace, capability, truth=None):
    context = _build(spec, trace, capability, truth)
    if truth:
        extras = context['system_prompt_extras']
        assert any(OLD_HEAD in s for s in extras)
        context['system_prompt_extras'] = [s.replace(OLD_HEAD, NEW_HEAD) for s in extras]
    _local.verdicts = {c['claim_id']: c['verdict'] for c in (truth or {}).get('claims', [])}
    return context


def refs_of(item):
    ids = []
    for ref in (item.get('actual_evidence') or []) + (item.get('evidence_refs') or []):
        if isinstance(ref, dict) and isinstance(ref.get('claim_ids'), list):
            ids += [str(i) for i in ref['claim_ids']]
    return ids


def check_new(data, expectations):
    found = list(_check(data, expectations))
    verdicts = getattr(_local, 'verdicts', None)
    if verdicts is None:
        return found
    for index, item in enumerate(data.get('fulfillment_assessments') or []):
        if not isinstance(item, dict):
            continue
        refs, status = refs_of(item), str(item.get('status') or '').strip().lower()
        unknown = [i for i in refs if i not in verdicts]
        if unknown:
            found.append({'kind': 'unknown_claim_id', 'where': f'fulfillment_assessments[{index}].evidence_refs', 'value': unknown})
        bad = [i for i in refs if verdicts.get(i) == 'unverifiable']
        if bad and status in ('fulfilled', 'not_fulfilled'):
            found.append({'kind': 'decided_on_unverifiable_claim', 'where': f'fulfillment_assessments[{index}].status',
                          'value': status, 'claim_ids': bad, 'expected': 'not_evaluable'})
    _local.checks.append([f['kind'] for f in found])
    return found


cj._judge_self_check = check_new


def dispatch(*args, **kwargs):
    # 旧 / 新按线程切换：每个线程跑一个 case，线程局部记当前用哪套。
    return build_new(*args, **kwargs) if getattr(_local, 'variant', 'old') == 'new' else _build(*args, **kwargs)


ful.build_context = dispatch


def run_once(cid, scenario, trace, truth, axis, variant, rep):
    _local.variant = variant
    _local.verdicts = None
    _local.checks = []
    runtime = AxisRuntime(spec=SPEC, run_id=f's3-{variant}-{rep}', trace_id=f's3-{variant}-{rep}:{cid}', scenario_id=scenario,
                          case_id=cid, enabled_axes=('truthfulness', 'fulfillment'))
    outcome = ful.run_fulfillment({'trace': trace, 'truth': truth}, axis, runtime)
    out = outcome.output or {}
    status = (out.get('overall_fulfillment') or {}).get('status') if not outcome.failed else 'FAILED'
    return {'variant': variant, 'rep': rep, 'status': status, 'usage': outcome.usage, 'checks': _local.checks,
            'items': [{'id': a.get('expectation_id'), 'status': a.get('status'), 'claim_ids': refs_of(a)} for a in out.get('fulfillment_assessments') or []],
            'expectations': [{'id': e.get('expectation_id'), 'blocking': e.get('blocking'), 'outcome': e.get('expected_outcome')} for e in out.get('business_expectations') or []],
            'reasoning': (out.get('reasoning_summary') or '')[:600]}


def task(item):
    cid, scenario, trace, group, cat, exp = item
    path = OUT / f'{cid}.json'
    if path.exists():
        return
    src = json.loads((TRUTH / f'{cid}-r0.json').read_text())
    tout = src['axes']['truthfulness'].get('output') or {}
    truth = {'claims': tout.get('claims') or [], 'coverage': tout.get('coverage')}
    axes, _ = load_scenario_axes('llm_probe', scenario)
    axis = next(a for a in axes if a.type_id == 'fulfillment')
    runs = [run_once(cid, scenario, trace, truth, axis, v, r) for v in ('old', 'new') for r in range(REPS)]
    record = {'case_id': cid, 'group': group, 'category': cat, 'expected': exp, 'answer': src['answer'],
              'claims': [{'claim_id': c['claim_id'], 'text': c['text'], 'verdict': c['verdict']} for c in truth['claims']], 'runs': runs}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print(cid, [c['verdict'] for c in truth['claims']], {v: [r['status'] for r in runs if r['variant'] == v] for v in ('old', 'new')}, flush=True)


if __name__ == '__main__':
    items = [it for it in common.samples() if (TRUTH / f'{it[0]}-r0.json').exists()]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for f in [pool.submit(task, it) for it in items]:
            f.result()
    print('done', flush=True)
