"""tool_execution 本应清单是分析产物：取分到的那一份（本应走分组分发），verdict 只说写好了。"""


def synthesize(view):
    expected = [x for p in view.parts for x in p["result"]["expected"]]
    not_covered = [x for p in view.parts for x in p["result"]["not_covered"]]
    return {"verdict": "ready", "reason": f"{len(expected)} 条本应，{len(not_covered)} 项未覆盖",
            "expected": expected, "not_covered": not_covered}
