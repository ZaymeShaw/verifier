"""汇总一个或多个 variant 的评测结果，写 runs/<variant>/report.md：命中率（开发集 / 验收集分开，带 95% 区间）、
误放行、误杀、三态混淆表、判错清单（附主判理由）。用法：python report.py <variant> [<variant> ...]"""
import json, math, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
STATES = ('fulfilled', 'not_fulfilled', 'not_evaluable')
SHORT = {'fulfilled': 'F', 'not_fulfilled': 'NF', 'not_evaluable': 'NE'}
TRI = {'做成了': 'fulfilled', '没做成': 'not_fulfilled', '做不了': 'not_fulfilled', '不确定': 'not_evaluable'}


def ci(k, n):
    """Wilson 95% 区间。"""
    if not n:
        return '—'
    k = int(k)
    p, z = k / n, 1.96
    mid, half = (p + z * z / (2 * n)) / (1 + z * z / n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f'{k}/{n} = {p:.0%}（{max(0, mid - half):.0%}–{min(1, mid + half):.0%}）'


def report(variant):
    d = HERE / 'runs' / variant
    rows = [json.loads(x) for x in (d / 'results.jsonl').read_text().splitlines()]
    errors = [json.loads(x) for x in (d / 'errors.jsonl').read_text().splitlines()] if (d / 'errors.jsonl').exists() else []
    done = {(r['prompt_id'], r['rep']) for r in rows}
    errors = [e for e in errors if (e['prompt_id'], e['rep']) not in done]
    gold = json.loads((HERE / 'gold.json').read_text())
    for r in rows:
        # 2026-10-20 起附带说法在 M 里挡（spec/math-abstract/judge.md §3.1）：有主轴结论就按它的三态计分；
        # 运行失败（M 无结论）记 other。旧 variant 没有这个字段，仍按兑现轴的结论计。
        if 'main_verdict' in r:
            r['fulfillment_pred'] = r['pred']
            r['pred'] = TRI.get((r['main_verdict'] or {}).get('verdict'), 'run_failed')
    for r in rows:  # 按当前 gold.json 重新计分：标准答案改了（或允许多个结论）不用重跑
        accept = gold[r['prompt_id']].get('accept') or [gold[r['prompt_id']]['gold']]
        r['gold'] = gold[r['prompt_id']]['gold']
        r['grade'] = {'hit': float(r['pred'] in accept), 'false_pass': float(r['pred'] == 'fulfilled' and 'fulfilled' not in accept),
                      'false_kill': float('fulfilled' in accept and r['pred'] != 'fulfilled' and r['pred'] not in accept)}
    L = [f'# 主轴三态评测：{variant}', '', f'结果 {len(rows)} 行，未完成（报错 / 超时）{len(errors)} 行。', '',
         '| 集 | 命中率 | 误放行（不该办成判了办成） | 误杀（该办成没判办成） |', '|---|---|---|---|']
    for split in ('dev', 'holdout', 'all'):
        rs = [r for r in rows if split in ('all', r['split'])]
        n = len(rs)
        neg = [r for r in rs if r['gold'] != 'fulfilled']
        pos = [r for r in rs if r['gold'] == 'fulfilled']
        L.append(f"| {split} | {ci(sum(r['grade']['hit'] for r in rs), n)} | "
                 f"{ci(sum(r['grade']['false_pass'] for r in neg), len(neg))} | {ci(sum(r['grade']['false_kill'] for r in pos), len(pos))} |")
    L += ['', '## 三态混淆（行 = 标准答案，列 = 主判）', '', '| 标准 \\ 主判 | F | NF | NE | 其他 |', '|---|---|---|---|---|']
    cm = Counter((r['gold'], r['pred'] if r['pred'] in STATES else 'other') for r in rows)
    for g in STATES:
        L.append(f'| {SHORT[g]} | ' + ' | '.join(str(cm[(g, p)]) for p in (*STATES, 'other')) + ' |')
    calls = [r['llm_calls'] for r in rows]
    lat = [r['latency_s'] for r in rows]
    if rows:
        L += ['', f'模型调用：共 {sum(calls)} 次，每条中位 {sorted(calls)[len(calls) // 2]}（{min(calls)}–{max(calls)}）；'
                  f'耗时每条中位 {sorted(lat)[len(lat) // 2]} s（{min(lat)}–{max(lat)} s）。']
    miss = sorted((r for r in rows if not r['grade']['hit']), key=lambda r: (r['split'], r['prompt_id']))
    L += ['', f'## 判错 {len(miss)} 条', '']
    for r in miss:
        L += [f"### {r['prompt_id']}（{r['split']}，标准 {SHORT[r['gold']]} → 主判 {SHORT.get(r['pred'], r['pred'])}）", '',
              f"- 标准答案理由：{gold[r['prompt_id']]['why']}",
              f"- 主判写的期望：{'；'.join(str(e['expected_outcome']) for e in r['expectations'])[:400]}",
              f"- 主判理由：{r['reasoning'][:600]}",
              f"- 说法核验：{'；'.join(c['verdict'] + ' ' + str(c['text'])[:40] for c in r['claims'])[:400] or '无'}", '']
    if errors:
        L += ['## 未完成', ''] + [f"- {e['prompt_id']} rep{e['rep']}：{e['failure_class']} {e['error'][:200]}" for e in errors]
    (d / 'report.md').write_text('\n'.join(L) + '\n')
    print('\n'.join(L[:12]))


if __name__ == '__main__':
    for v in sys.argv[1:]:
        report(v)
