"""兑现：模型只判交付给没给与引用，每条结果由程序按证据组派生（spec/alg/fulfilled.md §2.1）；
输出字段与整体状态同 llm_probe 兑现轴（主轴 M 函数照读）。"""
from impl.core.judge import _derive_overall_status
from impl.projects.llm_probe_loop.process_axes import process_rows

FULFILLED, NOT_FULFILLED, NOT_EVALUABLE = "fulfilled", "not_fulfilled", "not_evaluable"
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"


def _names(items, label):
    return "、".join(f"{key}（{label(item)}）" for key, item in items)


def _knowledge(refs, claims):
    """知识组：引用的说法有被否定的 → 不过；结果值的说法都核实了（修饰它的单位等核实不了不挡）→ 过；否则判不了。
    → (结果, 程序依据)。"""
    cited = [(r, claims[r]) for r in refs if r in claims]
    text = lambda c: c.get("text") or ""
    refuted = [(r, c) for r, c in cited if c["verdict"] == "refuted"]
    if refuted:
        return FAIL, "knowledge 组不过：" + _names(refuted, lambda c: f"有矛盾：{text(c)}")
    values = [(r, c) for r, c in cited if not c.get("qualifies")]
    if values and all(c["verdict"] == "verified" for _, c in values):
        return PASS, f"knowledge 组过：{len(values)} 条结果值说法都核实"
    if not values:
        return UNKNOWN, "knowledge 组判不了：没有引用结果值的说法"
    return UNKNOWN, "knowledge 组判不了：" + _names([(r, c) for r, c in values if c["verdict"] != "verified"],
                                                   lambda c: f"查不到：{text(c)}")


def _trace(refs, rows):
    """trace 组：引用的过程条目有没达到 → 不过（蒙的、查错对象、编造、传丢）；都达到 → 过；有无法核或没有条目 → 判不了。
    → (结果, 程序依据)。"""
    cited = [(r, rows[r]) for r in refs if r in rows]
    text = lambda row: f"{row['verdict']}：{row.get('statement') or ''}"
    failed = [(r, row) for r, row in cited if row["verdict"] == "没达到"]
    if failed:
        return FAIL, "trace 组不过：" + _names(failed, text)
    if cited and all(row["verdict"] == "达到" for _, row in cited):
        return PASS, f"trace 组过：{len(cited)} 条过程条目都达到"
    if not cited:
        return UNKNOWN, "trace 组判不了：没有可引的过程条目"
    return UNKNOWN, "trace 组判不了：" + _names([(r, row) for r, row in cited if row["verdict"] != "达到"], text)


def derive(item, needs, evidence, claims, rows):
    """→ (status, 档位, 缺的组, 程序依据)。"""
    if item["delivered"] == "没给":
        return NOT_FULFILLED, [], [], "交付没给"
    if item["delivered"] == "交付不可读":
        return NOT_EVALUABLE, [], [], "交付不可读"
    if not needs:
        return FULFILLED, ["delivery"], [], "只凭交付：这条不需要额外证据"
    usable = [group for group in needs if all(evidence.get(kind) for kind in group)]
    if not usable:
        wanted = " 或 ".join("+".join(g) for g in needs)
        return NOT_EVALUABLE, [], [list(g) for g in needs], f"缺证据：需要 {wanted}，场景都没配"
    judge = {"knowledge": lambda: _knowledge(item["claim_refs"], claims), "trace": lambda: _trace(item["process_refs"], rows)}
    groups, notes = [], []
    for group in usable:
        marks = []
        for kind in group:
            mark, note = judge[kind]()
            marks.append(mark)
            notes.append(note)
        groups.append(FAIL if FAIL in marks else UNKNOWN if UNKNOWN in marks else PASS)
    basis = "；".join(dict.fromkeys(notes))
    if FAIL in groups:
        return NOT_FULFILLED, [], [], basis
    if UNKNOWN in groups:
        return NOT_EVALUABLE, [], [], basis
    return FULFILLED, sorted({kind for group in usable for kind in group}), [], basis


def synthesize(view):
    expectations = view.materials["result.expectations"]["expectations"]
    blocking = {i["expectation_id"]: i["blocking"] for i in view.materials["result.blocking"]["items"]}
    evidence = view.materials["scenario.evidence"]
    truth = view.materials.get("result.truthfulness")
    claims = {c["claim_id"]: c for c in (truth or {}).get("claims") or []}
    rows = process_rows(view.materials)
    needs = {e["expectation_id"]: e.get("needs") or [] for e in expectations}
    business = [{
        "expectation_id": e["expectation_id"], "blocking": blocking[e["expectation_id"]],
        "user_intent": e.get("about") or "", "expected_outcome": e.get("statement") or "",
        "acceptance_criteria": [{"condition": e.get("condition"), "ambiguity_group": e.get("ambiguity_group")}],
        "priority": "high" if blocking[e["expectation_id"]] else "normal",
        "evidence_refs": [{"source_refs": e.get("source_refs") or []}], "needs": needs[e["expectation_id"]],
    } for e in expectations]
    assessments = []
    for a in view.own["assessments"]:
        status, tier, missing, basis = derive(a, needs[a["expectation_id"]], evidence, claims, rows)
        assessments.append({"expectation_id": a["expectation_id"], "status": status, "status_basis": basis,
                            "delivered": a["delivered"],
                            "evidence_tier": tier, "missing_evidence": missing, "actual_evidence": list(a["evidence"]),
                            "downstream_impact": a["reason"], "claim_refs": list(a["claim_refs"]),
                            "process_refs": list(a["process_refs"])})
    status = {a["expectation_id"]: a["status"] for a in assessments}
    groups = {}
    for e in expectations:
        if e.get("ambiguity_group"):
            groups.setdefault(e["ambiguity_group"], []).append(e["expectation_id"])
    for a in assessments:
        group = next((m for m in groups.values() if a["expectation_id"] in m), [])
        if a["status"] != FULFILLED and any(status.get(m) == FULFILLED for m in group):
            a["other_reading_fulfilled"] = True
    counted = [e for e in business
               if not any(a.get("other_reading_fulfilled") for a in assessments if a["expectation_id"] == e["expectation_id"])]
    overall = {"status": _derive_overall_status(counted, assessments),
               "blocking_expectations": [e["expectation_id"] for e in business if e["blocking"]]}
    statements = {e["expectation_id"]: e.get("statement") or "" for e in expectations}
    not_fulfilled = [{"expectation_id": a["expectation_id"], "statement": statements[a["expectation_id"]]}
                     for a in assessments if blocking[a["expectation_id"]] and a["status"] == NOT_FULFILLED]
    return {"verdict": overall["status"], "business_expectations": business, "fulfillment_assessments": assessments,
            "overall_fulfillment": overall, "not_fulfilled": not_fulfilled, "claims_checked": truth is not None,
            "reasoning_summary": view.own["reason"]}
