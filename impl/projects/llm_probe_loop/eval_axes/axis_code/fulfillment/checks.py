"""兑现逐条引用的程序检查（spec/alg/fulfilled.md §4）：claim_refs 存在；所引说法有出处在这条期望的轮次。"""


def check(view):
    truth = view.materials.get("result.truthfulness")
    claims = {c["claim_id"]: {s["turn"] for s in c["spans"]} for c in (truth or {}).get("claims") or []}
    turn_of = {e["expectation_id"]: e["turn"] for e in view.materials["result.expectations"]["expectations"]}
    problems = []
    for item in view.own["assessments"]:
        key = item["expectation_id"]
        unknown = [r for r in item["claim_refs"] if r not in claims]
        if unknown:
            problems.append(f"{key}：claim_refs {unknown} 不在核事实结果里" if truth else f"{key}：没有核事实结果，claim_refs 必须为空")
        other_turn = [r for r in item["claim_refs"] if r in claims and turn_of[key] not in claims[r]]
        if other_turn:
            problems.append(f"{key}：claim_refs {other_turn} 的出处都不在第 {turn_of[key]} 轮，只引出处里有本轮的说法")
    return problems
