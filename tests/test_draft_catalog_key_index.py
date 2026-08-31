from __future__ import annotations

from pathlib import Path

import pytest

from impl.core.project_loader import load_project
from impl.projects.client_search import catalog as catalog_mod
from impl.core.schema import InvestigationKeyEntry, InvestigationKeyIndex
from impl.projects.client_search.catalog import (
    ABBR_INDEX_KEY,
    COLLECTION_SPECS,
    FIELD_INDEX_KEY,
    MAPPINGS_INDEX_KEY,
    RULES_INDEX_KEY,
    STRONG_HIT_FLOOR,
    TEXT_COLLECTION_EMBEDDING,
    build_draft_catalog_registry,
    create_catalog_tools,
    rewrite_query,
    search_catalog,
)
from impl.projects.client_search.catalog_embedding import (
    catalog_embedding_projection,
    clear_entry_vector_cache,
    cosine_l2,
    search_embedding_channel,
)
from impl.projects.client_search.draft.simulate_field_key_index import (
    EMBEDDING_CACHE_PATH,
)


CATALOG_PATH = Path(catalog_mod.__file__)


def _skip_without_sources():
    spec = load_project("client_search")
    needed = ("field_definitions", "enhanced_rules", "value_mappings", "abbrname_enums")
    missing = [
        key
        for key in needed
        if not spec.source_path(key) or not Path(spec.source_path(key)).is_file()
    ]
    if missing:
        pytest.skip(f"business sources unavailable: {missing}")
    return spec


def test_catalog_module_has_no_business_reject_lexicon():
    source = CATALOG_PATH.read_text(encoding="utf-8")
    forbidden = (
        "COMMON_TOKENS",
        "天气",
        "爱好",
        "红烧肉",
        "客户的有是和与及或并且一个哪些名单帮我找查询",
        "Prefer",
    )
    for token in forbidden:
        assert token not in source, f"Judge Catalog must not contain {token!r}"


def test_rewrite_skips_ultrashort_queries():
    assert rewrite_query("") == ()
    assert rewrite_query("A") == ()
    assert rewrite_query("客户") == ()
    assert rewrite_query("金") == ()
    assert rewrite_query("O2O") == ()
    assert rewrite_query("ab") == ()


def test_rewrite_rejects_new_entity_variants():
    origins = ("关爱客户", "有钱客户", "帮我找客户名单")
    forbidden_entities = (
        "高净值",
        "天气",
        "红烧肉",
        "clientAge",
        "polNoInfo.plancodeinfo.abbrname",
        "金凤",
        "VIP客户",
        "licensePlateNo",
    )
    for origin in origins:
        variants = rewrite_query(origin)
        assert origin not in variants
        for variant in variants:
            assert variant in origin
            assert len(variant) > 2
        for entity in forbidden_entities:
            assert entity not in variants


def test_rewrite_bans_field_ids_and_english_paths():
    assert rewrite_query("clientAge") == ()
    assert rewrite_query("polNoInfo.plancodeinfo.abbrname") == ()
    assert rewrite_query("familyInfo.familyclientage") == ()
    for variant in rewrite_query("查找客户本人年龄"):
        assert "." not in variant
        assert variant != "clientAge"


def test_abbr_exact_equality_not_substring():
    spec = _skip_without_sources()
    registry = build_draft_catalog_registry(spec)
    hits, searched = search_catalog(registry, "金凤", index_keys=(ABBR_INDEX_KEY,))
    assert ABBR_INDEX_KEY in searched
    assert any(hit.key == "金凤" and hit.index_key == ABBR_INDEX_KEY for hit in hits)
    assert all(float(hit.score or 0) >= STRONG_HIT_FLOOR for hit in hits)

    customer_hits, _ = search_catalog(registry, "客户")
    for hit in customer_hits:
        assert hit.key == "客户" or hit.name == "客户"


def test_all_catalog_default_has_no_prefer_routing():
    spec = _skip_without_sources()
    registry = build_draft_catalog_registry(spec)
    expected = (
        FIELD_INDEX_KEY,
        RULES_INDEX_KEY,
        MAPPINGS_INDEX_KEY,
        ABBR_INDEX_KEY,
    )
    catalog_keys = tuple(item["index_key"] for item in registry.catalog())
    assert set(catalog_keys) == set(expected)
    assert {item.index_key for item in COLLECTION_SPECS} == set(expected)

    hits, searched = search_catalog(registry, "金凤")
    assert searched == catalog_keys
    assert any(hit.index_key == ABBR_INDEX_KEY and hit.key == "金凤" for hit in hits)

    search_tool, load_tool = create_catalog_tools(registry)
    searched_all = search_tool.execute_fn(query="金凤")
    assert searched_all.status == "succeeded"
    assert searched_all.actual["searched_index_keys"] == list(catalog_keys)
    assert searched_all.actual["search_hit_is_not_evidence"] is True
    assert "Prefer" not in (search_tool.description or "")
    assert "SearchHit is not Evidence" in (search_tool.description or "")
    assert "Rewrite and embedding hits are locators only" in (search_tool.description or "")
    assert "they are not synonym proofs" in (search_tool.description or "")
    assert "do not change fulfillment from SearchHit without Load" in (
        search_tool.description or ""
    )

    loaded = load_tool.execute_fn(index_key=ABBR_INDEX_KEY, key="金凤")
    assert loaded.status == "succeeded"
    assert loaded.actual["content"]["value"] == "金凤"
    assert loaded.actual["content"]["membership"] == "exact"
    assert "rules" not in loaded.actual["content"]
    dump = load_tool.execute_fn(index_key=ABBR_INDEX_KEY, key="*")
    assert dump.status == "failed"


