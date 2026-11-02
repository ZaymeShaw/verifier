"""主轴三态评测：把样本冻结成自包含文件（cases/<id>.json），评测只读这些文件，不依赖 scratchpad 与 8031 实例里会变的数据。

来源：report/fact-claims-20261018 的 38 条（A 条款 5、B 员工手册 11、C 保险 MCP 2、D 单位 2、F 短答 5、H 8031 MCP 13），
加 8031 汇总页 verify-insurance-mcp/agno/langfuse 最新一次跑出的真实回答（问题+回答与已有样本完全相同的去重）。
评测链路统一走 verify-insurance-mcp 场景（agno/langfuse 的回答只当输入用，信息源相同）。
用法：python freeze_cases.py（在 verifier-integrate 的 Python 环境下）
"""
import json, random, sqlite3, sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / 'fact-claims-20261018'))
import common  # noqa: E402  （会把 verifier-integrate 加进 sys.path）

DB = common.CODE / '.runtime/instances/inst-f105511930554648/data/latest_runs.sqlite3'
H_DIRS = [HERE.parent / 'fact-claims-20261018/out/h-samples', HERE.parent / 'fact-claims-20261018/out/c1-samples']
HOLDOUT_SHARE, SEED = 0.3, 20261020


def user_turns(trace):
    turns = [m.get('query') or m.get('content') for m in trace.get('conversation_transcript') or [] if m.get('role') == 'user']
    if turns:
        return turns
    body = (trace.get('normalized_request') or {}).get('body') or {}
    messages = (body.get('input') or {}).get('messages') if isinstance(body.get('input'), dict) else body.get('messages')
    return [m.get('content') for m in messages or [] if m.get('role') == 'user']


def rebuild_records(trace):
    """common 的合成样本只改了请求和答复、没改模板带来的对话记录与逐轮记录；按请求和答复重建，
    否则需求轴、兑现轴读到的是模板的问题和答复，而核事实读的是合成答复。"""
    body = trace['normalized_request']['body']
    messages = (body.get('input') or {}).get('messages') if isinstance(body.get('input'), dict) else body.get('messages')
    trace['conversation_transcript'] = [{'role': 'user', 'content': m['content'], 'query': m['content']} for m in messages if m.get('role') == 'user']
    trace['turn_records'] = [{'turn_index': 1, 'request': trace['normalized_request'],
                              'extracted_output': trace['extracted_output'], 'project_fields': {}}]


def fix_frozen():
    """已冻结的合成样本补同一处重建（不重新冻结，样本集与留出不变）。"""
    for f in sorted((HERE / 'cases').glob('*.json')):
        case = json.loads(f.read_text())
        if case['source'] in ('fact-claims-H',) or not case['source'].startswith('fact-claims-'):
            continue
        rebuild_records(case['trace'])
        f.write_text(json.dumps(case, ensure_ascii=False, indent=1))
        print('fixed', case['id'])


def main():
    cases = []
    normalize, common.normalize_run_trace = common.normalize_run_trace, lambda t: t  # 取规范化前的原始 trace dict
    try:
        built = common.f_samples() + common.samples()
    finally:
        common.normalize_run_trace = normalize
    for cid, scenario, trace, group, *_ in built:
        rebuild_records(trace)
        cases.append({'id': cid + ('-1018' if group == 'C' else ''), 'source': 'fact-claims-' + group, 'scenario': scenario, 'trace': trace})
    for d in H_DIRS:
        for f in sorted(d.glob('*.json')):
            x = json.loads(f.read_text())
            cases.append({'id': x['case_id'].replace('verify-insurance-', ''), 'source': 'fact-claims-H', 'scenario': 'verify-insurance-mcp', 'trace': x['trace']})
    con = sqlite3.connect(DB)
    for case_json, run_json in con.execute('select case_json, run_json from current_cases where project = ?', ('llm_probe',)):
        case = json.loads(case_json)
        if not case.get('scenario', '').startswith('verify-insurance') or not run_json:
            continue
        trace = json.loads(run_json).get('trace')
        if trace and (trace.get('extracted_output') or {}).get('output_text'):
            cases.append({'id': case['id'].replace('verify-insurance-', '') + '-1020', 'source': '8031-' + case['scenario'].split('-')[-1],
                          'scenario': 'verify-insurance-mcp', 'trace': trace})
    unique, seen = [], set()
    for c in cases:  # 问题与回答完全相同的只留先出现的一条
        c['turns'] = user_turns(c['trace'])
        c['answer'] = common.answer_of(common.normalize_run_trace(c['trace']))
        key = (json.dumps(c['turns'], ensure_ascii=False), c['answer'])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    cases = unique
    assert len({c['id'] for c in cases}) == len(cases), '样本 id 重复'
    holdout = set(random.Random(SEED).sample(sorted(c['id'] for c in cases), round(len(cases) * HOLDOUT_SHARE)))
    for c in cases:
        c['split'] = 'holdout' if c['id'] in holdout else 'dev'
        (HERE / 'cases' / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False, indent=1))
    print(len(cases), 'cases;', sum(c['split'] == 'holdout' for c in cases), 'holdout')


if __name__ == '__main__':
    import sys
    fix_frozen() if sys.argv[1:] == ['--fix-records'] else main()
