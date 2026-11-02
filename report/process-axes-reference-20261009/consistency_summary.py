"""Item-level agreement between the three lists, under the strict and the lenient notion of "equivalent".
usage: python consistency_summary.py > consistency.md"""
import collections, json
import match_items as m

AX = ['intent_understanding', 'planning_routing', 'tool_execution', 'knowledge_data', 'model_capability', 'context_memory']
CASES = ('renyanlin', 'D01')
PAIRS = (('B1_B2', 'B1', 'B2'), ('A_B1', 'A', 'B1'), ('A_B2', 'A', 'B2'))
hit = lambda v: v not in (None, 'null', '')


def cover(mode, pair, x, y, c, a):
    r = json.load(open(m.b.HERE / f'B_runs/{mode}/{pair}_{c}_{a}.json'))['result']
    return len(m.items(x, c, a)), sum(map(hit, r['x_to_y'].values())), len(m.items(y, c, a)), sum(map(hit, r['y_to_x'].values()))


print('# 条目级一致性：同一方法写两遍 / 手写 vs 盲写\n')
print('「等价」有两种口径：**严格**=核对运行记录会得到同样结论（下限）；**宽松**=核对时盯着同一件事，允许一条更概括（上限）。配对由模型做（deepseek-flash），未人工复核全部，只抽查过一个轴，发现严格口径偏严。\n')
print('| 比较 | 口径 | 左边被右边覆盖 | 右边被左边覆盖 |')
print('|---|---|---|---|')
agg = collections.defaultdict(lambda: [0, 0, 0, 0])
for mode, label in (('match', '严格'), ('match_lenient', '宽松')):
    for pair, x, y in PAIRS:
        t = [0, 0, 0, 0]
        for c in CASES:
            for a in AX:
                for i, v in enumerate(cover(mode, pair, x, y, c, a)):
                    t[i] += v
        nx, mx, ny, my = t
        print(f'| {x} vs {y} | {label} | {x}：{mx}/{nx} = {mx / nx * 100:.0f}% | {y}：{my}/{ny} = {my / ny * 100:.0f}% |')
print('\n## 按轴（B1 vs B2，B1 被 B2 覆盖 / B2 被 B1 覆盖；严格 → 宽松）\n')
print('| case | 轴 | B1 被 B2 | B2 被 B1 |')
print('|---|---|---|---|')
for c in CASES:
    for a in AX:
        s = cover('match', 'B1_B2', 'B1', 'B2', c, a); l = cover('match_lenient', 'B1_B2', 'B1', 'B2', c, a)
        print(f'| {c} | {a} | {s[1]}/{s[0]} → {l[1]}/{l[0]} | {s[3]}/{s[2]} → {l[3]}/{l[2]} |')
print('\n## 按类型（B1 条目在 B2 里有等价条目的比例）\n')
print('| 类型 | 严格 | 宽松 |')
print('|---|---|---|')
tt = {mode: collections.defaultdict(lambda: [0, 0]) for mode in ('match', 'match_lenient')}
for mode in tt:
    for c in CASES:
        for a in AX:
            r = json.load(open(m.b.HERE / f'B_runs/{mode}/B1_B2_{c}_{a}.json'))['result']['x_to_y']
            typ = {i['id']: i['type'] for i in json.load(open(m.b.HERE / f'B_runs/deepseek_rep1/{c}/{a}/frozen_items.json'))['items']}
            for k, v in r.items():
                if typ.get(k):
                    tt[mode][typ[k]][0] += 1; tt[mode][typ[k]][1] += hit(v)
for ty in ('推出', '守恒', '外部真值'):
    f = lambda d: f'{d[ty][1]}/{d[ty][0]} = {d[ty][1] / d[ty][0] * 100:.0f}%'
    print(f'| {ty} | {f(tt["match"])} | {f(tt["match_lenient"])} |')
