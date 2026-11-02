"""承载性（spec/alg/axis_loop.md §12.3）：依据只能是本轴描述原文或这次 search_knowledge 查到的原文；归位由程序换算，主轴照读。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from impl.core.axis_loop.view import CallView
from impl.projects.llm_probe_loop.eval_axes.main_verdict import main_verdict
from impl.projects.llm_probe_loop.eval_axes.registry import definitions
from impl.projects.llm_probe_loop.eval_axes.validate import validate_scenario_entry

NOTE = "仅提供办理说明，不实际提交退保或保全申请。"


def _code():
    return definitions().axes["carryability"].code


def _view(own, calls=()):
    return SimpleNamespace(stage="item", own=own, materials={"axis.note": NOTE}, calls=list(calls),
                           call=lambda ref: next((c for c in calls if c.call_id == ref), None))


def _own(carry, basis=(), gap_kind="", missing=""):
    return {"expectation_id": "t1.E1", "carry": carry, "reason": "r", "basis": list(basis),
            "gap_kind": gap_kind, "missing_material": missing}


def _search(status, text="保单 P1 的现金价值为 1200 元", error=False):
    structured = {"items": [{"item_id": "t1.E1", "status": status, "citations": [{"ref": "r1", "quote": text}]}]}
    return CallView("c1", "search_knowledge", "subloop", {}, 1, text, structured, error)


def test_quote_from_the_box_is_evidence():
    assert _code().check(_view(_own("no", [{"ref": "axis.note", "quote": "不实际提交退保或保全申请"}]))) == []


def test_quote_outside_the_box_or_from_a_missed_search_is_rejected():
    check = _code().check
    assert check(_view(_own("no", [{"ref": "axis.note", "quote": "系统不支持退保"}])))
    assert check(_view(_own("yes", [{"ref": "c1", "quote": "现金价值为 1200 元"}]), [_search("not_found")]))
    assert check(_view(_own("yes", [{"ref": "c1", "quote": "现金价值为 1200 元"}]), [_search("found", error=True)]))
    assert check(_view(_own("yes", [{"ref": "c1", "quote": "现金价值为 1200 元"}]), [_search("found")])) == []


def test_yes_or_no_needs_basis_and_undecidable_needs_gap():
    check = _code().check
    assert check(_view(_own("yes")))
    assert check(_view(_own("undecidable")))
    assert check(_view(_own("undecidable", gap_kind="空间未受治理", missing="产品清单"))) == []


def test_placements_feed_the_main_verdict():
    judgments = [_own("no", [{"ref": "axis.note", "quote": NOTE}])]
    carry = _code().synthesize(SimpleNamespace(own={"judgments": judgments}))
    assert carry["verdict"] == "做不了" and carry["placements"][0]["placement"] == "做不了"
    fulfillment = {"business_expectations": [{"expectation_id": "t1.E1", "blocking": True}],
                   "fulfillment_assessments": [{"expectation_id": "t1.E1", "status": "not_fulfilled"}]}
    results = [{"type_id": "fulfillment", "status": "succeeded", "output": fulfillment},
               {"type_id": "carryability", "status": "succeeded", "output": carry}]
    assert main_verdict(results)["verdict"] == "做不了"
    carry = _code().synthesize(SimpleNamespace(own={"judgments": [_own("yes", [{"ref": "c1", "quote": "x"}])]}))
    results[1]["output"] = carry
    assert carry["verdict"] == "做错了" and main_verdict(results)["verdict"] == "没做成"


def test_carryability_appears_only_when_fulfillment_is_not_fulfilled():
    axis = definitions().axes["carryability"]
    assert axis.trigger.axis == "fulfillment" and axis.trigger.verdict_in == ("not_fulfilled",)
    assert ("carryability", False) in [(d.axis, d.hard) for d in definitions().axes["main_verdict"].depends]


def test_boundary_lives_in_the_carryability_box():
    with pytest.raises(ValueError, match="承载性的描述框"):
        validate_scenario_entry({"axes": [], "boundary": "x"}, owner="x")


def test_optional_tool_without_sources_does_not_block_the_scenario():
    """承载性的 search_knowledge 是可选工具：场景没选知识源也能开（必需工具的真实性照旧报错）。"""
    on = ["expectations", "blocking", "claims", "fulfillment", "carryability", "main_verdict"]
    axes = validate_scenario_entry({"axes": [{"type": k, "enabled": True, "description": ""} for k in on]}, owner="x")
    assert "carryability" in axes.enabled
    with pytest.raises(ValueError, match="必需 knowledge"):
        validate_scenario_entry({"axes": [{"type": k, "enabled": True, "description": ""} for k in [*on, "truthfulness"]]}, owner="x")
