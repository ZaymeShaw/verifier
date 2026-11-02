"""A1：对象和条件可取自用户问题（spec/adapter/claims-extraction-plan-20261019.md §2）。进程内替换，正式文件不改。
用法：python exp_a1.py <old|new> <extract|chain> <reps> <outdir> <all|F>
"""
import json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from impl.core.project_loader import load_project
from impl.core.structured_output import StructuredOutputSpec
from impl.projects.llm_probe.eval_axes.llm import axis_llm, merge_usage
from impl.projects.llm_probe.eval_axes.validate import load_scenario_axes
from impl.projects.llm_probe.eval_axes.runner import run_axes
from impl.projects.llm_probe.eval_axes.types import AxisRuntime
import impl.projects.llm_probe.knowledge_loop.extract as ex
import impl.projects.llm_probe.eval_axes.adapters.truthfulness as tr

VARIANT, MODE, REPS, OUT, WHICH = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4]), sys.argv[5]
OUT.mkdir(parents=True, exist_ok=True)
_local = threading.local()

REPLACE = [
    ('text 和 context 里的每一段都必须逐字摘自 output_text 的连续原文。',
     'text 必须逐字摘自 output_text 的连续原文；context 每一段逐字摘自 output_text 或用户问题（question）的连续原文。'),
    ('context 是核验这条 text 所需的最少上下文片段列表，只放两种：',
     'context 是核验这条 text 所需的最少上下文片段列表，回答里没有时从用户问题里摘，只放两种：'),
    ('回答里找不到它所指对象的标识，这条就不抽。',
     '回答和用户问题里都找不到它所指对象的标识，这条才不抽。'
     '例如问"累计工龄3年，年休假有几天？"、回答"5天"：text=“5天” context=[“累计工龄3年”,“年休假”]（都摘自问题）。'),
]


def question_text(request):
    """用户问题原文：请求体里各条消息的 content。"""
    body = (request or {}).get('body') or {}
    messages = (body.get('input') or {}).get('messages') or body.get('messages') or []
    return '\n'.join(str(m.get('content') or '') for m in messages if isinstance(m, dict))


def parse_claims_a1(payload, output_text, question):
    """同 extract.parse_claims，context 可逐字出自回答或问题。"""
    if not isinstance(payload, dict) or payload.get('error') or not isinstance(payload.get('claims'), list):
        raise ValueError('断言提取失败：缺少 claims 列表')
    plain_out, plain_q = ex._plain(output_text), ex._plain(question)
    seen, result = set(), []
    for claim in payload['claims']:
        if not isinstance(claim, dict):
            raise ValueError('断言必须是对象')
        key, text, context = claim.get('claim_id'), claim.get('text'), claim.get('context', [])
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError('claim_id 必须唯一且非空')
        if not isinstance(text, str) or not text.strip() or ex._plain(text) not in plain_out:
            raise ValueError(f'断言 {key} 的 text {text!r} 不是 output_text 的逐字连续原文')
        if not isinstance(context, list):
            raise ValueError(f'断言 {key} 的 context 必须是字符串列表')
        bad = [c for c in context if not isinstance(c, str) or not c.strip() or (ex._plain(c) not in plain_out and ex._plain(c) not in plain_q)]
        if bad:
            raise ValueError(f'断言 {key} 的 context 段 {bad[0]!r} 既不是 output_text 也不是用户问题的逐字连续原文')
        seen.add(key)
        result.append({'claim_id': key, 'text': text, 'context': [c.strip() for c in context]})
    for claim in result:
        for other in result:
            if other is not claim:
                leaked = [c for c in claim['context'] if ex._contains_value(c, other['text'])]
                if leaked:
                    raise ValueError(f"断言 {claim['claim_id']} 的 context {leaked[0]!r} 含了断言 {other['claim_id']} 的值 {other['text']!r}，只放定位所需的上下文")
    return result


