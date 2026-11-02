"""主轴最终结论：兑现（C）与承载性（J）的确定性合成，不调模型、可复算。

规则见 spec/math-abstract/judge.md §3.1，需求见 demand/main_axis.md §2–§4。
只读两者的结论，不读交付与资料（不新增揣测通道）。核事实（K）只经兑现的逐条期望起作用（含隐性期望"回答里的事实都对"）；
blocking 为空的期望（挡不挡看这次错成什么样）不决定结论，没达到的列进组成 pending_unmet（2026-10-25）。
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

DONE, NOT_DONE, CANNOT, UNSURE = "做成了", "没做成", "做不了", "不确定"
_CANNOT, _WRONG = "做不了", "做错了"


def _output(result: Mapping[str, Any] | None) -> Mapping[str, Any]:
    output = (result or {}).get("output")
    return output if isinstance(output, Mapping) else {}


def _with_basis(item: Mapping[str, Any]) -> str:
    return f"{item['expectation_id']}（{item['status_basis']}）" if item["status_basis"] else str(item["expectation_id"])


def _unmet_text(unmet: Sequence[Mapping[str, Any]]) -> str:
    """没兑现的分开写：给了但错了（附兑现的程序依据）、没给到（demand/main_axis.md §4.3、M9）。"""
    wrong = [_with_basis(i) for i in unmet if i["delivered"] == "给了"]
    missing = [str(i["expectation_id"]) for i in unmet if i["delivered"] != "给了"]
    return "；".join(([f"给错了：{'、'.join(wrong)}"] if wrong else []) + ([f"没给到：{'、'.join(missing)}"] if missing else []))


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
    claims_checked = truth.get("status") == "succeeded"
    carry = by_type.get("carryability") or {}
    placements = {p.get("expectation_id"): p for p in _output(carry).get("placements") or []
                  if isinstance(p, Mapping)} if carry.get("status") == "succeeded" else {}
    blocking = {e.get("expectation_id"): e.get("blocking") for e in c.get("business_expectations") or []}
    items = []
    for a in c.get("fulfillment_assessments") or []:
        key = a.get("expectation_id")
        placement = placements.get(key) or {}
        if a.get("other_reading_fulfilled"):
            continue  # 歧义组里另一种读法已给到，这一读法不计（spec/alg/fulfilled.md §1）
        items.append({"expectation_id": key, "status": a.get("status"), "blocking": blocking.get(key),
                      "delivered": a.get("delivered") or "", "status_basis": a.get("status_basis") or "",
                      "placement": placement.get("placement") or "", "claim_refs": list(a.get("claim_refs") or []),
                      "process_refs": list(a.get("process_refs") or []), "evidence_tier": list(a.get("evidence_tier") or []),
                      "missing_evidence": list(a.get("missing_evidence") or [])})
    unmet = [i for i in items if i["blocking"] is True and i["status"] == "not_fulfilled"]
    unsure = [i for i in items if i["blocking"] is True and i["status"] not in ("fulfilled", "not_fulfilled")]
    pending = [i["expectation_id"] for i in items if i["blocking"] is None and i["status"] != "fulfilled"]
    composition = {"items": items, "pending_unmet": pending, "capability_undetermined": False,
                   "claims_checked": claims_checked}

    def done(verdict: str, basis: str, **extra: Any) -> dict[str, Any]:
        note = f"；待定项没达到：{'、'.join(pending)}（挡不挡看这次错成什么样，做成 / 没做成都可）" if pending else ""
        return {"verdict": verdict, "basis": basis + note, "composition": {**composition, **extra}}

    # 规则 1：用户要的没给到（没给，或给了但错了），按承载性分做不了 / 没做成。
    if unmet:
        what = _unmet_text(unmet)
        found = [i["placement"] for i in unmet]
        if not all(found):
            return done(NOT_DONE, f"{what}；能不能做没区分（承载性没开或没判）", capability_undetermined=True)
        if _WRONG in found:
            return done(NOT_DONE, f"{what}；系统本可以给出")
        if all(p == _CANNOT for p in found):
            return done(CANNOT, f"{what}；有依据表明系统正常工作时也给不出")
        # ⟡ demand/main_axis.md ⟡2：有依据来源但仍分不清时，暂按没做成，注明没分清。
        return done(NOT_DONE, f"{what}；能不能做没分清", capability_undetermined=True)
    # 规则 2：材料不够——用户要的核实不了。
    if unsure:
        return done(UNSURE, "材料不够：" + "、".join(_with_basis(i) for i in unsure) + " 判断不了")
    return done(DONE, "用户要的都给到了" + ("" if claims_checked else "；事实属实未核"))
