"""llm_probe 轴2 文本形态：boundary 文本作为 G，空则说不清。"""
from __future__ import annotations

from impl.core.authority_scopes import capability_carrier_enabled
from impl.core.capability_carrier import (
    CARRY_NO,
    CARRY_UNDECIDABLE,
    CARRY_YES,
    GAP_UNGOVERNED,
    PLACEMENT_CANNOT,
    PLACEMENT_UNCLEAR,
    PLACEMENT_WRONG,
    bind_capability_carrier,
    live_carrier_report,
    using_placement_request,
    validate_placements,
)
from impl.core.capability_store import validate_entry
from impl.core.project_loader import load_project
from impl.projects.llm_probe.capability import resolve_boundary, resolve_capability
from impl.projects.llm_probe.live import capability_provider
from impl.projects.llm_probe.text_carrier import TextCarrier


def _nf(expectation_id: str) -> dict:
    return {
        "overall_fulfillment": {"status": "not_fulfilled"},
        "business_expectations": [{
            "expectation_id": expectation_id,
            "blocking": True,
            "expected_outcome": expectation_id,
        }],
        "fulfillment_assessments": [
            {"expectation_id": expectation_id, "status": "not_fulfilled"}
        ],
    }


def _completer(carry: str, **extra):
    def complete(_expectation_text: str, boundary: str) -> dict:
        # 引用默认逐字引用边界文本本身：机械核验（引句必须在原文中）才放行。
        payload = {
            "carry": carry,
            "reason": extra.get("reason") or f"boundary={boundary}",
            "self_recognition": extra.get("self_recognition", ""),
            "citations": extra.get("citations", [
                {"source": "boundary", "ref": "boundary", "note": extra.get("note") or boundary}
            ]),
            "gap_kind": extra.get("gap_kind", ""),
            "missing_material": extra.get("missing_material", ""),
        }
        extra.get("seen", []).append(boundary)
        return payload
    return complete


def test_empty_boundary_is_ungoverned_unclear() -> None:
    carrier = TextCarrier(boundary_loader=lambda: "")
    verdict = carrier.verdict_for({"expectation_id": "按年龄检索"})
    assert verdict.carry == CARRY_UNDECIDABLE
    assert verdict.gap_kind == GAP_UNGOVERNED
    assert "能力边界" in verdict.missing_material
    report = carrier.place(_nf("按年龄检索"))
    assert report["placements"][0]["placement"] == PLACEMENT_UNCLEAR
    assert report["placements"][0]["gap_kind"] == GAP_UNGOVERNED


def test_boundary_yes_places_wrong() -> None:
    carrier = TextCarrier(
        boundary_loader=lambda: "本接口支持按客户姓名检索。",
        completer=_completer(CARRY_YES),
    )
    report = carrier.place(_nf("按姓名检索"))
    item = report["placements"][0]
    assert item["placement"] == PLACEMENT_WRONG
    assert item["citations"]


def test_boundary_no_places_cannot_with_statement_recognition() -> None:
    carrier = TextCarrier(
        boundary_loader=lambda: "本接口仅支持按客户姓名检索，不支持年龄。",
        completer=_completer(
            CARRY_NO,
            self_recognition="仅支持按客户姓名检索，不支持年龄",
        ),
    )
    report = carrier.place(_nf("按年龄检索"))
    item = report["placements"][0]
    assert item["placement"] == PLACEMENT_CANNOT
    assert item["recognition"] == "boundary_statement"
    row = {
        "current": _nf("按年龄检索"),
        "draft": {"overall_fulfillment": {"status": "fulfilled"}},
        "capability_carrier": {"current": report, "draft": {"applicable": False}},
    }
    assert validate_placements(row) == []


def test_fulfilled_axis1_does_not_run_text_carrier() -> None:
    carrier = TextCarrier(
        boundary_loader=lambda: "支持姓名",
        completer=lambda *_args: {"carry": "yes", "reason": "should not run"},
    )
    report = carrier.place({"overall_fulfillment": {"status": "fulfilled"}})
    assert report["applicable"] is False
    assert report["placements"] == []


def test_llm_probe_scope_on_and_provider_binds_text_carrier() -> None:
    spec = load_project("llm_probe")
    assert capability_carrier_enabled(spec)
    assert capability_provider(spec).__class__ is TextCarrier
    bound = bind_capability_carrier(spec)
    assert isinstance(bound, TextCarrier)


