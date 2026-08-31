"""Deterministic offline channel experiment for client_search field Key-Index.

Expected targets are evaluation-only: builders and strategies receive query and
source-derived entries, never probe labels or expected business outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re

import yaml
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from impl.core.context.embedding import BailianEmbeddingProvider, validate_embedding_vector
from impl.core.project_loader import load_project
from impl.core.schema import InvestigationKeyEntry
from impl.core.portable_artifact import (
    project_artifact_repository_root,
    write_active_artifact,
    write_portable_export,
)
from impl.projects.client_search.field_tools import (
    _load_field_key_index,
    build_field_key_index_registry,
)

DEVELOPMENT_PROBES: tuple[dict[str, Any], ...] = (
    {"id": "source-term-insure-date", "category": "source_term", "query": "投保日期", "required": ["policies_insure_date"]},
    {"id": "paraphrase-buy-insurance", "category": "source_paraphrase", "query": "去年买保险的客户", "required": ["policies_insure_date"]},
    {"id": "source-term-policy-effective", "category": "source_term", "query": "保单生效日期", "required": ["polNoInfo.poleffdate"]},
    {"id": "source-phrase-policy-effective", "category": "source_paraphrase", "query": "本月生效的保单", "required": ["polNoInfo.poleffdate"]},
    {"id": "multi-object-applicant", "category": "ambiguity_multi_object", "query": "投保人姓名陈金秀", "required": ["polNoInfo.applicantname"]},
    {"id": "paraphrase-applicant", "category": "source_paraphrase", "query": "保单的投保人是陈金秀", "required": ["polNoInfo.applicantname"]},
    {"id": "source-term-mobile-suffix", "category": "source_term", "query": "手机号后四位1234", "required": ["clientMobile"]},
    {"id": "ambiguous-self-age", "category": "ambiguity_multi_object", "query": "年龄30岁", "required": ["clientAge"]},
    {"id": "multi-object-child-age", "category": "ambiguity_multi_object", "query": "子女年龄10岁", "required": ["familyInfo.familyclientage", "familyInfo.familyrelation"]},
    {"id": "multi-object-parent-age", "category": "ambiguity_multi_object", "query": "父母60岁以下", "required": ["familyInfo.familyclientage", "familyInfo.familyrelation"]},
    {"id": "source-term-client-age", "category": "source_term", "query": "客户年龄", "required": ["clientAge"]},
    {"id": "source-term-family-birthday", "category": "source_term", "query": "家庭成员生日", "required": ["familyInfo.familyclientbirthday"]},
    {"id": "multi-term-prospect-source", "category": "unsupported", "query": "准客来源包含综拓 O2O 意健险", "required": ["pcustSourcType"]},
    {"id": "source-term-plan-name", "category": "source_term", "query": "投保险种名称", "required": ["polNoInfo.plancodeinfo.planfullname"]},
    {"id": "ambiguous-client-number", "category": "ambiguity_multi_object", "query": "客户号后四位", "required": ["clientNo"]},
    {"id": "source-term-policy-number", "category": "source_term", "query": "保单号查询", "required": ["polNo"]},
    {"id": "irrelevant-weather", "category": "irrelevant", "query": "天气怎么样", "required": []},
    {"id": "irrelevant-poem", "category": "irrelevant", "query": "帮我写一首诗", "required": []},
    {"id": "irrelevant-license", "category": "irrelevant", "query": "量子航海许可证", "required": []},
    {"id": "development-child-colloquial", "category": "source_paraphrase", "query": "孩子今年12岁", "required": ["familyInfo.familyclientage", "familyInfo.familyrelation"]},
    {"id": "development-unsupported-color", "category": "unsupported", "query": "客户最喜欢的颜色", "required": []},
    {"id": "development-unsupported-pet-name", "category": "unsupported", "query": "客户宠物名字", "required": []},
    # Former holdout: invalidated and moved to development after its failures informed channel design.
    {"id": "development-former-holdout-stable-client-number", "category": "stable_identifier", "query": "clientNo", "required": ["clientNo"]},
    {"id": "development-former-holdout-insured-mobile", "category": "source_term", "query": "被保人手机号", "required": ["polNoInfo.insuredphoneno"]},
    {"id": "development-former-holdout-child-age", "category": "source_paraphrase", "query": "小孩不到6岁", "required": ["familyInfo.familyclientage", "familyInfo.familyrelation"]},
    {"id": "development-former-holdout-partner-age", "category": "ambiguity_multi_object", "query": "爱人不到45岁", "required": ["familyInfo.familyclientage", "familyInfo.familyrelation"]},
    {"id": "development-former-holdout-beneficiary-name", "category": "search_to_load", "query": "受益人姓名", "required": ["polNoInfo.benefinfo.benefname"]},
    {"id": "development-former-holdout-favorite-film", "category": "unsupported", "query": "客户最爱的电影", "required": []},
    {"id": "development-former-holdout-coffee", "category": "irrelevant", "query": "怎么制作咖啡", "required": []},
    {"id": "development-former-holdout-galaxy", "category": "irrelevant", "query": "银河系有多老", "required": []},
)

# Frozen before the first embedding evaluation. Do not tune candidates from these results.
HOLDOUT_PROBES: tuple[dict[str, Any], ...] = (
    {"id": "holdout-v3-spouse-birthday", "category": "source_paraphrase", "query": "另一半是哪天出生的", "required": ["familyInfo.familyclientbirthday", "familyInfo.familyrelation"]},
    {"id": "holdout-v3-family-phone", "category": "source_paraphrase", "query": "家里人的联系电话", "required": ["familyInfo.familyclientmobile"]},
    {"id": "holdout-v3-insured-name", "category": "source_paraphrase", "query": "这张保单保的是谁", "required": ["polNoInfo.insuredname"]},
    {"id": "holdout-v3-occupation", "category": "source_paraphrase", "query": "客户是做哪一行的", "required": ["profName"]},
    {"id": "holdout-v3-contact-address", "category": "search_to_load", "query": "客户收信寄到哪里", "required": ["CONTACT_ADDRESS_FIELD"]},
    {"id": "holdout-v3-unsupported-hobby", "category": "unsupported", "query": "客户平时有什么兴趣爱好", "required": []},
    {"id": "holdout-v3-irrelevant-recipe", "category": "irrelevant", "query": "红烧肉怎么做", "required": []},
    {"id": "holdout-v3-irrelevant-astronomy", "category": "irrelevant", "query": "黑洞为什么会蒸发", "required": []},
)

Strategy = Callable[[str, Sequence[InvestigationKeyEntry], int], Sequence[tuple[InvestigationKeyEntry, float, dict[str, float]]]]


def _normalise(value: Any) -> str:
    text = "".join(char for char in str(value or "").casefold() if char.isalnum() or "\u4e00" <= char <= "\u9fff")
    return re.sub(r"\d+", "0", text)


def _bigrams(value: Any) -> set[str]:
    text = _normalise(value)
    return {text[i:i + 2] for i in range(max(0, len(text) - 1))}


def _phrases(value: Any) -> list[str]:
    return [text for part in re.split(r"[\s，。；、：:（）()|/]+", str(value or "")) if len(text := _normalise(part)) >= 2]


def _augmented_source_entries(spec, entries: Sequence[InvestigationKeyEntry]) -> tuple[InvestigationKeyEntry, ...]:
    enums = yaml.safe_load(Path(spec.source_path("field_enums")).read_text(encoding="utf-8")) or {}
    mappings = yaml.safe_load(Path(spec.source_path("value_mappings")).read_text(encoding="utf-8")) or {}
    source_terms: dict[str, list[str]] = {entry.key: [] for entry in entries}
    for entry in entries:
        enum_config = enums.get(entry.key) or {}
        if isinstance(enum_config, dict):
            source_terms[entry.key].extend(str(value) for value in enum_config.get("values") or [])
        mapping_config = mappings.get(entry.key) or {}
        if isinstance(mapping_config, dict):
            for source_term, target_term in mapping_config.items():
                source_terms[entry.key].extend((str(source_term), str(target_term)))
    by_key = {entry.key: entry for entry in entries}
    for source_entry in entries:
        explicit_refs = set(re.findall(r"[A-Za-z][A-Za-z0-9_.]*", source_entry.search_text))
        explicit_refs.discard(source_entry.key)
        for target_key in explicit_refs & set(by_key):
            # A source-declared dependency lets both field entries expose the
            # other's source-derived navigation vocabulary; no case labels enter.
            source_terms[source_entry.key].extend(source_terms[target_key])
            source_terms[target_key].append(source_entry.search_text)
    return tuple(
        InvestigationKeyEntry(
            key=entry.key,
            name=entry.name,
            search_text=" ".join((entry.search_text, *source_terms[entry.key])),
            target_ref=entry.target_ref,
        )
        for entry in entries
    )

def _exact_strategy(query: str, entries: Sequence[InvestigationKeyEntry], limit: int):
    raw_query = str(query or "").casefold()
    query_text = _normalise(query)
    ranked = []
    for entry in entries:
        scores = []
        if entry.key.casefold() in raw_query:
            scores.append(100.0)
        for phrase in _phrases(entry.search_text):
            if phrase == query_text or phrase in query_text:
                scores.append(float(20 + min(len(phrase), 20)))
        if scores:
            ranked.append((entry, max(scores), {"exact": max(scores)}))
    ranked.sort(key=lambda item: (-item[1], item[0].key))
    return ranked[:limit]



_LEGACY_IGNORED_QUERY_CHARS = set("客户的有是和与及或并且一个哪些名单帮我找查询")


def _legacy_searchable_chars(value: Any) -> set[str]:
    return {
        char
        for char in str(value or "").casefold()
        if (
            not char.isspace()
            and char not in _LEGACY_IGNORED_QUERY_CHARS
            and (char.isalpha() or "\u4e00" <= char <= "\u9fff")
        )
    }


def _legacy_char_heuristic(query, entries, limit):
    """Frozen experiment baseline; not Draft Judge core."""
    query_text = str(query or "").strip()
    query_chars = _legacy_searchable_chars(query_text)
    if not query_chars:
        return []
    candidates = []
    for entry in entries:
        score = len(query_chars & _legacy_searchable_chars(entry.search_text))
        if entry.key.casefold() in query_text.casefold():
            score += 100
        if "岁" in query_text or "周岁" in query_text:
            if "年龄" in entry.name or "age" in entry.key.casefold():
                score += 20
            if "family" in entry.key.casefold():
                score -= 5
        if score >= 2:
            candidates.append((entry, float(score)))
    candidates.sort(key=lambda item: (-item[1], item[0].key))
    return candidates[:limit]


def _current_strategy(query: str, entries: Sequence[InvestigationKeyEntry], limit: int):
    return [(entry, float(score or 0), {"lexical": float(score or 0)}) for entry, score in _legacy_char_heuristic(query, entries, limit)]


def _source_phrase_idf_strategy(entries: Sequence[InvestigationKeyEntry], *, min_query_coverage: float = 0.0) -> Strategy:
    document_frequency: Counter[str] = Counter()
    for entry in entries:
        document_frequency.update(_bigrams(entry.search_text))
    count = len(entries)

    def idf(term: str) -> float:
        return math.log((count + 1) / (document_frequency[term] + 1)) + 1

    def search(query: str, candidates: Sequence[InvestigationKeyEntry], limit: int):
        query_text = _normalise(query)
        query_bigrams = _bigrams(query_text)
        ranked = []
        if len(query_text) < 2:
            return ranked
        for entry in candidates:
            exact_phrases = [
                phrase for phrase in _phrases(entry.search_text)
                if (phrase == query_text or (len(phrase) >= 3 and phrase in query_text) or (len(query_text) >= 3 and query_text in phrase))
            ]
            shared = query_bigrams & _bigrams(entry.search_text)
            key_hit = entry.key.casefold() in str(query or "").casefold()
            coverage = len(shared) / len(query_bigrams) if query_bigrams else 0.0
            if not key_hit and not exact_phrases and (len(shared) < 2 or coverage < min_query_coverage):
                continue
            score = sum(idf(term) for term in sorted(shared)) + sum(8 + min(len(phrase), 12) for phrase in exact_phrases) + (100 * coverage) + (100 if key_hit else 0)
            ranked.append((entry, float(score), {"lexical": float(score)}))
        ranked.sort(key=lambda item: (-item[1], item[0].key))
        return ranked[:limit]

    return search


def _fused_strategy(exact: Strategy, lexical: Strategy) -> Strategy:
    def search(query: str, entries: Sequence[InvestigationKeyEntry], limit: int):
        merged: dict[str, tuple[InvestigationKeyEntry, dict[str, float]]] = {}
        for strategy in (exact, lexical):
            for entry, _score, channels in strategy(query, entries, max(limit, 8)):
                existing = merged.get(entry.key)
                combined = dict(existing[1]) if existing else {}
                combined.update(channels)
                merged[entry.key] = (entry, combined)
        ranked = []
        for entry, channels in merged.values():
            # Exact preserves formal identifiers/phrases; lexical supplies recall.
            score = (1000 if "exact" in channels else 0) + sum(channels[key] for key in sorted(channels))
            ranked.append((entry, float(score), channels))
        ranked.sort(key=lambda item: (-item[1], item[0].key))
        return ranked[:limit]
    return search


EMBEDDING_CACHE_PATH = Path(__file__).parent.parent / "investigation/judge/experiments/field-key-index-embeddings.json"
EMBEDDING_PROJECTION_VERSION = "client-search-field-projection-v1"
EMBEDDING_MODEL_VERSION = "dashscope-text-embedding-api-v1"


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _embedding_projection(entry: InvestigationKeyEntry) -> str:
    return f"字段标识: {entry.key}\n字段名称: {entry.name}\n检索说明: {entry.search_text}"


def _embedding_input_hash(entries: Sequence[InvestigationKeyEntry], probes: Sequence[dict[str, Any]]) -> str:
    payload = {
        "projection_version": EMBEDDING_PROJECTION_VERSION,
        "entries": {entry.key: _embedding_projection(entry) for entry in entries},
        "queries": {probe["id"]: probe["query"] for probe in probes},
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _embed_batched(provider: Any, texts: Sequence[str], batch_size: int = 10) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(provider.embed(texts[start:start + batch_size]))
    return vectors


def _entry_projection_hashes(entries: Sequence[InvestigationKeyEntry]) -> dict[str, str]:
    return {
        entry.key: hashlib.sha256(_embedding_projection(entry).encode("utf-8")).hexdigest()
        for entry in entries
    }


def _query_hashes(probes: Sequence[dict[str, Any]]) -> dict[str, str]:
    return {
        str(probe["id"]): hashlib.sha256(str(probe["query"]).encode("utf-8")).hexdigest()
        for probe in probes
    }


def _refresh_embedding_cache(
    entries: Sequence[InvestigationKeyEntry],
    probes: Sequence[dict[str, Any]],
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Entry-keyed embedding refresh (staleness facility Q5b).

    Re-embeds only entries whose projection hash changed; unchanged vectors are
    carried over from the existing receipt. Queries are frozen probes and are
    re-embedded only when their texts changed. Without a per-entry baseline the
    first refresh re-embeds everything and establishes the baseline.
    """
    provider = BailianEmbeddingProvider()
    entry_texts = {entry.key: _embedding_projection(entry) for entry in entries}
    entry_hashes = {
        key: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for key, text in entry_texts.items()
    }
    baseline = dict((existing or {}).get("entry_sha256") or {})
    changed_keys = [key for key, current in entry_hashes.items() if baseline.get(key) != current]
    if existing and set(existing.get("entry_vectors") or {}) == set(entry_texts) and not changed_keys:
        entry_vectors = dict(existing["entry_vectors"])
    else:
        entry_vectors = dict((existing or {}).get("entry_vectors") or {})
        rebuild_keys = sorted(set(changed_keys or list(entry_texts)) | (set(entry_texts) - set(entry_vectors)))
        rebuild_texts = [entry_texts[key] for key in rebuild_keys]
        rebuilt_vectors = _embed_batched(provider, rebuild_texts)
        for key, vector in zip(rebuild_keys, rebuilt_vectors):
            entry_vectors[key] = vector

    query_texts = {str(probe["id"]): str(probe["query"]) for probe in probes}
    query_hashes = _query_hashes(probes)
    if (
        existing
        and dict((existing or {}).get("query_sha256") or {}) == query_hashes
        and set(existing.get("query_vectors") or {}) == set(query_texts)
    ):
        query_vectors = dict(existing["query_vectors"])
    else:
        vectors = _embed_batched(provider, list(query_texts.values()))
        query_vectors = dict(zip(query_texts.keys(), vectors))

    cache = {
        "schema_version": 1,
        "provider": "bailian",
        "model": provider.model_id,
        "model_version": EMBEDDING_MODEL_VERSION,
        "projection_version": EMBEDDING_PROJECTION_VERSION,
        "normalization": "cosine_l2_at_scoring",
        "input_sha256": _embedding_input_hash(entries, probes),
        "entry_sha256": entry_hashes,
        "query_sha256": query_hashes,
        "entry_vectors": entry_vectors,
        "query_vectors": query_vectors,
    }
    EMBEDDING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    repository_root = project_artifact_repository_root(EMBEDDING_CACHE_PATH)
    if repository_root is not None:
        write_active_artifact(
            "key_index_experiment",
            EMBEDDING_CACHE_PATH,
            cache,
            repository_root=repository_root,
        )
    else:
        write_portable_export(EMBEDDING_CACHE_PATH, cache)
    return cache


