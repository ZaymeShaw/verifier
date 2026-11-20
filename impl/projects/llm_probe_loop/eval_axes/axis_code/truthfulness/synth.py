"""真实性：每条说法合上判定，给兑现与主轴读（字段同 llm_probe 真实性轴的 claims）；轴级 verdict 只作摘要。"""
VERDICTS = ("verified", "refuted", "unverifiable")


def synthesize(view):
    judged = {j["claim_id"]: j for j in view.own["judgments"]}
    claims = []
    for c in view.materials["result.claims"]["claims"]:
        j = judged[c["claim_id"]]
        claims.append({"claim_id": c["claim_id"], "text": c["claim"], "spans": c["spans"], "context": c["context"],
                       "qualifies": c["qualifies"], "verdict": j["verdict"], "reason": j["reason"], "gap": j["gap"],
                       "citations": [{"ref": b["ref"], "note": b["quote"]} for b in j["basis"]]})
    coverage = {"extracted": len(claims), **{v: sum(c["verdict"] == v for c in claims) for v in VERDICTS}}
    verdict = ("no_claims" if not claims else "has_refuted" if coverage["refuted"] else
               "has_unverifiable" if coverage["unverifiable"] else "all_verified")
    return {"verdict": verdict, "claims": claims, "coverage": coverage}
