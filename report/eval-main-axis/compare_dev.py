"""开发集新旧对照：两版都按主轴结论映射三态计分，分场景命中、误放行 / 误杀、调用与耗时，逐条列出两版结论不同的样本。
用法：python compare_dev.py <旧 variant> <新 variant>"""
import json, statistics, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
TRI = {'做成了': 'fulfilled', '没做成': 'not_fulfilled', '做不了': 'not_fulfilled', '不确定': 'not_evaluable'}
SHORT = {'fulfilled': 'F', 'not_fulfilled': 'NF', 'not_evaluable': 'NE', 'run_failed': '无结论'}
GOLD = json.loads((HERE / 'gold.json').read_text())
SCENARIO = {json.loads(f.read_text())['id']: json.loads(f.read_text())['scenario'] for f in (HERE / 'cases').glob('*.json')}


def load(variant):
    rows = {}
    for line in (HERE / 'runs' / variant / 'results.jsonl').read_text().splitlines():
        r = json.loads(line)
        r['tri'] = TRI.get((r.get('main_verdict') or {}).get('verdict'), 'run_failed')
        accept = GOLD[r['prompt_id']].get('accept') or [GOLD[r['prompt_id']]['gold']]
        r['hit'] = r['tri'] in accept
        r['false_pass'] = r['tri'] == 'fulfilled' and 'fulfilled' not in accept
        r['false_kill'] = 'fulfilled' in accept and r['tri'] != 'fulfilled' and not r['hit']
        rows[r['prompt_id']] = r
    return rows


def stats(rows):
    by = defaultdict(lambda: [0, 0])
    for r in rows.values():
        by[SCENARIO[r['prompt_id']]][0] += r['hit']
        by[SCENARIO[r['prompt_id']]][1] += 1
    return {'n': len(rows), 'hit': sum(r['hit'] for r in rows.values()),
            'by_scenario': {k: f'{a}/{b}' for k, (a, b) in sorted(by.items())},
            'false_pass': sum(r['false_pass'] for r in rows.values()), 'false_kill': sum(r['false_kill'] for r in rows.values()),
            'no_conclusion': sum(r['tri'] == 'run_failed' for r in rows.values()),
            'llm_calls_mean': round(statistics.mean(r['llm_calls'] for r in rows.values()), 1),
            'latency_median_s': statistics.median(r['latency_s'] for r in rows.values())}


if __name__ == '__main__':
    old, new = load(sys.argv[1]), load(sys.argv[2])
    common = sorted(set(old) & set(new))
    print('共同样本', len(common))
    print('旧', json.dumps(stats({k: old[k] for k in common}), ensure_ascii=False))
    print('新', json.dumps(stats({k: new[k] for k in common}), ensure_ascii=False))
    print('\n两版结论不同的样本（标准 / 旧 / 新）：')
    for k in common:
        if old[k]['tri'] != new[k]['tri']:
            g = SHORT[GOLD[k]['gold']]
            print(f"  {k} [{SCENARIO[k]}] 标准 {g} / 旧 {SHORT[old[k]['tri']]}{'✓' if old[k]['hit'] else '✗'} / 新 {SHORT[new[k]['tri']]}{'✓' if new[k]['hit'] else '✗'}")
