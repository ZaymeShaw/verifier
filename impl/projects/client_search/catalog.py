"""Draft Judge Catalog: registry-driven key-index navigation.

E1 consumption only. Not a Manifest selection. Exact + query-internal rewrite
remain the lexical channels. Embedding is an additional channel on text
collections (field_definitions, enhanced_rules) when a provider is supplied;
abbr/mappings stay exact-first (embedding rejected). Default search still
covers every registered index. SearchHit is not Evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import quote

import yaml

from impl.core.investigation_key_index import (
    InvestigationKeyIndexRegistry,
    KeyIndexSearchHit,
)
from impl.core.schema import InvestigationKeyEntry, InvestigationKeyIndex, ProjectSpec
from impl.projects.client_search.catalog_embedding import (
    search_embedding_channel,
)
from impl.projects.client_search.field_provider import ClientSearchFieldDefinitionProvider
from impl.tools import ToolResult, VerifiableTool

FIELD_INDEX_KEY = "client-search.field-definitions"
RULES_INDEX_KEY = "client-search.enhanced-rules"
MAPPINGS_INDEX_KEY = "client-search.value-mappings"
ABBR_INDEX_KEY = "client-search.abbrname-enums"

EXACT_FULL_SCORE = 200.0
EXACT_TOKEN_SCORE = 180.0
REWRITE_SCORE = 40.0
STRONG_HIT_FLOOR = 150.0

_TOKEN_SPLIT = re.compile(r"[\s，。；、：:（）()|/,\.]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_FIELD_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*(\.[A-Za-z][A-Za-z0-9_]*)*$")
_ENGLISH_PATH = re.compile(r"[A-Za-z][A-Za-z0-9]*(\.[A-Za-z][A-Za-z0-9_]+)+")
_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9]*")


@dataclass(frozen=True)
class ChannelDecl:
    name: str
    status: str
    reason: str


@dataclass(frozen=True)
class EmbeddingChannelMeta:
    """Frozen CollectionSpec embedding contract.

    client_search Draft text collections use min_cosine=0.58 (Key-Index
    experiment t55/t58 band). A 0.50 cutoff recalled unsupported hobby
    paraphrases onto insurance-intent fields in that experiment. Keep the
    number here, not in Judge business-word ifs.
    """

    min_cosine: float
    provider: str = "bailian"
    projection_version: str = "client-search-field-projection-v1"
    score_scale: float = 100.0


# Frozen Draft text-collection cutoff. Not a runtime fallback and not a
# business-lexicon test; search_catalog reads it only from CollectionSpec.
TEXT_COLLECTION_EMBEDDING = EmbeddingChannelMeta(min_cosine=0.58)


@dataclass(frozen=True)
class CollectionSpec:
    collection_id: str
    index_key: str
    object_boundary: str
    match_policy: str
    channels: tuple[ChannelDecl, ...]
    entry_granularity: str
    target_kind: str = "evidence_locator"
    notes: str = ""
    embedding: EmbeddingChannelMeta | None = None


COLLECTION_SPECS: tuple[CollectionSpec, ...] = (
    CollectionSpec(
        collection_id="business-field-definitions",
        index_key=FIELD_INDEX_KEY,
        object_boundary="field",
        match_policy="exact_membership",
        entry_granularity="yaml_field_definition",
        channels=(
            ChannelDecl("exact", "active", "equality on field key, short name, source phrases"),
            ChannelDecl("rewrite", "active", "query-internal n-grams; ultrashort skipped"),
            ChannelDecl(
                "embedding",
                "active",
                "Bailian supplementary recall; CollectionSpec min_cosine",
            ),
        ),
        notes="exact + rewrite first; embedding additional when a provider is supplied",
        embedding=TEXT_COLLECTION_EMBEDDING,
    ),
    CollectionSpec(
        collection_id="business-enhanced-rules",
        index_key=RULES_INDEX_KEY,
        object_boundary="rule",
        match_policy="exact_membership",
        entry_granularity="yaml_rule",
        channels=(
            ChannelDecl("exact", "active", "equality on rule name"),
            ChannelDecl("rewrite", "active", "query-internal n-grams; ultrashort skipped"),
            ChannelDecl(
                "embedding",
                "active",
                "Bailian supplementary recall; CollectionSpec min_cosine",
            ),
        ),
        embedding=TEXT_COLLECTION_EMBEDDING,
    ),
    CollectionSpec(
        collection_id="business-value-mappings",
        index_key=MAPPINGS_INDEX_KEY,
        object_boundary="spoken_key",
        match_policy="exact_membership",
        entry_granularity="yaml_spoken_key",
        channels=(
            ChannelDecl("exact", "active", "equality on mapping spoken keys"),
            ChannelDecl("rewrite", "active", "query-internal n-grams; ultrashort skipped"),
            ChannelDecl("embedding", "rejected", "membership must be exact"),
        ),
    ),
    CollectionSpec(
        collection_id="business-abbrname-enums",
        index_key=ABBR_INDEX_KEY,
        object_boundary="enum_member",
        match_policy="exact_membership",
        entry_granularity="yaml_enum_member",
        channels=(
            ChannelDecl("exact", "active", "equality on abbrname enum members"),
            ChannelDecl("rewrite", "active", "query-internal n-grams; ultrashort skipped"),
            ChannelDecl("embedding", "rejected", "membership must be exact"),
        ),
    ),
)

COLLECTION_SPEC_BY_INDEX_KEY = {item.index_key: item for item in COLLECTION_SPECS}


def normalize_needle(value: Any) -> str:
    return str(value or "").strip().casefold()


def is_ultrashort(query: str) -> bool:
    text = str(query or "").strip()
    if len(text) <= 2:
        return True
    compact = "".join(text.split())
    return bool(_LATIN_TOKEN.fullmatch(compact))


def _is_banned_variant(text: str) -> bool:
    token = str(text or "").strip()
    if not token:
        return True
    if _ENGLISH_PATH.search(token):
        return True
    if _FIELD_ID.fullmatch(token) and "." not in token and _LATIN_TOKEN.fullmatch(token):
        return True
    return False


def rewrite_query(query: str) -> tuple[str, ...]:
    """Query-internal variants only: contiguous chars/n-grams of the original.

    Skip ultrashort originals (len<=2 or a single latin token). Ban field ids,
    English paths, and any string that is not a contiguous subset of the query
    (no new entities).
    """
    raw = str(query or "").strip()
    if not raw or is_ultrashort(raw) or _ENGLISH_PATH.search(raw):
        return ()
    seen: set[str] = {raw, raw.casefold()}
    variants: list[str] = []

    def add(piece: str) -> None:
        token = piece.strip()
        if not token:
            return
        folded = token.casefold()
        if token in seen or folded in seen:
            return
        if len(token) <= 2 or _LATIN_TOKEN.fullmatch(token):
            return
        if _is_banned_variant(token):
            return
        if token not in raw and folded not in raw.casefold():
            return
        seen.add(token)
        seen.add(folded)
        variants.append(token)

    for run in _CJK_RUN.findall(raw):
        for size in range(3, len(run) + 1):
            for index in range(0, len(run) - size + 1):
                add(run[index : index + size])
    for run in _LATIN_RUN.findall(raw):
        if run != raw and len(run) >= 3 and not _LATIN_TOKEN.fullmatch(raw.strip()):
            add(run)
    return tuple(variants)


def exact_needles(query: str) -> tuple[str, ...]:
    """Full query plus punctuation-split tokens. No short-token substring."""
    raw = str(query or "").strip()
    if not raw:
        return ()
    needles: list[str] = []
    seen: set[str] = set()

    def add(piece: str) -> None:
        token = normalize_needle(piece)
        if not token or token in seen:
            return
        seen.add(token)
        needles.append(token)

    add(raw)
    for part in _TOKEN_SPLIT.split(raw):
        add(part)
    return tuple(needles)


def _entry_members(entry: InvestigationKeyEntry) -> tuple[str, ...]:
    members: list[str] = []
    seen: set[str] = set()

    def add(piece: str, *, minimum: int = 1) -> None:
        token = normalize_needle(piece)
        if len(token) < minimum or token in seen:
            return
        seen.add(token)
        members.append(token)

    add(entry.key)
    add(entry.name)
    for part in _TOKEN_SPLIT.split(entry.search_text or ""):
        # Source phrases participate as exact members; skip ultrashort tokens
        # so a short token cannot equality-hit a longer name via a 2-char piece.
        add(part, minimum=3)
    return tuple(members)


_EXACT_STRATEGY_CACHE: dict[int, object] = {}


def make_exact_strategy(index: InvestigationKeyIndex):
    cached = _EXACT_STRATEGY_CACHE.get(id(index))
    if cached is not None:
        return cached
    member_map: dict[str, list[InvestigationKeyEntry]] = {}
    for entry in index.entries:
        for member in _entry_members(entry):
            member_map.setdefault(member, []).append(entry)

    def strategy(query: str, entries: Sequence[InvestigationKeyEntry], limit: int):
        del entries
        needles = exact_needles(query)
        if not needles:
            return []
        full = normalize_needle(query)
        ranked: list[tuple[InvestigationKeyEntry, float]] = []
        seen: set[str] = set()
        for needle in needles:
            for entry in member_map.get(needle, ()):
                if entry.key in seen:
                    continue
                seen.add(entry.key)
                score = EXACT_FULL_SCORE if needle == full else EXACT_TOKEN_SCORE
                ranked.append((entry, score))
        ranked.sort(key=lambda item: (-item[1], item[0].key))
        return ranked[: max(1, int(limit))]

    _EXACT_STRATEGY_CACHE[id(index)] = strategy
    return strategy


def hit_strength(
    score: float | None,
    matched_channels: Sequence[str] | None = None,
) -> str:
    if score is not None and float(score) >= STRONG_HIT_FLOOR:
        return "exact"
    channels = tuple(matched_channels or ())
    if "embedding" in channels and (score is None or float(score) > REWRITE_SCORE):
        return "embedding"
    return "rewrite"


def _channel_status(spec: CollectionSpec | None, name: str) -> str:
    if spec is None:
        return ""
    for channel in spec.channels:
        if channel.name == name:
            return channel.status
    return ""


def search_catalog(
    registry: InvestigationKeyIndexRegistry,
    query: str,
    *,
    index_keys: Sequence[str] | None = None,
    limit: int = 8,
    embedding_provider: Any = None,
) -> tuple[list[KeyIndexSearchHit], tuple[str, ...]]:
    """Search registered indexes. Default is all indexes; no query-shape index routing.

    Embedding is an additional channel on CollectionSpecs that declare it
    active, and only when a provider is supplied. It does not select indexes.
    """
    catalog = registry.catalog()
    keys = tuple(index_keys) if index_keys is not None else tuple(
        item["index_key"] for item in catalog
    )
    bounded = max(1, min(int(limit), 32))
    merged: dict[tuple[str, str], KeyIndexSearchHit] = {}

    def absorb(hit: KeyIndexSearchHit, channels: Sequence[str]) -> None:
        marker = (hit.index_key, hit.key)
        incoming = tuple(dict.fromkeys(str(item) for item in channels if str(item)))
        current = merged.get(marker)
        if current is None:
            merged[marker] = replace(hit, matched_channels=incoming)
            return
        combined = tuple(dict.fromkeys((*current.matched_channels, *incoming)))
        if float(hit.score or 0) > float(current.score or 0):
            merged[marker] = replace(hit, matched_channels=combined)
        else:
            merged[marker] = replace(current, matched_channels=combined)

    for index_key in keys:
        hits, _receipt = registry.search(index_key, query, limit=bounded)
        for hit in hits:
            absorb(hit, ("exact",))
    for variant in rewrite_query(query):
        for index_key in keys:
            hits, _receipt = registry.search(index_key, variant, limit=bounded)
            for hit in hits:
                absorb(replace(hit, score=REWRITE_SCORE), ("rewrite",))
    if embedding_provider is not None:
        for index_key in keys:
            spec = COLLECTION_SPEC_BY_INDEX_KEY.get(index_key)
            if _channel_status(spec, "embedding") != "active" or spec is None or spec.embedding is None:
                continue
            try:
                index = registry.index(index_key)
                ranked = search_embedding_channel(
                    index,
                    query,
                    provider=embedding_provider,
                    min_cosine=spec.embedding.min_cosine,
                    limit=bounded,
                )
            except Exception:
                continue
            known = {entry.key: entry for entry in index.entries}
            for entry, similarity in ranked:
                canonical = known.get(entry.key)
                if canonical is None:
                    continue
                absorb(
                    KeyIndexSearchHit(
                        index_key=index_key,
                        key=canonical.key,
                        name=canonical.name,
                        target_ref=canonical.target_ref,
                        score=float(similarity) * float(spec.embedding.score_scale),
                    ),
                    ("embedding",),
                )
    ranked = sorted(
        merged.values(),
        key=lambda item: (-float(item.score or 0), item.index_key, item.key),
    )
    return ranked[:bounded], keys


def _read_yaml(path: str) -> Any:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"catalog source not found: {path}")
    return yaml.safe_load(source.read_text(encoding="utf-8")) or {}


def _source_fingerprint(path: str) -> tuple[str, int, int]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"catalog source not found: {path}")
    stat = source.stat()
    return str(source.resolve()), stat.st_mtime_ns, stat.st_size


def _register_field(
    registry: InvestigationKeyIndexRegistry,
    spec: ProjectSpec,
    provider: ClientSearchFieldDefinitionProvider,
) -> None:
    from impl.projects.client_search.field_tools import (
        field_index_components,
    )

    index, resolve, validate = field_index_components(spec, provider)
    registry.register(
        index,
        resolver=resolve,
        search_strategy=make_exact_strategy(index),
        target_validator=validate,
    )


def _build_rule_index(spec: ProjectSpec) -> tuple[InvestigationKeyIndex, dict[str, dict[str, Any]]]:
    path = spec.source_path("enhanced_rules")
    if not path:
        raise ValueError(f"enhanced_rules not configured for project {spec.project_id}")
    return _cached_rule_index(*_source_fingerprint(path))


@lru_cache(maxsize=8)
def _cached_rule_index(path: str, modified_ns: int, size: int) -> tuple[InvestigationKeyIndex, dict[str, dict[str, Any]]]:
    del modified_ns, size
    payload = _read_yaml(path)
    entries: list[InvestigationKeyEntry] = []
    objects: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for offset, raw in enumerate(payload.get("rules") or []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        field = str(raw.get("field") or "").strip()
        key = name
        if key in seen:
            key = f"{name}::{field}::{offset}"
        seen.add(key)
        compact = {
            item: raw[item]
            for item in (
                "name",
                "patterns",
                "field",
                "operator",
                "match_mode",
                "value_type",
                "value",
                "priority",
                "query_logic",
                "merge_to_llm",
                "extra_conditions",
                "is_supported",
            )
            if item in raw
        }
        objects[key] = compact
        entries.append(
            InvestigationKeyEntry(
                key=key,
                name=name,
                search_text=name,
                target_ref=f"client-search-rule://{quote(key, safe='')}",
            )
        )
    index = InvestigationKeyIndex(
        index_key=RULES_INDEX_KEY,
        collection_ref="business-enhanced-rules",
        target_kind="evidence_locator",
        entry_granularity="yaml_rule",
        entries=tuple(entries),
    )
    return index, objects


def _register_rules(registry: InvestigationKeyIndexRegistry, spec: ProjectSpec) -> None:
    index, objects = _build_rule_index(spec)
    path = spec.source_path("enhanced_rules")

    def validate(target_ref: str) -> None:
        prefix = "client-search-rule://"
        if not target_ref.startswith(prefix):
            raise ValueError(f"invalid enhanced_rules target_ref: {target_ref}")

    def resolve(target_ref: str) -> dict[str, Any]:
        validate(target_ref)
        from urllib.parse import unquote

        key = unquote(target_ref.split("://", 1)[1])
        raw = objects.get(key)
        if raw is None:
            raise KeyError(f"enhanced rule not found: {key}")
        return {
            "content": dict(raw),
            "locator": f"enhanced_rules_args.yaml#key={key}",
            "provenance": {
                "project_id": spec.project_id,
                "source_path": path,
            },
        }

    registry.register(
        index,
        resolver=resolve,
        search_strategy=make_exact_strategy(index),
        target_validator=validate,
    )


def _build_mapping_index(spec: ProjectSpec) -> tuple[InvestigationKeyIndex, dict[str, dict[str, Any]]]:
    path = spec.source_path("value_mappings")
    if not path:
        raise ValueError(f"value_mappings not configured for project {spec.project_id}")
    return _cached_mapping_index(*_source_fingerprint(path))


@lru_cache(maxsize=8)
def _cached_mapping_index(path: str, modified_ns: int, size: int) -> tuple[InvestigationKeyIndex, dict[str, dict[str, Any]]]:
    del modified_ns, size
    payload = _read_yaml(path)
    entries: list[InvestigationKeyEntry] = []
    objects: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for field, mapping in (payload or {}).items():
        if not isinstance(mapping, dict):
            continue
        field_id = str(field).strip()
        if not field_id:
            continue
        for spoken, normalized in mapping.items():
            spoken_key = str(spoken).strip()
            if not spoken_key:
                continue
            key = f"{field_id}::{spoken_key}"
            if key in seen:
                continue
            seen.add(key)
            objects[key] = {
                "field": field_id,
                "spoken": spoken_key,
                "normalized": normalized,
            }
            entries.append(
                InvestigationKeyEntry(
                    key=key,
                    name=spoken_key,
                    search_text=spoken_key,
                    target_ref=f"client-search-mapping://{quote(key, safe='')}",
                )
            )
    index = InvestigationKeyIndex(
        index_key=MAPPINGS_INDEX_KEY,
        collection_ref="business-value-mappings",
        target_kind="evidence_locator",
        entry_granularity="yaml_spoken_key",
        entries=tuple(entries),
    )
    return index, objects


def _register_mappings(registry: InvestigationKeyIndexRegistry, spec: ProjectSpec) -> None:
    index, objects = _build_mapping_index(spec)
    path = spec.source_path("value_mappings")

    def validate(target_ref: str) -> None:
        if not target_ref.startswith("client-search-mapping://"):
            raise ValueError(f"invalid value_mappings target_ref: {target_ref}")

    def resolve(target_ref: str) -> dict[str, Any]:
        validate(target_ref)
        from urllib.parse import unquote

        key = unquote(target_ref.split("://", 1)[1])
        raw = objects.get(key)
        if raw is None:
            raise KeyError(f"value mapping not found: {key}")
        return {
            "content": dict(raw),
            "locator": f"value_mappings_args.yaml#key={key}",
            "provenance": {
                "project_id": spec.project_id,
                "source_path": path,
            },
        }

    registry.register(
        index,
        resolver=resolve,
        search_strategy=make_exact_strategy(index),
        target_validator=validate,
    )


def _build_abbr_index(spec: ProjectSpec) -> tuple[InvestigationKeyIndex, dict[str, str]]:
    path = spec.source_path("abbrname_enums")
    if not path:
        raise ValueError(f"abbrname_enums not configured for project {spec.project_id}")
    return _cached_abbr_index(*_source_fingerprint(path))


@lru_cache(maxsize=8)
def _cached_abbr_index(path: str, modified_ns: int, size: int) -> tuple[InvestigationKeyIndex, dict[str, str]]:
    del modified_ns, size
    payload = _read_yaml(path)
    node = payload.get("polNoInfo.plancodeinfo.abbrname") if isinstance(payload, dict) else None
    values: Iterable[Any]
    if isinstance(node, dict):
        values = node.get("values") or node.get("enums") or []
    elif isinstance(payload, list):
        values = payload
    else:
        values = []
    entries: list[InvestigationKeyEntry] = []
    objects: dict[str, str] = {}
    for raw in values:
        member = str(raw).strip()
        if not member or member in objects:
            continue
        objects[member] = member
        entries.append(
            InvestigationKeyEntry(
                key=member,
                name=member,
                search_text=member,
                target_ref=f"client-search-abbrname://{quote(member, safe='')}",
            )
        )
    index = InvestigationKeyIndex(
        index_key=ABBR_INDEX_KEY,
        collection_ref="business-abbrname-enums",
        target_kind="evidence_locator",
        entry_granularity="yaml_enum_member",
        entries=tuple(entries),
    )
    return index, objects


def _register_abbr(registry: InvestigationKeyIndexRegistry, spec: ProjectSpec) -> None:
    index, objects = _build_abbr_index(spec)
    path = spec.source_path("abbrname_enums")

    def validate(target_ref: str) -> None:
        if not target_ref.startswith("client-search-abbrname://"):
            raise ValueError(f"invalid abbrname target_ref: {target_ref}")

    def resolve(target_ref: str) -> dict[str, Any]:
        validate(target_ref)
        from urllib.parse import unquote

        key = unquote(target_ref.split("://", 1)[1])
        member = objects.get(key)
        if member is None:
            raise KeyError(f"abbrname member not found: {key}")
        return {
            "content": {
                "value": member,
                "field": "polNoInfo.plancodeinfo.abbrname",
                "membership": "exact",
            },
            "locator": f"abbrname_enums_args.yaml#value={member}",
            "provenance": {
                "project_id": spec.project_id,
                "source_path": path,
            },
        }

    registry.register(
        index,
        resolver=resolve,
        search_strategy=make_exact_strategy(index),
        target_validator=validate,
    )


def build_draft_catalog_registry(
    spec: ProjectSpec,
    provider: ClientSearchFieldDefinitionProvider | None = None,
) -> InvestigationKeyIndexRegistry:
    """Register every Draft Catalog collection. Control flow is spec-driven."""
    active_provider = provider or ClientSearchFieldDefinitionProvider(spec)
    registry = InvestigationKeyIndexRegistry()
    _register_field(registry, spec, active_provider)
    _register_rules(registry, spec)
    _register_mappings(registry, spec)
    _register_abbr(registry, spec)
    return registry


def create_catalog_tools(
    registry: InvestigationKeyIndexRegistry,
    *,
    embedding_provider: Any = None,
) -> tuple[VerifiableTool, VerifiableTool]:
    catalog = registry.catalog()
    index_keys = [item["index_key"] for item in catalog]
    catalog_lines = [
        (
            f"{item['index_key']} [collection_ref={item['collection_ref']}; "
            f"target_kind={item['target_kind']}; "
            f"entry_granularity={item['entry_granularity']}]"
        )
        for item in catalog
    ]
    catalog_description = (
        "Default searches all registered indexes (no query-shape index routing). "
        "Embedding is an additional channel on text collections when infra is "
        "available; it does not choose indexes by query shape. "
        "One Search: omit index_key to search all indexes; do not fan-out one Search per index. After an exact/strong hit, Load 1–2 keys; do not Load competing family fields after an exact clientAge / 本人规则 hit. SearchHit is not Evidence; load_entry loads one real object. Declared operator lists after Load describe support; they do not make a live exclusive-below operator (`LT n` for 「n周岁以下」) illegal. Parser generation recipes (enhanced_rules operator/pattern) are not Evidence that live LT is wrong. Rewrite and embedding hits are locators only; they are not synonym proofs; do not change fulfillment from SearchHit without Load. "
        "Available indexes: " + "; ".join(catalog_lines)
    )
    index_key_parameter: dict[str, Any] = {
        "type": "string",
        "description": (
            "Optional. Omit to search every registered index. "
            + catalog_description
        ),
    }
    if index_keys:
        index_key_parameter["enum"] = index_keys

    def search_index(**kwargs: Any) -> ToolResult:
        try:
            requested = str(kwargs.get("index_key") or "").strip()
            selected = [requested] if requested else None
            hits, searched = search_catalog(
                registry,
                str(kwargs.get("query") or ""),
                index_keys=selected,
                limit=int(kwargs.get("limit") or 8),
                embedding_provider=embedding_provider,
            )
            candidates = []
            for hit in hits:
                payload = hit.as_dict()
                payload["strength"] = hit_strength(hit.score, hit.matched_channels)
                if hit.matched_channels:
                    payload["matched_channels"] = list(hit.matched_channels)
                candidates.append(payload)
            return ToolResult(
                tool_id="investigation.search_index",
                tool_type="investigation_key_index_search",
                status="succeeded",
                actual={
                    "candidates": candidates,
                    "searched_index_keys": list(searched),
                    "search_hit_is_not_evidence": True,
                },
                evidence="searched Draft Catalog indexes; hits are locators not evidence",
            )
        except Exception as exc:
            return ToolResult(
                tool_id="investigation.search_index",
                tool_type="investigation_key_index_search",
                status="failed",
                error=str(exc),
            )

    def load_entry(**kwargs: Any) -> ToolResult:
        try:
            actual, receipt = registry.load(
                str(kwargs.get("index_key") or ""),
                str(kwargs.get("key") or ""),
            )
            return ToolResult(
                tool_id="investigation.load_entry",
                tool_type="investigation_key_index_load",
                status="succeeded",
                actual=actual,
                evidence="loaded one Catalog target; not a full-collection dump",
                runtime_metadata={"receipt": receipt.as_dict()},
            )
        except Exception as exc:
            return ToolResult(
                tool_id="investigation.load_entry",
                tool_type="investigation_key_index_load",
                status="failed",
                error=str(exc),
            )

    return (
        VerifiableTool(
            tool_id="investigation.search_index",
            description=(
                "Search Draft Catalog indexes for limited candidates. "
                + catalog_description
            ),
            applicable_scenario="find candidate targets without loading the full collection",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Navigation query."},
                    "index_key": dict(index_key_parameter),
                    "limit": {"type": "integer", "description": "Maximum candidate count."},
                },
                "required": ["query"],
            },
            execute_fn=search_index,
        ),
        VerifiableTool(
            tool_id="investigation.load_entry",
            description=(
                "Load one indexed target object. SearchHit is not Evidence. Declared operator lists after Load describe support; they do not make a live exclusive-below operator (`LT n` for 「n周岁以下」) illegal. Parser generation recipes (enhanced_rules operator/pattern) are not Evidence that live LT is wrong. Rewrite and embedding hits are locators only; they are not synonym proofs; do not change fulfillment from SearchHit without Load. "
                "Requires an explicit non-wildcard key from search candidates."
            ),
            applicable_scenario="inspect one candidate target after search",
            parameters={
                "type": "object",
                "properties": {
                    "index_key": dict(index_key_parameter),
                    "key": {"type": "string", "description": "One explicit entry key."},
                },
                "required": ["index_key", "key"],
            },
            execute_fn=load_entry,
        ),
    )
