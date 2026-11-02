"""Item-level equivalence between two lists of "本应产出" statements for the same (case, axis).

Pairs: B1-vs-B2 (does the same method give the same list twice?) and A-vs-B1 / A-vs-B2 (hand-written vs blind).
Both directions in one call. "Equivalent" is strict: checking either item against the run would give the same conclusion.
usage: python match_items.py <provider> [workers] [strict|lenient]
  strict  = checking either item against the run would give the same conclusion (lower bound of agreement)
  lenient = both items watch the same thing, even if one is more general / more specific (upper bound)
"""
import concurrent.futures as cf, json, sys
import blind_pass as b

AX = ['intent_understanding', 'planning_routing', 'tool_execution', 'knowledge_data', 'model_capability', 'context_memory']
PROMPT = """下面是同一个部件、同一次运行的两份“本应产出”清单（X 与 Y），由不同的人/不同的次数各自独立写成。请判断它们的条目是否一一对应。

{rule}一条 X 可以对应多条 Y 时，选最贴近的一条。

只输出一个 JSON 对象，不要任何其他文字：
{{"x_to_y": {{"<X的id>": "<Y的id或null>", ...}}, "y_to_x": {{"<Y的id>": "<X的id或null>", ...}}}}

===== X =====
{x}

===== Y =====
{y}"""


RULES = {
    'strict': "判定“等价”要严格：两条要求的是**同一件事**——拿去核对运行记录，会得到同样的结论。只是话题相同、粒度不同、或一条包含另一条的一部分，都不算等价（写 null）。",
    'lenient': "判定“等价”用宽松口径：只要两条在核对时**盯着的是同一件事**（同一个对象、同一种性质）就算，哪怕一条更概括、一条更具体，措辞不同，或其中一条多带了前提、例子。只是话题沾边、但盯的对象不同，不算（写 null）。",
}


def items(kind, c, a):
    if kind == 'A':
        return [dict(id=i['id'], statement=i['statement']) for i in json.load(open(b.HERE / 'A_items.json'))[c][a]]
    rep = kind[1]
    return [dict(id=i['id'], statement=i['statement']) for i in json.load(open(b.HERE / f'B_runs/deepseek_rep{rep}/{c}/{a}/frozen_items.json'))['items']]


def fmt(lst):
    return '\n'.join(f"[{i['id']}] {i['statement'][:220]}" for i in lst)


if __name__ == '__main__':
    b.use_provider(sys.argv[1]); workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    mode = sys.argv[3] if len(sys.argv) > 3 else 'strict'
    b.MAX_TOKENS = 64000
    out = b.HERE / 'B_runs' / ('match' if mode == 'strict' else 'match_lenient'); out.mkdir(exist_ok=True)
    jobs = []
    for c in ('renyanlin', 'D01'):
        for a in AX:
            for x, y in (('B1', 'B2'), ('A', 'B1'), ('A', 'B2')):
                jobs.append((f'{x}_{y}_{c}_{a}', PROMPT.format(rule=RULES[mode], x=fmt(items(x, c, a)), y=fmt(items(y, c, a)))))
    with cf.ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda j: b.ask(j[1], out / f'{j[0]}.json', 'x_to_y'), jobs))
    print('match done', sum(r is not None for r in res), '/', len(res))
