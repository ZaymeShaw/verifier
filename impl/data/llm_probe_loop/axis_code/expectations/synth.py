"""需求轴：合并各轮的期望，编号带轮次前缀、全案唯一（同 llm_probe 需求轴）。"""


def synthesize(view):
    material = view.materials["case.requirements"]
    expectations = [{**e, "expectation_id": f"{p['id']}.{e['expectation_id']}", "turn": p["id"]}
                    for p in view.parts for e in p["result"]["expectations"]]
    reason = "；".join(f"{p['id']}：{p['result']['reason']}" for p in view.parts)
    return {"verdict": "partial" if material["missing"] else "complete", "reason": reason, "expectations": expectations,
            "sources": material["sources"], "missing": material["missing"]}
