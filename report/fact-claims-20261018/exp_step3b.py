"""第 3 步补做（修订版方案）：claim_refs 进模型输出结构，代码投影进 evidence_refs 的 {"claim_ids": [...]}；补注入检查。
真实性结果固定用第 1 步重做的链路结果（out/step1b-chain）；兑现轴旧 / 新各 REPS 次。进程内替换，正式文件不改。
- 新：JudgeFulfillmentAssessmentOutput 加 claim_refs（按线程切换输出结构，旧变体结构不变）；
- 投影与后检查挂在 core judge 的 _judge_self_check（结果构造之前）：引用 unverifiable 却判 fulfilled/not_fulfilled、
  或引用不存在的 claim_id → 不一致，退回重判一次；
- 注入检查：用桩模型先返回一份违规输出、再返回合规输出，确认被打回、第二次通过。
用法：python exp_step3b.py <reps> <outdir>
"""
import copy, json, sys, threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from impl.core.project_loader import load_project
from impl.core.schema.judge import JudgeFulfillmentAssessmentOutput, JudgeLLMOutput
from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
import impl.core.judge as cj
import impl.projects.llm_probe.eval_axes.adapters.fulfillment as ful

REPS, OUT = int(sys.argv[1]), Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
TRUTH = Path(__file__).parent / 'out/step1b-chain'
SPEC = load_project('llm_probe')


@dataclass
class AssessmentOut(JudgeFulfillmentAssessmentOutput):
    # 这条期望的结论所依赖的说法 claim_id；不依赖任何说法时 []。
    claim_refs: List[str] = field(default_factory=list)


@dataclass
class LLMOut(JudgeLLMOutput):
    fulfillment_assessments: List[AssessmentOut] = field(default_factory=list)


OLD_HEAD = "上游已对回答中的事实断言逐条核验。"
NEW_HEAD = ("上游已对回答中的事实断言逐条核验，每条有 claim_id。"
            "每个 fulfillment_assessment 填 claim_refs：这条期望的结论所依赖的断言 claim_id；不依赖任何断言时填 []。"
            "程序会检查：claim_refs 引用了 `unverifiable` 断言却判 fulfilled 或 not_fulfilled，输出作废重判。")
_local = threading.local()
_build, _check, _spec = ful.build_context, cj._judge_self_check, cj._build_judge_output_spec


def build(spec, trace, capability, truth=None):
    context = _build(spec, trace, capability, truth)
    if getattr(_local, 'variant', 'old') == 'new' and truth:
        assert any(OLD_HEAD in s for s in context['system_prompt_extras'])
        context['system_prompt_extras'] = [s.replace(OLD_HEAD, NEW_HEAD) for s in context['system_prompt_extras']]
        _local.verdicts = {c['claim_id']: c['verdict'] for c in truth.get('claims', [])}
    return context


def output_spec(*args, **kwargs):
    spec = _spec(*args, **kwargs)
    if getattr(_local, 'variant', 'old') == 'new' and spec.model is JudgeLLMOutput:
        return StructuredOutputSpec.from_dataclass(LLMOut, required_nonempty=list(spec.required_nonempty),
                                                   description=spec.description, nested_schemas=dict(spec.nested_schemas))
    return spec


def check(data, expectations):
    found = list(_check(data, expectations))
    verdicts = getattr(_local, 'verdicts', None)
    if verdicts is None:
        return found
    _local.raw.append(copy.deepcopy(data))
    for index, item in enumerate(data.get('fulfillment_assessments') or []):
        if not isinstance(item, dict):
            continue
        refs = [str(i) for i in item.get('claim_refs') or []]
        # 投影：claim_refs → evidence_refs 的 {"claim_ids": [...]}（归一化会丢掉未知字段）
        item['evidence_refs'] = [*(item.get('evidence_refs') or []), {'claim_ids': refs}]
        status = str(item.get('status') or '').strip().lower()
        unknown = [i for i in refs if i not in verdicts]
        if unknown:
            found.append({'kind': 'unknown_claim_id', 'where': f'fulfillment_assessments[{index}].claim_refs', 'value': unknown})
        bad = [i for i in refs if verdicts.get(i) == 'unverifiable']
        if bad and status in ('fulfilled', 'not_fulfilled'):
            found.append({'kind': 'decided_on_unverifiable_claim', 'where': f'fulfillment_assessments[{index}].status',
                          'value': status, 'claim_ids': bad, 'expected': 'not_evaluable'})
    _local.checks.append([f['kind'] for f in found])
    return found