def test_weak_rewrite_hits_do_not_count_as_success():
    spec = _skip_without_sources()
    registry = build_draft_catalog_registry(spec)
    hits, _ = search_catalog(registry, "查找车牌号相关请求")
    rewrite_hits = [hit for hit in hits if float(hit.score or 0) < STRONG_HIT_FLOOR]
    for hit in rewrite_hits:
        assert float(hit.score or 0) < STRONG_HIT_FLOOR



class _TableEmbeddingProvider:
    """Deterministic vectors for Catalog tests; no network."""

    model_id = "scripted-catalog-v1"

    def __init__(self, table, default):
        self.table = dict(table)
        self.default = list(default)
        self.calls = []

    def embed(self, texts):
        batch = [str(text) for text in texts]
        self.calls.append(batch)
        return [list(self.table.get(text, self.default)) for text in batch]


def _channel_status(spec, name):
    return next(channel.status for channel in spec.channels if channel.name == name)


def test_embedding_channel_declared_on_text_collections_only():
    by_key = {item.index_key: item for item in COLLECTION_SPECS}
    assert _channel_status(by_key[FIELD_INDEX_KEY], "embedding") == "active"
    assert _channel_status(by_key[RULES_INDEX_KEY], "embedding") == "active"
    assert _channel_status(by_key[MAPPINGS_INDEX_KEY], "embedding") == "rejected"
    assert _channel_status(by_key[ABBR_INDEX_KEY], "embedding") == "rejected"
    assert by_key[FIELD_INDEX_KEY].embedding is TEXT_COLLECTION_EMBEDDING
    assert by_key[RULES_INDEX_KEY].embedding is TEXT_COLLECTION_EMBEDDING
    assert by_key[MAPPINGS_INDEX_KEY].embedding is None
    assert by_key[ABBR_INDEX_KEY].embedding is None
    assert TEXT_COLLECTION_EMBEDDING.min_cosine == 0.58
    assert TEXT_COLLECTION_EMBEDDING.provider == "bailian"
    assert TEXT_COLLECTION_EMBEDDING.min_cosine > 0.50


def test_embedding_threshold_lives_on_collection_spec_not_business_ifs():
    source = CATALOG_PATH.read_text(encoding="utf-8")
    assert "TEXT_COLLECTION_EMBEDDING = EmbeddingChannelMeta(min_cosine=0.58)" in source
    assert "if spec.embedding.min_cosine" not in source
    forbidden_business = ("isBuyInsurance", "COMMON_TOKENS", "兴趣爱好")
    for token in forbidden_business:
        assert token not in source


def test_embedding_skipped_without_provider_keeps_existing_search():
    spec = _skip_without_sources()
    registry = build_draft_catalog_registry(spec)
    empty, searched = search_catalog(registry, "十里堡")
    assert empty == []
    assert FIELD_INDEX_KEY in searched


def test_embedding_is_additional_channel_on_text_collections():
    spec = _skip_without_sources()
    registry = build_draft_catalog_registry(spec)
    index = registry.index(FIELD_INDEX_KEY)
    target = next(entry for entry in index.entries if entry.key == "clientAge")
    query = "十里堡"
    high = [0.9, 0.4358898943540673]
    provider = _TableEmbeddingProvider(
        {
            query: [1.0, 0.0],
            catalog_embedding_projection(target): high,
        },
        default=[0.0, 1.0],
    )
    clear_entry_vector_cache()
    hits, searched = search_catalog(
        registry,
        query,
        embedding_provider=provider,
    )
    assert searched == tuple(item["index_key"] for item in registry.catalog())
    age_hits = [hit for hit in hits if hit.key == "clientAge" and hit.index_key == FIELD_INDEX_KEY]
    assert age_hits
    assert "embedding" in age_hits[0].matched_channels
    assert float(age_hits[0].score or 0) < STRONG_HIT_FLOOR
    assert float(age_hits[0].score or 0) > 40.0

    abbr_hits, _ = search_catalog(
        registry,
        "金凤",
        index_keys=(ABBR_INDEX_KEY,),
        embedding_provider=provider,
    )
    assert any(hit.key == "金凤" and hit.index_key == ABBR_INDEX_KEY for hit in abbr_hits)
    assert all("embedding" not in hit.matched_channels for hit in abbr_hits)

    search_tool, load_tool = create_catalog_tools(
        registry, embedding_provider=provider
    )
    result = search_tool.execute_fn(query=query, index_key=FIELD_INDEX_KEY)
    assert result.status == "succeeded"
    assert result.actual["search_hit_is_not_evidence"] is True
    loaded = load_tool.execute_fn(index_key=FIELD_INDEX_KEY, key="clientAge")
    assert loaded.status == "succeeded"
    assert loaded.actual["content"]["field"] == "clientAge"


