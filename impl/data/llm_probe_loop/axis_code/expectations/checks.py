"""一轮的期望：结构与出处规则（同 llm_probe 需求轴 validate）。分发出去的每份只看到本轮的出处。"""
from collections import Counter


def check(view):
    sources = {s["id"]: s for s in view.materials["case.requirements"]["sources"]}
    problems, ids, groups = [], set(), Counter()
    for e in view.own["expectations"]:
        if not all(str(e[k]).strip() for k in ("expectation_id", "about", "statement", "condition")):
            problems.append("期望 id/关于/陈述/条件不能为空")
        if e["expectation_id"] in ids:
            problems.append(f"期望 id 重复：{e['expectation_id']}")
        ids.add(e["expectation_id"])
        if not e["source_refs"]:
            problems.append(f"期望 {e['expectation_id']} 没有出处")
        elif not any((sources.get(r) or {}).get("component") == "user" for r in e["source_refs"]):
            problems.append(f"期望 {e['expectation_id']} 必须引用本轮用户原话（component=user）；场景判准、历史、业务描述不能独立产生期望")
        if e["ambiguity_group"]:
            groups[e["ambiguity_group"]] += 1
        if any(len(set(g)) != len(g) for g in e["needs"]) or len({tuple(sorted(g)) for g in e["needs"]}) != len(e["needs"]):
            problems.append(f"期望 {e['expectation_id']} 的 needs 有重复：组内不重复写同一类，组之间不重复")
    if any(n < 2 for n in groups.values()):
        problems.append("歧义组至少两条互斥读法")
    if any(s["side"] == "want" for s in sources.values()) and not view.own["expectations"]:
        problems.append("有用户要求时不可提交空期望集")
    return problems