ful.build_context, cj._judge_self_check, cj._build_judge_output_spec = build, check, output_spec


def claim_ids(a):
    return [i for r in a.get('evidence_refs') or [] if isinstance(r, dict) for i in r.get('claim_ids') or []]


def run_once(cid, scenario, trace, truth, axis, variant, rep, llm=None):
    _local.variant, _local.verdicts, _local.checks, _local.raw = variant, None, [], []
    runtime = AxisRuntime(spec=SPEC, run_id=f's3b-{variant}-{rep}', trace_id=f's3b-{variant}-{rep}:{cid}', scenario_id=scenario,
                          case_id=cid, enabled_axes=('truthfulness', 'fulfillment'))
    original = ful.axis_llm
    if llm is not None:
        ful.axis_llm = lambda *a, **k: llm
    try:
        outcome = ful.run_fulfillment({'trace': trace, 'truth': truth}, axis, runtime)
    finally:
        ful.axis_llm = original
    out = outcome.output or {}
    return {'variant': variant, 'rep': rep, 'status': (out.get('overall_fulfillment') or {}).get('status') if not outcome.failed else 'FAILED',
            'usage': outcome.usage, 'checks': _local.checks, 'raw': _local.raw[:1],
            'items': [{'id': a.get('expectation_id'), 'status': a.get('status'), 'claim_ids': claim_ids(a)} for a in out.get('fulfillment_assessments') or []],
            'reasoning': (out.get('reasoning_summary') or '')[:600]}


def load_truth(cid):
    src = json.loads((TRUTH / f'{cid}.json').read_text())
    t = src['chain']['axes']['truthfulness'].get('output') or {}
    return src, {'claims': t.get('claims') or [], 'coverage': t.get('coverage')}


def task(item):
    cid, scenario, trace, group, cat, exp = item
    path = OUT / f'{cid}.json'
    if path.exists():
        return
    src, truth = load_truth(cid)
    axes, _ = load_scenario_axes('llm_probe', scenario)
    axis = next(a for a in axes if a.type_id == 'fulfillment')
    runs = [run_once(cid, scenario, trace, truth, axis, v, r) for v in ('old', 'new') for r in range(REPS)]
    record = {'case_id': cid, 'group': group, 'category': cat, 'expected': exp, 'answer': src['answer'],
              'claims': [{'claim_id': c['claim_id'], 'text': c['text'], 'verdict': c['verdict']} for c in truth['claims']], 'runs': runs}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print(cid, [c['verdict'][0] for c in truth['claims']], {v: [r['status'] for r in runs if r['variant'] == v] for v in ('old', 'new')}, flush=True)


class StubLLM:
    """注入检查用：依次吐出给定输出。"""
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), 0

    def complete_json(self, *args, **kwargs):
        self.calls += 1
        return copy.deepcopy(self.outputs.pop(0))

    def usage(self):
        return {'llm_calls': self.calls}


def injection():
    item = next(it for it in common.samples() if it[0] == 'unit-policy-present')
    cid, scenario, trace = item[:3]
    rec = json.loads((OUT / f'{cid}.json').read_text())
    real = next(r for r in rec['runs'] if r['variant'] == 'new' and r['raw'])['raw'][0]
    _, truth = load_truth(cid)
    unit = next(c['claim_id'] for c in truth['claims'] if c['verdict'] == 'unverifiable')
    bad = copy.deepcopy(real)
    for a in bad['fulfillment_assessments']:
        a['status'], a['claim_refs'] = 'fulfilled', [unit]
    axes, _ = load_scenario_axes('llm_probe', scenario)
    axis = next(a for a in axes if a.type_id == 'fulfillment')
    stub = StubLLM([bad, real])
    result = run_once(cid, scenario, trace, truth, axis, 'new', 'inject', llm=stub)
    return {'stub_calls': stub.calls, 'checks': result['checks'], 'final_status': result['status'], 'items': result['items']}


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=6) as pool:
        for f in [pool.submit(task, it) for it in common.samples()]:
            f.result()
    inj = injection()
    (OUT / 'injection.json').write_text(json.dumps(inj, ensure_ascii=False, indent=1))
    print('injection', inj, flush=True)
    print('done', flush=True)