def _load_embedding_cache(entries: Sequence[InvestigationKeyEntry], probes: Sequence[dict[str, Any]], *, refresh: bool = False) -> dict[str, Any]:
    if refresh:
        try:
            existing = json.loads(EMBEDDING_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        cache = _refresh_embedding_cache(entries, probes, existing=existing)
    else:
        cache = json.loads(EMBEDDING_CACHE_PATH.read_text(encoding="utf-8"))
    if cache.get("input_sha256") != _embedding_input_hash(entries, probes):
        raise ValueError("embedding cache input/projection drifted; rerun with --refresh-embeddings")
    if cache.get("model_version") != EMBEDDING_MODEL_VERSION or cache.get("projection_version") != EMBEDDING_PROJECTION_VERSION:
        raise ValueError("embedding cache model/projection version drifted")
    expected_keys = {entry.key for entry in entries}
    if set(cache.get("entry_vectors") or {}) != expected_keys:
        raise ValueError("embedding cache does not cover every index entry")
    expected_queries = {probe["id"] for probe in probes}
    if set(cache.get("query_vectors") or {}) != expected_queries:
        raise ValueError("embedding cache does not cover every frozen probe")
    dimensions = 0
    for vector in list(cache["entry_vectors"].values()) + list(cache["query_vectors"].values()):
        normalized = validate_embedding_vector(vector, expected_dimensions=dimensions)
        dimensions = dimensions or len(normalized)
    cache["dimensions"] = dimensions
    return cache


def _embedding_strategy(cache: Mapping[str, Any], probes: Sequence[dict[str, Any]], *, threshold: float) -> Strategy:
    query_ids = {probe["query"]: probe["id"] for probe in probes}
    entry_vectors = cache["entry_vectors"]
    query_vectors = cache["query_vectors"]

    def search(query: str, entries: Sequence[InvestigationKeyEntry], limit: int):
        probe_id = query_ids.get(query)
        if probe_id is None:
            raise ValueError("frozen embedding simulation only accepts registered probes")
        query_vector = query_vectors[probe_id]
        ranked = []
        for entry in entries:
            similarity = _cosine(query_vector, entry_vectors[entry.key])
            if similarity >= threshold:
                ranked.append((entry, float(similarity), {"embedding": float(similarity)}))
        ranked.sort(key=lambda item: (-item[1], item[0].key))
        return ranked[:limit]

    return search


def _audited_multichannel_strategy(exact: Strategy, lexical: Strategy, embedding: Strategy) -> Strategy:
    def search(query: str, entries: Sequence[InvestigationKeyEntry], limit: int):
        merged: dict[str, tuple[InvestigationKeyEntry, dict[str, float]]] = {}
        for strategy in (exact, lexical, embedding):
            for entry, _score, channels in strategy(query, entries, max(limit, 8)):
                existing = merged.get(entry.key)
                combined = dict(existing[1]) if existing else {}
                combined.update(channels)
                merged[entry.key] = (entry, combined)
        ranked = []
        for entry, channels in merged.values():
            # Formal identifiers remain dominant. Lexical remains the stable anchor;
            # embedding only supplements misses and cannot create Evidence authority.
            score = (1000 if "exact" in channels else 0)
            score += channels.get("lexical", 0.0)
            score += channels.get("embedding", 0.0) * 100.0
            ranked.append((entry, float(score), channels))
        ranked.sort(key=lambda item: (-item[1], item[0].key))
        return ranked[:limit]
    return search


def _probe_hash(probes: Sequence[dict[str, Any]]) -> str:
    payload = json.dumps(probes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _run_probe_set(probes, strategy: Strategy, registry, entries: Sequence[InvestigationKeyEntry]) -> dict[str, Any]:
    rows = []
    relevant = irrelevant = top1 = top3 = top8 = false_positive = resolved = loaded_entries = loaded_chars = 0
    deterministic = True
    for probe in probes:
        ranked = list(strategy(probe["query"], list(entries), 8))[:8]
        repeated = list(strategy(probe["query"], list(entries), 8))[:8]
        keys = [entry.key for entry, _score, _channels in ranked]
        deterministic = deterministic and keys == [entry.key for entry, _score, _channels in repeated]
        required = set(probe["required"])
        if required:
            relevant += 1
            top1 += int(required <= set(keys[:1]))
            top3 += int(required <= set(keys[:3]))
            top8 += int(required <= set(keys[:8]))
        else:
            irrelevant += 1
            false_positive += int(bool(keys))
        receipts = []
        for entry, score, channels in ranked:
            loaded, receipt = registry.load("client-search.field-definitions", entry.key)
            resolved += int(bool(receipt.resolved_locator))
            loaded_entries += 1
            chars = len(json.dumps(loaded["content"], ensure_ascii=False, sort_keys=True))
            loaded_chars += chars
            receipts.append({"key": entry.key, "score": score, "matched_channels": sorted(channels), "channel_scores": channels, "resolved": bool(receipt.resolved_locator), "loaded_chars": chars})
        rows.append({"probe_id": probe["id"], "category": probe["category"], "query": probe["query"], "required_targets": sorted(required), "hits": receipts, "pass": required <= set(keys) if required else not keys})
    count = len(probes)
    return {
        "deterministic_search": deterministic,
        "metrics": {
            "relevant_probe_count": relevant,
            "all_required_top1": top1,
            "all_required_top3": top3,
            "all_required_top8": top8,
            "top8_recall_rate": top8 / relevant if relevant else 1.0,
            "irrelevant_probe_count": irrelevant,
            "irrelevant_false_positive_count": false_positive,
            "irrelevant_rejection_rate": (irrelevant - false_positive) / irrelevant if irrelevant else 1.0,
            "search_to_load_resolution_rate": resolved / loaded_entries if loaded_entries else 1.0,
            "average_loaded_entries": loaded_entries / count,
            "average_loaded_chars": loaded_chars / count,
        },
        "rows": rows,
    }


def _candidate(candidate_id, channels, strategy, registry, entries, projection_fields=None, embedding_audit=None):
    return {
        "candidate_id": candidate_id,
        "experiment_scope": "retrieval_channel_candidate",
        "retrieval_channels": list(channels),
        "default_retrieval_channels": list(channels),
        "source_derived": True,
        "forbidden_inputs": [],
        "deterministic_builder": True,
        "projection_provenance": {"source_fields": projection_fields or ["field", "retrieval_text", "description"], "ai_authored_terms": False},
        **({"embedding_audit": embedding_audit} if embedding_audit else {}),
        "suite": {
            "index_key": "client-search.field-definitions",
            "collection_ref": "business-field-definitions",
            "builder": "impl.projects.client_search.field_tools._load_field_key_index",
            "projection_fields": projection_fields or ["field", "retrieval_text", "description"],
            "search_strategy": candidate_id,
            "target_ref_template": "client-search-field://<field>",
            "resolver": "ClientSearchFieldDefinitionProvider.get_field_definition",
            "load_operation": "InvestigationKeyIndexRegistry.load",
        },
        "results": {
            "development": _run_probe_set(DEVELOPMENT_PROBES, strategy, registry, entries),
            "holdout": _run_probe_set(HOLDOUT_PROBES, strategy, registry, entries),
        },
    }


def build_report(*, refresh_embeddings: bool = False) -> dict[str, Any]:
    spec = load_project("client_search")
    index = _load_field_key_index(spec)
    entries = list(index.entries)
    registry = build_field_key_index_registry(spec)
    entry_payload = json.dumps([entry.as_dict() for entry in entries], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    resolved = sum(bool(registry.load("client-search.field-definitions", entry.key)[1].resolved_locator) for entry in entries)
    lexical = _source_phrase_idf_strategy(entries)
    augmented_entries = _augmented_source_entries(spec, entries)
    augmented_lexical = _source_phrase_idf_strategy(augmented_entries)
    linked_coverage_lexical = _source_phrase_idf_strategy(augmented_entries, min_query_coverage=0.50)
    all_probes = DEVELOPMENT_PROBES + HOLDOUT_PROBES
    embedding_cache = _load_embedding_cache(augmented_entries, all_probes, refresh=refresh_embeddings)
    embedding_audit = {
        "provider": embedding_cache["provider"],
        "model": embedding_cache["model"],
        "model_version": embedding_cache["model_version"],
        "projection_version": embedding_cache["projection_version"],
        "normalization": embedding_cache["normalization"],
        "dimensions": embedding_cache["dimensions"],
        "cache_input_sha256": embedding_cache["input_sha256"],
    }
    candidates = [
        _candidate("current-char-heuristic", ("lexical",), _current_strategy, registry, entries),
        _candidate("source-exact", ("exact",), _exact_strategy, registry, entries),
        _candidate("source-phrase-idf-min2-bigram", ("lexical",), lexical, registry, entries),
        _candidate("source-exact-plus-lexical", ("exact", "lexical"), _fused_strategy(_exact_strategy, lexical), registry, entries),
        _candidate(
            "source-enum-mapping-lexical", ("lexical",), augmented_lexical, registry, augmented_entries,
            ["field", "retrieval_text", "description", "field_enums.values", "value_mappings.keys", "value_mappings.values"],
        ),
        _candidate(
            "source-linked-coverage-lexical", ("lexical",), linked_coverage_lexical, registry, augmented_entries,
            ["field", "retrieval_text", "description", "field_enums.values", "value_mappings.keys", "value_mappings.values", "source_cross_references"],
        ),
        *[
            _candidate(
                f"source-exact-lexical-embedding-t{int(threshold * 100)}",
                ("exact", "lexical", "embedding"),
                _audited_multichannel_strategy(
                    _exact_strategy,
                    linked_coverage_lexical,
                    _embedding_strategy(embedding_cache, all_probes, threshold=threshold),
                ),
                registry,
                augmented_entries,
                ["field", "retrieval_text", "description", "field_enums.values", "value_mappings.keys", "value_mappings.values", "source_cross_references"],
                embedding_audit,
            )
            for threshold in (0.45, 0.55, 0.65)
        ],
    ]
    thresholds = {"top8_recall_rate_min": 0.85, "irrelevant_rejection_rate_min": 1.0, "search_to_load_resolution_rate_min": 1.0, "average_loaded_entries_max": 8}
    shortlist = []
    for candidate in candidates:
        dev = candidate["results"]["development"]["metrics"]
        holdout = candidate["results"]["holdout"]["metrics"]
        if all((
            dev["top8_recall_rate"] >= thresholds["top8_recall_rate_min"],
            holdout["top8_recall_rate"] >= thresholds["top8_recall_rate_min"],
            dev["irrelevant_rejection_rate"] >= thresholds["irrelevant_rejection_rate_min"],
            holdout["irrelevant_rejection_rate"] >= thresholds["irrelevant_rejection_rate_min"],
            dev["search_to_load_resolution_rate"] >= thresholds["search_to_load_resolution_rate_min"],
            holdout["search_to_load_resolution_rate"] >= thresholds["search_to_load_resolution_rate_min"],
            dev["average_loaded_entries"] <= thresholds["average_loaded_entries_max"],
            holdout["average_loaded_entries"] <= thresholds["average_loaded_entries_max"],
        )):
            shortlist.append(candidate["candidate_id"])
    manifest = json.loads((Path(__file__).parent / "investigation/judge/manifest.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 2,
        "experiment_id": "client-search-field-key-index-v3",
        "project_id": "client_search",
        "role": "judge",
        "source_revision": manifest["source_revision"],
        "collection_profile": {
            "collection_ref": "business-field-definitions",
            "object_count": len(entries),
            "stable_identifier": "field",
            "load_boundary": "one field definition",
            "runtime_need": "locate a small set of field definitions without preloading the full capability collection",
            "full_load_pressure_observed": True,
        },
        "channel_consideration": {
            "exact": {"decision": "experiment", "reason": "stable field keys and source phrases exist"},
            "lexical": {"decision": "experiment", "reason": "retrieval_text contains source business terminology"},
            "embedding": {"decision": "experiment", "reason": "real Bailian embeddings are evaluated offline as a supplementary channel with frozen model/projection receipts"},
            "rerank": {"decision": "deferred", "reason": "first test simple auditable channel fusion; add a reranker only if the frozen candidate budget shows a concrete need"},
        },
        "probe_sets": {
            "development": {"sha256": _probe_hash(DEVELOPMENT_PROBES), "count": len(DEVELOPMENT_PROBES), "categories": sorted({p["category"] for p in DEVELOPMENT_PROBES}), "used_for_tuning": True},
            "holdout": {"sha256": _probe_hash(HOLDOUT_PROBES), "count": len(HOLDOUT_PROBES), "categories": sorted({p["category"] for p in HOLDOUT_PROBES}), "used_for_tuning": False},
        },
        "builder_output_sha256": hashlib.sha256(entry_payload.encode()).hexdigest(),
        "all_entry_target_resolution_rate": resolved / len(entries),
        "thresholds": thresholds,
        "candidates": candidates,
        "decision": {
            "status": "provisional" if shortlist else "unresolved",
            "shortlist": shortlist,
            "selected_candidate": "",
            "loop_evidence": None,
            "reason": (
                "Simulation shortlisted candidates; frozen Draft Loop evidence is required before selected."
                if shortlist else
                "No candidate passes both frozen development and unseen holdout thresholds; do not enter Draft Loop or silently fall back to the full Collection."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--refresh-embeddings", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build_report(refresh_embeddings=args.refresh_embeddings), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_portable_export(args.output, rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