def extract_a1(trace, runtime, usage):
    output_text = (trace.extracted_output or {}).get('output_text')
    if not isinstance(output_text, str):
        raise ValueError('output_text 缺失或不是文本')
    request = trace.normalized_request or {}
    question = question_text(request)
    system = ex.EXTRACT_SYSTEM
    for a, b in REPLACE:
        assert a in system, a
        system = system.replace(a, b)
    client = axis_llm(runtime.spec, role='truthfulness', tools=[])
    user = json.dumps({'output_text': output_text, 'question': request.get('body') or {}}, ensure_ascii=False)
    spec = StructuredOutputSpec.from_dataclass(ex.ExtractedClaims)

    def parse(payload):
        try:
            return parse_claims_a1(payload, output_text, question)
        except ValueError as exc:
            getattr(_local, 'rejections', []).append(str(exc)[:300])
            raise
    try:
        try:
            claims = parse(client.complete_json(system, user, trace_id=runtime.trace_id, stage='knowledge_extract', reasoning_effort='low', output_spec=spec))
        except ValueError as exc:
            claims = parse(client.complete_json(system, user + '\n\n## 上次输出不符合要求\n' + str(exc)[:600] + '\n请只修正这一点，重新输出只含 claims 键的 JSON。',
                                                trace_id=runtime.trace_id, stage='knowledge_extract', reasoning_effort='low', output_spec=spec))
    finally:
        merge_usage(usage, client.usage())
    return [{'item_id': c['claim_id'], 'kind': 'claim', 'text': c['text'], 'context': c['context']} for c in claims]


if VARIANT == 'new':
    object.__setattr__(tr.AXIS_TYPE, 'knowledge_items', extract_a1)
else:
    _parse = ex.parse_claims

    def counting(payload, output_text):
        try:
            return _parse(payload, output_text)
        except ValueError as exc:
            getattr(_local, 'rejections', []).append(str(exc)[:300])
            raise
    ex.parse_claims = counting
SPEC = load_project('llm_probe')
EXTRACT = tr.AXIS_TYPE.knowledge_items


def run_extract(item, rep):
    cid, scenario, trace = item[:3]
    _local.rejections = []
    runtime = AxisRuntime(spec=SPEC, run_id=f'a1-{VARIANT}-{rep}', trace_id=f'a1-{VARIANT}-{rep}:{cid}', scenario_id=scenario, case_id=cid,
                          enabled_axes=('knowledge_evidence', 'truthfulness'))
    usage = {'llm_calls': 0, 'tool_calls': 0}
    try:
        items, error = EXTRACT(trace, runtime, usage), ''
    except Exception as exc:
        items, error = [], str(exc)[:300]
    return {'rep': rep, 'claims': [{'text': i['text'], 'context': i['context']} for i in items], 'error': error,
            'rejections': list(_local.rejections), 'usage': usage}


def run_chain(item):
    cid, scenario, trace = item[:3]
    _local.rejections = []
    axes, _ = load_scenario_axes('llm_probe', scenario)
    chosen = [a for a in axes if a.type_id in ('knowledge_evidence', 'truthfulness')]
    results = [r.as_dict() for r in run_axes(SPEC, trace, chosen, scenario_id=scenario, run_id=f'a1-{VARIANT}-chain')]
    by = {r['type_id']: r for r in results}
    return {'rejections': list(_local.rejections),
            'axes': {k: {'status': r['status'], 'error': r['error'][:300], 'usage': r['usage'], 'elapsed_ms': common.elapsed_ms(r),
                         'output': r['output'] if k == 'truthfulness' else None} for k, r in by.items()}}


def task(item):
    cid = item[0]
    path = OUT / f'{cid}.json'
    if path.exists():
        return
    record = {'case_id': cid, 'group': item[3], 'expected': item[5], 'variant': VARIANT, 'answer': common.answer_of(item[2])}
    if MODE == 'extract':
        record['reps'] = [run_extract(item, r) for r in range(REPS)]
        print(cid, [len(r['claims']) for r in record['reps']], 'rej', [len(r['rejections']) for r in record['reps']], flush=True)
    else:
        record['chain'] = run_chain(item)
        t = record['chain']['axes'].get('truthfulness', {})
        print(cid, t.get('status'), [(c['verdict'], c['text'][:20], c['context']) for c in (t.get('output') or {}).get('claims') or []], flush=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    items = common.f_samples() + (common.samples() if WHICH == 'all' else [])
    with ThreadPoolExecutor(max_workers=6 if MODE == 'extract' else 4) as pool:
        for f in [pool.submit(task, it) for it in items]:
            f.result()
    print('done', flush=True)
