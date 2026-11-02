"""承载性：每条没给到的期望换成归位（同 llm_probe 承载性轴的 placements，主轴 main_verdict 照读）。"""
PLACEMENT = {"no": "做不了", "yes": "做错了", "undecidable": "说不清"}


def synthesize(view):
    placements = [{"expectation_id": j["expectation_id"], "placement": PLACEMENT[j["carry"]], "reason": j["reason"],
                   "citations": [{"ref": b["ref"], "note": b["quote"]} for b in j["basis"]],
                   "gap_kind": j["gap_kind"], "missing_material": j["missing_material"]} for j in view.own["judgments"]]
    found = {p["placement"] for p in placements}
    verdict = "做错了" if "做错了" in found else "做不了" if found == {"做不了"} else "说不清"
    return {"verdict": verdict, "placements": placements}