def test_existing_presets_without_boundary_place_ungoverned(monkeypatch) -> None:
    # capability_map.json 是用户数据，可能随时被填上 boundary；这里固定一个无 boundary 预设。
    monkeypatch.setattr(
        "impl.projects.llm_probe.capability.load_capability_map",
        lambda: {"no-boundary-api": {"capability": "按条件检索客户"}},
    )
    spec = load_project("llm_probe")
    report = live_carrier_report(
        spec,
        _nf("按年龄检索"),
        request={"capability_ref": "no-boundary-api"},
    )
    assert report is not None
    assert report["placements"][0]["placement"] == PLACEMENT_UNCLEAR
    assert report["placements"][0]["gap_kind"] == GAP_UNGOVERNED


def test_g_is_this_case_boundary_not_all_presets(monkeypatch) -> None:
    mapping = {
        "alpha": {"capability": "搜人", "boundary": "仅支持姓名检索"},
        "beta": {"capability": "搜年龄", "boundary": "仅支持年龄筛选"},
    }
    monkeypatch.setattr(
        "impl.projects.llm_probe.capability.load_capability_map",
        lambda: mapping,
    )
    seen: list[str] = []
    carrier = TextCarrier(completer=_completer(CARRY_YES, seen=seen))
    spec = load_project("llm_probe")
    live_carrier_report(
        spec, _nf("按姓名检索"), carrier=carrier,
        request={"capability_ref": "alpha"},
    )
    assert seen == ["仅支持姓名检索"]
    seen.clear()
    live_carrier_report(
        spec, _nf("按年龄检索"), carrier=carrier,
        request={"capability_ref": "beta"},
    )
    assert seen == ["仅支持年龄筛选"]


def test_inline_request_boundary_wins_over_preset(monkeypatch) -> None:
    monkeypatch.setattr(
        "impl.projects.llm_probe.capability.load_capability_map",
        lambda: {"alpha": {"capability": "搜人", "boundary": "预设边界不应出现"}},
    )
    bundle = resolve_boundary({
        "capability_ref": "alpha",
        "boundary": "本案内联边界",
    })
    assert bundle["text"] == "本案内联边界"
    assert bundle["catalog"] == []


def test_text_carrier_boundary_expands_sample_material() -> None:
    """轴2 读到的 G 必须是样例资料正文，不是 {material://} 记号本身。"""
    token = "{material://llm_probe/client-search-match-rule}"
    bundle = resolve_boundary({"boundary": token})
    assert "姓名全值等值匹配" in bundle["text"]
    assert bundle["text"] != token
    assert bundle["catalog"] == []
    carrier = TextCarrier()
    with using_placement_request({"boundary": f"能力范围见 {token}"}):
        current = carrier._current_boundary()
    assert "姓名全值等值匹配" in current["text"]
    assert "--- material://llm_probe/client-search-match-rule ---" in current["text"]


def test_boundary_large_material_becomes_catalog_entry(monkeypatch) -> None:
    """超预算的资料不内联：转目录条目，正文靠检索工具查。"""
    import impl.core.materials_store as ms

    token = "{material://llm_probe/client-search-match-rule}"
    monkeypatch.setattr(ms, "REFERENCE_EXPAND_BUDGET_CHARS", 10)
    bundle = resolve_boundary({"boundary": f"能力见 {token}"})
    assert bundle["catalog"], "超预算资料必须进 catalog"
    entry = bundle["catalog"][0]
    assert entry["id"] == "client-search-match-rule"
    assert entry["uri"] == "material://llm_probe/client-search-match-rule"
    assert entry["sha256"]
    assert "[大资料未内联]" in bundle["text"]
    assert "姓名全值等值匹配" not in bundle["text"]


def test_fake_citation_is_rejected_and_exhausts_retries() -> None:
    """机械核验：引句不在原文 → 打回重试 → 耗尽落归位失败，不放行假引用。"""
    carrier = TextCarrier(
        boundary_loader=lambda: "本接口支持按客户姓名检索。",
        completer=_completer(CARRY_YES, note="资料里根本没有这句话"),
        retries=2,
        retry_backoff=(0, 0),
    )
    from impl.core.capability_carrier import CarrierError

    outcome = carrier.verdict_for({"expectation_id": "按姓名检索"})
    assert isinstance(outcome, CarrierError)
    assert "引用核验" in outcome.last_error


