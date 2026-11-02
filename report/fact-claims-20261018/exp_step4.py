"""第 4 步：trace 路线没有核事实记录时主判怎么说话（进程内替换，正式文件不改）。
同一份案卷：过程轴只跑一次并冻结主判材料，主判旧 / 新各 REPS 次。
用法：python exp_step4.py <reps> <outdir>
"""
import copy, json, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import e_samples
from impl.core.project_loader import load_project
from impl.core.judge import _derive_overall_status
import impl.projects.llm_probe.need_judge as nj
from impl.projects.llm_probe.judge import LlmProbeJudge, ProcessJudgeExecution

REPS, OUT = int(sys.argv[1]), Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
SPEC = load_project('llm_probe')
NEW_RULE = "本 case 没有评测方独立核事实的记录；不得在 observed / reasoning 里说任何事实已核实或核实不了，只能说'未独立核实'。"
PHRASE = re.compile(r'核实不了|无法核实|不能核实|难以核实|未能核实|已核实|已经核实|经核实|核实了|核实为|核实无误|得到核实|可以核实|已证实|无法证实|无法确认|未经核实|未核实')
_orig = nj.run_need_judge
_local = threading.local()


class Captured(Exception):
    pass


def capture(spec, trace, frozen, context):
    _local.captured = (copy.deepcopy(frozen), copy.deepcopy(context))
    raise Captured


nj.run_need_judge = capture


def material(name):
    path = OUT / f'ctx-{name}.json'
    if path.exists():
        return json.loads(path.read_text())
    trace = e_samples.load(name)
    _local.captured = None
    try:
        early = ProcessJudgeExecution().run(LlmProbeJudge(SPEC), trace, None)
    except Captured:
        early = None
    report = getattr(trace, '_pending_process_report', {}) or {}
    kd = next((r for r in report.get('results', []) if r.get('type_id') == 'knowledge_data'), {})
    data = {'name': name, 'early': None if early is None else {'status': early.overall_fulfillment, 'reason': early.reasoning_summary},
            'knowledge_data': {'status': kd.get('status'), 'verdict': kd.get('verdict'), 'summary': (kd.get('summary') or {}).get('text', '')[:600]},
            'answer': (trace.extracted_output or {}).get('output_text', '')[:1500],
            'trace': {'trace_id': trace.trace_id, 'project_id': trace.project_id, 'extracted_output': trace.extracted_output}}
    if _local.captured:
        data['frozen'], data['context'] = _local.captured
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    return json.loads(path.read_text())


class T:  # run_need_judge 只用 trace_id / project_id / extracted_output
    def __init__(self, d):
        self.trace_id, self.project_id, self.extracted_output = d['trace_id'], d['project_id'], d['extracted_output']


def judge_once(data, variant, rep):
    context = copy.deepcopy(data['context'])
    if variant == 'new':
        context['user_prompt_extras']['fact_claims'] = None
        context['system_prompt_extras'].append(NEW_RULE)
    trace = T(data['trace']); trace.trace_id = f"s4-{variant}-{rep}:{data['name']}"
    try:
        result = _orig(SPEC, trace, data['frozen'], context)
    except Exception as exc:
        return {'variant': variant, 'rep': rep, 'status': 'FAILED', 'error': str(exc)[:300]}
    texts = [result.reasoning_summary] + [o for a in result.fulfillment_assessments for o in a.actual_evidence]
    hits = [m.group(0) for t in texts for m in PHRASE.finditer(t or '')]
    return {'variant': variant, 'rep': rep, 'status': _derive_overall_status(result.business_expectations, result.fulfillment_assessments),
            'items': [{'id': a.expectation_id, 'status': a.status, 'observed': a.actual_evidence[0][:400]} for a in result.fulfillment_assessments],
            'reasoning': result.reasoning_summary, 'phrases': hits, 'independent': len(re.findall('未独立核实', ' '.join(texts)))}


def run(name):
    path = OUT / f'{name}.json'
    if path.exists():
        return
    data = material(name)
    if 'context' not in data:
        print(name, 'early', data['early'], flush=True)
        return
    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = list(pool.map(lambda vr: judge_once(data, *vr), [(v, r) for v in ('old', 'new') for r in range(REPS)]))
    record = {'name': name, 'knowledge_data': data['knowledge_data'], 'runs': runs}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print(name, 'kd', data['knowledge_data']['verdict'], {v: [(r['status'], len(r.get('phrases', []))) for r in runs if r['variant'] == v] for v in ('old', 'new')}, flush=True)


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in [pool.submit(run, n) for n in e_samples.NAMES]:
            f.result()
    print('done', flush=True)