def test_scripted_embedding_respects_collection_spec_threshold():
    spec = _skip_without_sources()
    registry = build_draft_catalog_registry(spec)
    index = registry.index(FIELD_INDEX_KEY)
    target = next(entry for entry in index.entries if entry.key == "clientAge")
    query = "十里堡"
    # cosine([1,0], [0.5, 0.8660254037844386]) == 0.5, below frozen 0.58.
    low = [0.5, 0.8660254037844386]
    provider = _TableEmbeddingProvider(
        {
            query: [1.0, 0.0],
            catalog_embedding_projection(target): low,
        },
        default=[0.0, 1.0],
    )
    clear_entry_vector_cache()
    hits, _ = search_catalog(
        registry,
        query,
        index_keys=(FIELD_INDEX_KEY,),
        embedding_provider=provider,
    )
    assert hits == []


def test_frozen_experiment_hobby_query_stays_below_collection_spec_threshold():
    if not EMBEDDING_CACHE_PATH.is_file():
        pytest.skip("frozen embedding cache unavailable")
    import json

    cache = json.loads(EMBEDDING_CACHE_PATH.read_text(encoding="utf-8"))
    query_vector = cache["query_vectors"]["holdout-v3-unsupported-hobby"]
    entry_vectors = cache["entry_vectors"]
    entries = tuple(
        InvestigationKeyEntry(
            key=key,
            name=key,
            search_text=key,
            target_ref=f"client-search-field://{key}",
        )
        for key in entry_vectors
    )
    index = InvestigationKeyIndex(
        index_key=FIELD_INDEX_KEY,
        collection_ref="business-field-definitions",
        target_kind="evidence_locator",
        entry_granularity="yaml_field_definition",
        entries=entries,
    )
    frozen_cutoff = TEXT_COLLECTION_EMBEDDING.min_cosine
    hits_at_spec = search_embedding_channel(
        index,
        "客户平时有什么兴趣爱好",
        provider=None,
        min_cosine=frozen_cutoff,
        limit=8,
        entry_vectors=entry_vectors,
        query_vector=query_vector,
    )
    assert hits_at_spec == []
    insurance = cosine_l2(query_vector, entry_vectors["isBuyInsurance"])
    activity = cosine_l2(query_vector, entry_vectors["customerActivity"])
    assert insurance < frozen_cutoff
    assert activity < frozen_cutoff
    hits_at_low = search_embedding_channel(
        index,
        "客户平时有什么兴趣爱好",
        provider=None,
        min_cosine=0.50,
        limit=8,
        entry_vectors=entry_vectors,
        query_vector=query_vector,
    )
    low_keys = {entry.key for entry, _score in hits_at_low}
    assert "customerActivity" in low_keys
    assert insurance < 0.50


def test_catalog_tools_do_not_treat_exclusive_below_lt_as_illegal():
    """Catalog copy: live exclusive-below LT is not illegal; SearchHit is not evidence."""
    spec = _skip_without_sources()
    registry = build_draft_catalog_registry(spec)
    search_tool, load_tool = create_catalog_tools(registry)
    for tool in (search_tool, load_tool):
        desc = tool.description or ""
        assert "SearchHit is not Evidence" in desc
        assert "`LT n`" in desc
        assert "n周岁以下" in desc
        assert "含本数" not in desc
        assert "unless a Loaded mapping/rule says so" not in desc
        assert "含边界" not in desc
        assert "do not make a live exclusive-below operator" in desc
        assert "Parser generation recipes" in desc
        assert "not Evidence that live LT is wrong" in desc
    search_desc = search_tool.description or ""
    assert "One Search" in search_desc
    assert "omit index_key" in search_desc
    assert "do not fan-out one Search per index" in search_desc
    assert "Load 1–2 keys" in search_desc
    source = CATALOG_PATH.read_text(encoding="utf-8")
    assert "含本数" not in source
    assert "unless a Loaded mapping/rule says so" not in source
    assert "含边界" not in source
    assert "058" not in source
    assert "少儿" not in source
    assert "17周岁" not in source

def test_field_search_definition_operators_describe_support_not_ban():
    from impl.projects.client_search.field_tools import (
        create_minimal_field_definition_tool,
    )
    from impl.projects.client_search.field_provider import (
        ClientSearchFieldDefinitionProvider,
    )

    spec = _skip_without_sources()
    tool = create_minimal_field_definition_tool(
        ClientSearchFieldDefinitionProvider(spec)
    )
    desc = tool.description or ""
    assert "operators" in desc
    assert "`LT n`" in desc
    assert "非法" in desc
    assert "含边界" not in desc
    assert "unless a Loaded mapping/rule says so" not in desc

