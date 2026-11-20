"""过程六轴的本应分组同做（spec/alg/axis_loop.md §12.2.2）：同一组一个上下文，只按真实先后排队——
A 的输出端出现在 B 的本应材料里，A 交了 B 才出现、A 随即锁住；没先后的同时出现、可以一次交。
排不开先后（成环）的分到别的组。分组按 result.trace_analysis.feeds 每个 case 现算：组数最少，同组数取轮数最少。"""

SUFFIX = "_expected"


def _depth(group, edges):
    """组内要排几轮（最长先后链的长度）；有环返回 None。"""
    rest, rounds = set(group), 0
    while rest:
        free = {a for a in rest if not any(f in rest and t == a for f, t in edges)}
        if not free:
            return None
        rest -= free
        rounds += 1
    return rounds


def _partitions(items):
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for p in _partitions(rest):
        for i in range(len(p)):
            yield p[:i] + [[first] + p[i]] + p[i + 1:]
        yield [[first]] + p


def groups(axes, edges):
    """组数最少、每组无环的分法（六个轴最多 203 种，穷举），同组数取各组轮数之和最少的；返回各组（按轴原顺序）。"""
    best, best_key = None, None
    for p in _partitions(list(axes)):
        depths = [_depth(g, edges) for g in p]
        if None in depths:
            continue
        key = (len(p), sum(depths))
        if best_key is None or key < best_key:
            best, best_key = p, key
    return sorted((sorted(g, key=axes.index) for g in best), key=lambda g: axes.index(g[0]))


def dispatch(view):
    axes = [t[: -len(SUFFIX)] for t in view.params["tasks"]]
    edges = {(f["from"], f["to"]) for f in view.materials["result.trace_analysis"]["feeds"]}
    return [{"id": f"g{i}", "tasks": [a + SUFFIX for a in g],
             "after": sorted([f + SUFFIX, t + SUFFIX] for f, t in edges if f in g and t in g)}
            for i, g in enumerate(groups(axes, edges), 1)]
