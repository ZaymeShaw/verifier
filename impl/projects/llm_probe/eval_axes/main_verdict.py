"""主轴最终结论：兑现（C）、承载性（J）与可选的核事实（K）的确定性合成，不调模型、可复算。

规则见 spec/math-abstract/judge.md §3.1，需求见 demand/main_axis.md §2–§4。
只读三者的结论，不读交付与资料（不新增揣测通道）。K 没开时照样出结论，只是少叠加一层。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

DONE, NOT_DONE, CANNOT, UNSURE = "做成了", "没做成", "做不了", "不确定"
_CANNOT, _WRONG = "做不了", "做错了"


def _output(result: Mapping[str, Any] | None) -> Mapping[str, Any]:
    output = (result or {}).get("output")
    return output if isinstance(output, Mapping) else {}


def blocking_claims(claims: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    """交付里说错的、核实不了的事实（demand/main_axis.md §2.5）。修饰数值的说法（单位、币种、时点）核实不了、
    而它修饰的数值已核实时不挡（§2.6）。"""
    by_id = {c.get("claim_id"): c for c in claims}
    refuted = [c["claim_id"] for c in claims if c.get("verdict") == "refuted"]
    unverified = [c["claim_id"] for c in claims if c.get("verdict") == "unverifiable"
                  and not (c.get("qualifies") and (by_id.get(c["qualifies"]) or {}).get("verdict") == "verified")]
    return refuted, unverified


def main_verdict(results: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """results 是 run_axes 的 AxisResult.as_dict() 列表。兑现没跑成（没开 / 失败）→ None：记运行失败，不出结论。"""
    by_type = {r.get("type_id"): r for r in results}
    fulfillment = by_type.get("fulfillment") or {}
    if fulfillment.get("status") != "succeeded":
        return None
    c = _output(fulfillment)
    truth = by_type.get("truthfulness") or {}
    if truth.get("status") in ("failed", "blocked"):
        # 开了核事实却没跑成：不能当成"没开"放过（judge.md §3.1 规则 0）。
        return None
    claims = list(_output(truth).get("claims") or []) if truth.get("status") == "succeeded" else None
    carry = by_type.get("carryability") or {}
    placements = {p.get("expectation_id"): p for p in _output(carry).get("placements") or []
                  if isinstance(p, Mapping)} if carry.get("status") == "succeeded" else {}
    blocking = {e.get("expectation_id"): bool(e.get("blocking")) for e in c.get("business_expectations") or []}
    items = []
    for a in c.get("fulfillment_assessments") or []:
        key = a.get("expectation_id")
        placement = placements.get(key) or {}
        if a.get("other_reading_fulfilled"):
            continue  # 歧义组里另一种读法已给到，这一读法不计（spec/alg/fulfilled.md §1）
        items.append({"expectation_id": key, "status": a.get("status"), "blocking": blocking.get(key, False),
                      "placement": placement.get("placement") or "", "claim_refs": list(a.get("claim_refs") or [])})
    refuted, unverified = blocking_claims(claims) if claims is not None else ([], [])
    unmet = [i for i in items if i["blocking"] and i["status"] == "not_fulfilled"]
    unsure = [i for i in items if i["blocking"] and i["status"] != "fulfilled" and i["status"] != "not_fulfilled"]
    composition = {"items": items, "blocked_by_claims": [], "capability_undetermined": False,
                   "claims_checked": claims is not None}

    def done(verdict: str, basis: str, **extra: Any) -> dict[str, Any]:
        return {"verdict": verdict, "basis": basis, "composition": {**composition, **extra}}

    # 规则 1：交付里说了错话，不管用户要的那部分给到没有，都是没做成（main_axis §2.5）。
    if refuted:
        return done(NOT_DONE, "交付里有事实被信息源否定", blocked_by_claims=refuted)
    # 规则 2：用户要的没给到，按承载性分做不了 / 没做成。
    if unmet:
        found = [i["placement"] for i in unmet]
        if not all(found):
            return done(NOT_DONE, "没给到；能不能做没区分（承载性没开或没判）", capability_undetermined=True)
        if _WRONG in found:
            return done(NOT_DONE, "没给到；系统本可以给出")
        if all(p == _CANNOT for p in found):
            return done(CANNOT, "没给到；有依据表明系统正常工作时也给不出")
        # ⟡ demand/main_axis.md ⟡2：有依据来源但仍分不清时，暂按没做成，注明没分清。
        return done(NOT_DONE, "没给到；能不能做没分清", capability_undetermined=True)
    # 规则 3：材料不够——用户要的核实不了，或交付里有事实核实不了。
    if unsure or unverified:
        return done(UNSURE, "材料不够：" + "；".join(filter(None, (
            "期望 " + "、".join(i["expectation_id"] for i in unsure) + " 判断不了" if unsure else "",
            "事实 " + "、".join(unverified) + " 核实不了" if unverified else ""))),
            blocked_by_claims=unverified)
    return done(DONE, "用户要的都给到了" + ("，交付里的事实都核实为对" if claims is not None else "；事实属实未核"))
