"""承载性逐条判定的依据（spec/alg/axis_loop.md §12.3，需求 main_axis.md §3.3）：只能是本轴描述（登记的责任范围）原文，
或这次 search_knowledge 查到的原文；查询报错、这一条没找到的那次不算依据。"""
from impl.core.axis_loop.checks import SUBLOOP_CATEGORY, usable
from impl.core.axis_loop.text import leaves, quote_in_text

NOTE = "axis.note"


def _cite(view, ref, quote, item_id):
    if ref == NOTE:
        return "" if quote_in_text(quote, view.materials.get(NOTE) or "") else f"引句 {quote[:40]!r} 没有逐字出现在本轴描述里"
    why = usable(view, ref, SUBLOOP_CATEGORY, "search_knowledge")
    if why:
        return f"引用的 {ref} {why}"
    call = view.call(ref)
    found = next((i for i in (call.structured or {}).get("items") or [] if i.get("item_id") == item_id), None)
    if found is None or found.get("status") != "found":
        return f"{ref} 那次没有为 {item_id} 找到原文，不能当依据"
    if not any(quote_in_text(quote, t) for t in [call.text, *leaves(call.structured)]):
        return f"引句 {quote[:40]!r} 没有逐字出现在 {ref} 的返回里；照返回原文摘，不改写、不拼接"
    return ""


def check(view):
    if view.stage != "item":
        return []
    own = view.own
    if own["carry"] == "undecidable":
        if own["basis"] or not own["gap_kind"] or not own["missing_material"].strip():
            return ["carry=undecidable 时 basis 为空，gap_kind 与 missing_material 必填"]
        return []
    if not own["basis"]:
        return [f"carry={own['carry']} 必须引用本轴描述或 search_knowledge 查到的原文"]
    problems = [_cite(view, b["ref"], b["quote"], own["expectation_id"]) for b in own["basis"]]
    return [p for p in problems if p]
