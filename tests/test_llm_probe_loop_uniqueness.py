"""唯一性原则与多轮按轮列（spec/alg/knowledge-evidence.md §3、§4.6，spec/alg/fulfilled.md §4）：说法可记多处出现、出处带轮次；
取证结果里同一条记录、同一次调用只给一份；兑现只引出处在本轮的说法。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from impl.core.axis_loop.view import CallView
from impl.projects.llm_probe_loop.eval_axes.registry import definitions

T1 = "保单P1累计已交保费1,089.1元。\n……\n汇总：保单P1累计已交保费 1089.1 元。"
T2 = "保单P2累计已交保费 324.9 元。"


def _claims_view(claims, deliveries=(("t1", T1),)):
    return SimpleNamespace(own={"claims": claims}, materials={
        "case.deliveries": [{"turn": t, "output_text": x} for t, x in deliveries], "case.user_turns": ["查P1", "那P2呢"]})


def _claim(cid, spans, qualifies="", context=("保单P1",)):
    return {"claim_id": cid, "claim": "累计已交保费的数值是1089.1", "spans": [{"turn": t, "text": x} for t, x in spans],
            "context": list(context), "qualifies": qualifies}


def _check(claims, deliveries=(("t1", T1),)):
    return definitions().axes["claims"].code.check(_claims_view(claims, deliveries))


def test_claim_may_carry_every_place_it_appears():
    assert _check([_claim("c1", [("t1", "累计已交保费1,089.1元"), ("t1", "累计已交保费 1089.1 元")])]) == []


def test_each_span_must_be_verbatim():
    assert any("spans 段" in p for p in _check([_claim("c1", [("t1", "累计已交保费1,089.1元"), ("t1", "累计已交保费 2000 元")])]))


def test_qualifier_sharing_the_spans_is_not_a_context_leak():
    spans = [("t1", "累计已交保费1,089.1元")]
    unit = {**_claim("c2", spans, qualifies="c1"), "claim": "累计已交保费的单位是元"}
    assert _check([_claim("c1", spans), unit]) == []


def test_claims_from_each_turn_check_against_their_own_turn():
    both = (("t1", T1), ("t2", T2))
    p2 = _claim("c2", [("t2", "累计已交保费 324.9 元")], context=("保单P2",))
    assert _check([_claim("c1", [("t1", "累计已交保费1,089.1元")]), p2], both) == []
    wrong_turn = _claim("c2", [("t1", "累计已交保费 324.9 元")], context=("保单P2",))
    assert any("第 t1 轮" in p for p in _check([wrong_turn], both))


def test_span_turn_must_be_a_given_turn():
    """只给了最后一轮时（配置只核部分轮次），出处标别的轮被拒。"""
    assert any("不是材料里给了的轮" in p for p in _check([_claim("c1", [("t1", "累计已交保费1,089.1元")])], (("t2", T2),)))


def test_same_thing_in_two_turns_is_one_claim():
    both = (("t1", T1), ("t2", "前面说过，保单P1累计已交保费1,089.1元。"))
    assert _check([_claim("c1", [("t1", "累计已交保费1,089.1元"), ("t2", "累计已交保费1,089.1元")])], both) == []


def _fulfillment_check(refs, claim_turns):
    claims = [{"claim_id": c, "spans": [{"turn": t, "text": "x"} for t in ts]} for c, ts in claim_turns.items()]
    materials = {"result.truthfulness": {"claims": claims},
                 "result.expectations": {"expectations": [{"expectation_id": "t1.E1", "turn": "t1"}, {"expectation_id": "t2.E1", "turn": "t2"}]}}
    own = {"assessments": [{"expectation_id": e, "claim_refs": r, "process_refs": []} for e, r in refs.items()]}
    return definitions().axes["fulfillment"].code.check(SimpleNamespace(materials=materials, own=own))


def test_fulfillment_cites_only_claims_from_its_turn():
    turns = {"c1": ["t1"], "c2": ["t2"], "c3": ["t1", "t2"]}
    assert _fulfillment_check({"t1.E1": ["c1", "c3"], "t2.E1": ["c2", "c3"]}, turns) == []
    assert any("t1.E1" in p and "c2" in p for p in _fulfillment_check({"t1.E1": ["c2"]}, turns))


def test_evidence_gives_each_record_and_call_once():
    record = {"policy_no": "P1", "agg_paid_prem": "1089.1", "unit": None}
    text = json.dumps({"records": [record]}, ensure_ascii=False)
    call = CallView("c3", "policy_search", "tool", {"query": "P1"}, 1, text, None, False)
    items = [{"item_id": i, "status": "found", "citations": [{"ref": "c3", "quote": '"agg_paid_prem": "1089.1"'}],
              "search_calls": ["c3"], "note": "", "gap": ""} for i in ("c1", "c2")]
    view = SimpleNamespace(own={"items": items}, call=lambda ref: call)
    out = definitions().shared_tools["search_knowledge"].code.synthesize(view)
    assert out["cite_records"] == {"c1": ["r1"], "c2": ["r1"]}
    assert list(out["records"]) == ["r1"] and '"unit":null' in out["records"]["r1"]
    assert out["calls"] == {"c3": {"tool": "policy_search", "args": {"query": "P1"}}}
    assert "items" not in out


def test_truthfulness_result_with_turned_spans_fits_its_schema():
    from impl.core.axis_loop.acceptance import schema_errors
    axis = definitions().axes["truthfulness"]
    claim = _claim("c1", [("t1", "累计已交保费1,089.1元"), ("t2", "累计已交保费1,089.1元")])
    view = SimpleNamespace(materials={"result.claims": {"claims": [claim]}},
                           own={"judgments": [{"claim_id": "c1", "verdict": "verified", "reason": "r", "gap": "", "basis": []}]})
    result = {"reason": "r", "judgments": view.own["judgments"], **axis.code.synthesize(view)}
    assert [e for e in schema_errors(axis.output, result) if "spans" in e] == []
