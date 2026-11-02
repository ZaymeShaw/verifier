"""兑现轴新旧对照汇总：效果（对标准答案、分场景、两轮一致率）、效率（调用、token、耗时）、质量（期望条数、混进来的系统规则类期望）。
用法：python ab_report.py old new"""
import json, re, statistics, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
GOLD = json.loads((HERE / 'runs-ab/gold-regression.json').read_text())
# 能力描述里的系统规则 / 行为规范被写成期望的痕迹（08-30 分析 B1、B2 那一类）
RULE_LIKE = re.compile(r'SSE|卡片|拒绝|不支持|如实|追问|澄清|多轮|不编造')
TOKENS = re.compile(r'\[Token usage\] ([\d,]+) in \+ ([\d,]+) out')


def tokens(variant):
    """并发跑时 Token usage 行分不清属于哪条，只取全量合计；另取墙钟总耗时。"""
    total_in = total_out = 0
    wall = None
    for line in (HERE / f'runs-ab-{variant}.log').read_text().splitlines():
        m = TOKENS.search(line)
        if m:
            total_in += int(m.group(1).replace(',', ''))
            total_out += int(m.group(2).replace(',', ''))
        elif line.startswith('wall_clock_s'):
            wall = float(line.split()[1])
    return total_in, total_out, wall


def summarize(variant):
    rows = [json.loads(x) for x in (HERE / f'runs-ab/{variant}.jsonl').read_text().splitlines()]
    rows = [r for r in rows if not GOLD[r['case_id']].get('exclude')]  # 标准答案待定的不计分
    tok_in, tok_out, wall = tokens(variant)
    by_scn = defaultdict(lambda: [0, 0])
    by_case = defaultdict(list)
    for r in rows:
        accept = GOLD[r['case_id']].get('accept') or [GOLD[r['case_id']]['gold']]
        r['hit'] = r['verdict'] in accept
        by_scn[r['scenario']][0] += r['hit']
        by_scn[r['scenario']][1] += 1
        by_case[r['case_id']].append(r['verdict'])
    n = len(rows)
    agree = sum(len(set(v)) == 1 for v in by_case.values())
    exp = [e for r in rows for e in r['expectations']]
    return {
        'variant': variant, 'n': n,
        'hit': sum(r['hit'] for r in rows), 'by_scenario': {k: f'{a}/{b}' for k, (a, b) in by_scn.items()},
        'failed_runs': sum(r['status'] != 'succeeded' for r in rows),
        'two_rep_agree': f'{agree}/{len(by_case)}',
        'llm_calls_mean': round(statistics.mean((r['usage'] or {}).get('llm_calls', 0) for r in rows), 2),
        'tokens_in_per_case': round(tok_in / n), 'tokens_out_per_case': round(tok_out / n), 'wall_clock_s': wall,
        'latency_median_s': statistics.median(r['latency_s'] for r in rows),
        'latency_mean_s': round(statistics.mean(r['latency_s'] for r in rows), 1),
        'expectations_per_case': round(len(exp) / n, 2),
        'blocking_per_case': round(sum(bool(e['blocking']) for e in exp) / n, 2),
        'rule_like_expectations': sum(bool(RULE_LIKE.search(str(e['outcome']))) for e in exp),
        'models': sorted({(r['usage'] or {}).get('llm_model', '') for r in rows}),
        'misses': sorted({(r['case_id'], r['rep'], r['verdict']) for r in rows if not r['hit']}),
    }


if __name__ == '__main__':
    for v in sys.argv[1:]:
        print(json.dumps(summarize(v), ensure_ascii=False, indent=1))
