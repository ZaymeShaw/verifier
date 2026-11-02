"""逐条判定：依据的那次取证里要有这一条；取证没找到的只能判 unverifiable，gap 照取证写（同 llm_probe 真实性）。"""


def check(view):
    if view.stage != "item":
        return []
    call = view.call(view.own["evidence_call"])
    items = {i["item_id"]: i for i in ((call.structured or {}).get("items") or [])} if call else {}
    found = items.get(view.own["claim_id"])
    if found is None:
        return [f"{view.own['evidence_call']} 那次 search_knowledge 没有查 {view.own['claim_id']}；先为这一条取证"]
    if found["status"] == "not_found" and (view.own["verdict"] != "unverifiable" or view.own["gap"] != found["gap"]):
        return [f"取证没找到相关原文（gap={found['gap']}），这一条只能判 unverifiable，gap 填 {found['gap']}"]
    return []