def test_material_citation_verified_against_locator() -> None:
    from impl.projects.llm_probe.text_carrier import _verify_citations
    from impl.projects.llm_probe.material_tools import search as material_search

    hit = material_search("llm_probe", "client-search-match-rule", "等值匹配")
    locator = hit["snippets"][0]["locator"]
    good = CarrierVerdictFactory(
        citations=({"source": "material://llm_probe/client-search-match-rule",
                    "ref": locator, "note": "姓名全值等值匹配"},),
    )
    assert _verify_citations(good, "边界文本") == []
    bad = CarrierVerdictFactory(
        citations=({"source": "material://llm_probe/client-search-match-rule",
                    "ref": locator, "note": "原文没有的话"},),
    )
    failures = _verify_citations(bad, "边界文本")
    assert failures and "未找到引句" in failures[0]


def CarrierVerdictFactory(citations):
    from impl.core.capability_carrier import CarrierVerdict
    return CarrierVerdict(CARRY_YES, "理由", citations=citations)


def test_verdict_tool_trail_serializes() -> None:
    from impl.core.capability_carrier import CarrierVerdict

    verdict = CarrierVerdict(
        CARRY_YES, "资料覆盖",
        citations=({"source": "material://llm_probe/x", "ref": "L5-L7", "note": "支持等值"},),
        tool_trail=({"tool": "material_search", "material_id": "x", "query": "等值",
                     "returned_locators": ["L5-L7"]},),
    )
    payload = verdict.as_dict()
    assert payload["tool_trail"][0]["tool"] == "material_search"
    assert payload["citations"][0]["ref"] == "L5-L7"


def test_validate_entry_keeps_optional_boundary() -> None:
    clean = validate_entry("my-api", {
        "capability": "检索客户",
        "boundary": "仅支持姓名和手机号",
    })
    assert clean["boundary"] == "仅支持姓名和手机号"
    omitted = validate_entry("my-api", {"capability": "检索客户"})
    assert "boundary" not in omitted


def test_validate_entry_rejects_non_string_boundary() -> None:
    try:
        validate_entry("my-api", {"capability": "检索客户", "boundary": {"text": "x"}})
    except ValueError as exc:
        assert "boundary" in str(exc)
    else:
        raise AssertionError("non-string boundary must fail")


def test_validate_entry_keeps_uri_text_and_rejects_bad_refs() -> None:
    token = "{material://llm_probe/client-search-match-rule}"
    clean = validate_entry("my-api", {
        "capability": f"字段口径见 {token}",
        "boundary": token,
    })
    assert token in clean["capability"]
    assert clean["boundary"] == token
    try:
        validate_entry("my-api", {"capability": "见 material://llm_probe/NoSuch"})
    except ValueError as exc:
        assert "资料引用" in str(exc)
    else:
        raise AssertionError("bare material uri must fail save")
    try:
        validate_entry("my-api", {"capability": "见 {material://llm_probe/no-such-doc}"})
    except ValueError as exc:
        assert "资料引用" in str(exc)
    else:
        raise AssertionError("missing material must fail save")


def test_resolve_capability_expands_embedded_uri(monkeypatch) -> None:
    monkeypatch.setattr(
        "impl.core.materials_store.expand_material_uris",
        lambda text, **_kwargs: text.replace("{material://llm_probe/spec}", "姓名口径"),
    )
    assert "姓名口径" in resolve_capability({
        "capability": "字段口径见 {material://llm_probe/spec}",
    })


def test_config_check_accepts_bound_llm_probe() -> None:
    from impl.core.config_check import ConfigCheckReport, _check_capability_carrier_binding

    spec = load_project("llm_probe")
    report = ConfigCheckReport()
    _check_capability_carrier_binding(report, spec, spec.project_package_path() / "project.yaml")
    assert report.issues == []


def test_frontend_view_exposes_carrier_panel() -> None:
    """live 页轴2面板的数据源：build_frontend_view 必须带 capability_carrier_panel。"""
    from impl.core.frontend_view import build_frontend_view
    from impl.core.schema import JudgeResult, RunTrace

    spec = load_project("llm_probe")
    trace = RunTrace(
        trace_id="t1", project_id="llm_probe",
        normalized_request={"capability_ref": "client_search"},
        extracted_output={"output_text": "{}"},
    )
    judge = JudgeResult(
        trace_id="t1", project_id="llm_probe",
        overall_fulfillment={"status": "fulfilled"},
    )
    view = build_frontend_view(spec, trace, judge, None, None, None, {})
    panel = view.capability_carrier_panel
    assert panel.get("applicable") is False
    assert panel.get("axis1_status") == "fulfilled"
    # API 出口走 to_public_dict 白名单投影（occam.py），面板必须活着穿过这层。
    from impl.core.schema import to_public_dict

    public = to_public_dict(view)
    assert public.get("capability_carrier_panel", {}).get("applicable") is False
