"""g-provider 合同最小形状 + key_live 剥离等价门。

对应 spec/math-abstract/provider-contract.md：
- §2.1 装载期声明缺一即 fail-fast；
- §2.2 运行期五项输出；
- §3 值缺失是合法输出，不是失败；
- §4.1 key_live 实例：provider value 与旧直连检索输出逐字节一致（零行为漂移）。
"""
from __future__ import annotations

import json
import textwrap

import pytest

from impl.core.provider_contract import (
    LANE_G,
    TRUST_NORMATIVE_RULE,
    ProviderContractError,
    ProviderDeclaration,
    ProvidedValue,
    anchors_outside_citation_space,
)

_FAILURE_SEMANTICS = {
    "load": "装载失败 fail-fast",
    "runtime": "设施故障 error",
    "value_missing": "缺维度是合法证据",
}


def _declaration(**overrides):
    payload = {
        "provider_id": "demo.provider",
        "lane": LANE_G,
        "citation_space": frozenset({"clientAge"}),
        "failure_semantics": _FAILURE_SEMANTICS,
    }
    payload.update(overrides)
    return ProviderDeclaration(**payload)


def test_declaration_requires_lane_citation_space_and_failure_stages():
    assert _declaration().lane == LANE_G
    with pytest.raises(ProviderContractError):
        _declaration(lane="judge")
    with pytest.raises(ProviderContractError):
        _declaration(citation_space=frozenset())
    with pytest.raises(ProviderContractError):
        _declaration(failure_semantics={"load": "只有装载面"})
    with pytest.raises(ProviderContractError):
        _declaration(provider_id="  ")


def test_provided_value_requires_three_piece_metadata():
    provided = ProvidedValue(
        value={"rules": []},
        provenance={"source": "unit"},
        trust_tier=TRUST_NORMATIVE_RULE,
        staleness={"mode": "key_live"},
        citation_anchors=("clientAge",),
    )
    assert provided.citation_anchors == ("clientAge",)
    with pytest.raises(ProviderContractError):
        ProvidedValue(
            value={},
            provenance={"source": "unit"},
            trust_tier="self_claimed",
            staleness={"mode": "key_live"},
        )
    with pytest.raises(ProviderContractError):
        ProvidedValue(
            value={},
            provenance={},
            trust_tier=TRUST_NORMATIVE_RULE,
            staleness={"mode": "key_live"},
        )
    with pytest.raises(ProviderContractError):
        ProvidedValue(
            value={},
            provenance={"source": "unit"},
            trust_tier=TRUST_NORMATIVE_RULE,
            staleness={},
        )


def test_anchor_audit_flags_out_of_space_citations():
    declaration = _declaration(citation_space=frozenset({"clientAge", "规则A"}))
    inside = ProvidedValue(
        value={},
        provenance={"source": "unit"},
        trust_tier=TRUST_NORMATIVE_RULE,
        staleness={"mode": "key_live"},
        citation_anchors=("clientAge", "规则A"),
    )
    outside = ProvidedValue(
        value={},
        provenance={"source": "unit"},
        trust_tier=TRUST_NORMATIVE_RULE,
        staleness={"mode": "key_live"},
        citation_anchors=("clientAge", "别家的键"),
    )
    assert anchors_outside_citation_space(declaration, inside) == ()
    assert anchors_outside_citation_space(declaration, outside) == ("别家的键",)


_ENHANCED_RULES_FIXTURE = textwrap.dedent(
    """
    negation_words: ["不", "没有", "非"]
    rules:
      - name: 年龄区间规则
        field: clientAge
        operator: RANGE
        patterns: ["{num}岁到{num}岁"]
      - name: 年龄下限规则
        field: clientAge
        operator: GTE
        patterns: ["{num}岁以上"]
      - name: 隐藏生成配方
        field: clientAge
        operator: MATCH
        merge_to_llm: false
      - name: 车牌规则
        field: licensePlateNo
        operator: MATCH
    """
)


@pytest.fixture()
def key_live_fixture(tmp_path, monkeypatch):
    """把受治理源 YAML 钉到临时 business 根，隔离外部业务仓依赖。"""
    source = (
        tmp_path
        / "src/main/python/data/client_search_query_parse/enhanced_rules_args.yaml"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(_ENHANCED_RULES_FIXTURE, encoding="utf-8")
    monkeypatch.setenv("CLIENT_SEARCH_REPO", str(tmp_path))

    from impl.projects.client_search import enhanced_rules_key_index as module

    module._enhanced_rules_source_path.cache_clear()
    module._load_enhanced_rules_document.cache_clear()
    module._enhanced_rules_source_sha256.cache_clear()
    yield module
    module._enhanced_rules_source_path.cache_clear()
    module._load_enhanced_rules_document.cache_clear()
    module._enhanced_rules_source_sha256.cache_clear()


def test_key_live_provider_value_is_byte_identical_to_direct_retrieval(key_live_fixture):
    """零漂移等价门：provider.value == 旧直连检索输出（含字段序）。"""
    module = key_live_fixture
    direct = module.retrieve_enhanced_rules_for_fields({"clientAge", "licensePlateNo"})
    provided = module.provide_enhanced_rules_for_fields({"clientAge", "licensePlateNo"})
    assert json.dumps(provided.value, ensure_ascii=False, sort_keys=False) == (
        json.dumps(direct, ensure_ascii=False, sort_keys=False)
    )


def test_key_live_declaration_matches_contract_row(key_live_fixture):
    module = key_live_fixture
    declaration = module.enhanced_rules_provider_declaration()
    assert declaration.provider_id == module.ENHANCED_RULES_PROVIDER_ID
    assert declaration.lane == LANE_G
    # 引用空间 = field 名 + 规则定位键 name（含 merge_to_llm=false 的键：
    # 空间描述索引全集，注入过滤是消费侧行为）。
    assert {"clientAge", "licensePlateNo", "年龄区间规则", "车牌规则"} <= (
        declaration.citation_space
    )
    assert set(declaration.failure_semantics) == {"load", "runtime", "value_missing"}


def test_key_live_provided_value_carries_three_piece_and_anchors(key_live_fixture):
    module = key_live_fixture
    declaration = module.enhanced_rules_provider_declaration()
    provided = module.provide_enhanced_rules_for_fields(["clientAge"])
    assert provided.trust_tier == TRUST_NORMATIVE_RULE
    assert provided.staleness["consumption_mode"] == "key_live"
    assert provided.staleness["source_sha256"]
    assert provided.provenance["requested_fields"] == ["clientAge"]
    assert "enhanced_rules" in provided.provenance["source"]
    assert provided.citation_anchors
    assert anchors_outside_citation_space(declaration, provided) == ()
    # merge_to_llm=false 的配方不进 value，也不进锚点。
    assert "隐藏生成配方" not in provided.citation_anchors
    for rule in provided.value.get("rules") or []:
        assert set(rule) <= {"name", "field"}


def test_key_live_missing_field_is_legal_value_missing_not_error(key_live_fixture):
    """查了没有是证据：无条目字段返回合法空值，不抛错（§3）。"""
    module = key_live_fixture
    provided = module.provide_enhanced_rules_for_fields(["noSuchField"])
    assert "rules" not in provided.value
    assert provided.value.get("negation_words") == ["不", "没有", "非"]
    assert provided.citation_anchors == ()
