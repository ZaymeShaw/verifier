"""同一歧义组的互斥读法 blocking 一致（同 llm_probe 兑现轴 BLOCKING_SYSTEM 的要求）。"""


def check(view):
    groups = {}
    for e in view.materials["result.expectations"]["expectations"]:
        if e.get("ambiguity_group"):
            groups.setdefault(e["ambiguity_group"], []).append(e["expectation_id"])
    blocking = {i["expectation_id"]: i["blocking"] for i in view.own["items"]}
    return [f"歧义组 {g} 的互斥读法 {ids} blocking 必须一致" for g, ids in groups.items()
            if len({blocking.get(i) for i in ids}) > 1]
