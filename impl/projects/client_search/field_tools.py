"""client_search Draft-only field-key lookup.

Field Collection projection and Load of one field definition. Catalog search
lives in catalog.py; this module does not own query reject lexicons.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from impl.core.investigation_key_index import InvestigationKeyIndexRegistry
from impl.core.schema import InvestigationKeyEntry, InvestigationKeyIndex, ProjectSpec
from impl.tools import ToolResult, VerifiableTool

from impl.projects.client_search.field_provider import (
    ClientSearchFieldDefinitionProvider,
)


def _short_name(value: Any) -> str:
    short_name = (
        str(value or "").strip().split("，", 1)[0].split("。", 1)[0].strip()
    )
    for prefix in ("仅表示", "表示"):
        if short_name.startswith(prefix):
            short_name = short_name[len(prefix):].strip()
            break
    return short_name[:32]


@lru_cache(maxsize=8)
def _load_versioned_field_key_index(
    path: str,
    modified_ns: int,
    size: int,
) -> InvestigationKeyIndex:
    # modified_ns/size version the deterministic projection without copying
    # source content into the runtime prompt.
    del modified_ns, size
    source = Path(path)
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    entries: list[InvestigationKeyEntry] = []
    seen_fields: set[str] = set()
    for raw in payload.get("intents", []) or []:
        if not isinstance(raw, dict):
            continue
        field = str(raw.get("field") or "").strip()
        if not field or field in seen_fields:
            continue
        seen_fields.add(field)
        entries.append(InvestigationKeyEntry(
            key=field,
            name=_short_name(raw.get("description")) or field,
            search_text=" ".join(
                str(raw.get(key) or "")
                for key in ("field", "retrieval_text", "description")
            ),
            target_ref=f"client-search-field://{field}",
        ))
    return InvestigationKeyIndex(
        index_key="client-search.field-definitions",
        collection_ref="business-field-definitions",
        target_kind="evidence_locator",
        entry_granularity="yaml_field_definition",
        entries=tuple(entries),
    )


def load_explicit_field_support(spec: ProjectSpec, field: str) -> tuple[bool, bool]:
    """Return (supported, explicit) from every source entry for one field."""
    path = spec.source_path("field_definitions")
    if not path:
        return True, False
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    flags = [
        item.get("is_supported")
        for item in (payload.get("intents") or [])
        if isinstance(item, dict)
        and str(item.get("field") or "").strip() == field
        and "is_supported" in item
    ]
    if flags:
        return all(flag is not False for flag in flags), True

    # field_definitions 未声明该字段时，再看 behavior_intent_definitions 的空间声明。
    behavior_path = spec.source_path("behavior_intents")
    if not behavior_path:
        return True, False
    behavior_source = Path(behavior_path)
    if not behavior_source.is_file():
        return True, False
    behavior_payload = yaml.safe_load(behavior_source.read_text(encoding="utf-8")) or {}
    if not isinstance(behavior_payload, dict):
        return True, False
    if str(behavior_payload.get("field") or "").strip() != field:
        return True, False
    intents = behavior_payload.get("intents")
    if not isinstance(intents, list):
        return True, False
    behavior_flags = [
        item.get("is_supported")
        for item in intents
        if isinstance(item, dict)
        and "is_supported" in item
    ]
    if not behavior_flags:
        return True, False
    return all(flag is not False for flag in behavior_flags), True


def _load_field_key_index(spec: ProjectSpec) -> InvestigationKeyIndex:
    path = spec.source_path("field_definitions")
    if not path:
        raise ValueError(
            f"Field definitions not configured for project {spec.project_id}"
        )
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Field definitions file not found: {path}")
    stat = source.stat()
    index = _load_versioned_field_key_index(
        str(source.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
    )
    # 合并 behavior_intent_definitions 的字段级入口，使 catalog Search→Load 能命中 customer_activity。
    behavior_path = spec.source_path("behavior_intents")
    if behavior_path:
        behavior_source = Path(behavior_path)
        if behavior_source.is_file():
            behavior_payload = yaml.safe_load(behavior_source.read_text(encoding="utf-8")) or {}
            if isinstance(behavior_payload, dict):
                behavior_field = str(behavior_payload.get("field") or "").strip()
                if behavior_field:
                    entries = list(index.entries or [])
                    if behavior_field not in {entry.key for entry in entries}:
                        entries.append(InvestigationKeyEntry(
                            key=behavior_field,
                            name="客户行为",
                            search_text=" ".join([
                                behavior_field,
                                "客户行为",
                                str(behavior_payload.get("description") or ""),
                            ]),
                            target_ref=f"client-search-field://{behavior_field}",
                        ))
                    index = InvestigationKeyIndex(
                        index_key=index.index_key,
                        collection_ref=index.collection_ref,
                        target_kind=index.target_kind,
                        entry_granularity=index.entry_granularity,
                        entries=tuple(entries),
                    )
    return index


def field_index_components(
    spec: ProjectSpec,
    provider: ClientSearchFieldDefinitionProvider | None = None,
):
    """Return (index, resolver, validator) for the field Collection."""
    provider = provider or ClientSearchFieldDefinitionProvider(spec)
    index = _load_field_key_index(spec)
    known_fields = {entry.key for entry in index.entries}

    def validate_target(target_ref: str) -> None:
        prefix = "client-search-field://"
        if not target_ref.startswith(prefix) or target_ref[len(prefix):] not in known_fields:
            raise ValueError(f"invalid client_search field target_ref: {target_ref}")

    def resolve_target(target_ref: str) -> dict[str, Any]:
        validate_target(target_ref)
        field = target_ref.split("://", 1)[1]
        raw = provider.get_field_definition(field)
        if not raw:
            raise KeyError(f"field definition not found: {field}")
        raw = dict(raw)
        supported, explicit = load_explicit_field_support(spec, field)
        if explicit:
            raw["is_supported"] = supported
            raw["is_supported_explicit"] = True
        source_path = spec.source_path("field_definitions")
        locator = f"field_definitions_args.yaml#field={field}"
        behavior_path = spec.source_path("behavior_intents")
        if behavior_path and field == (raw.get("field") or ""):
            try:
                behavior_payload = yaml.safe_load(Path(behavior_path).read_text(encoding="utf-8")) or {}
            except Exception:
                behavior_payload = {}
            if isinstance(behavior_payload, dict) and behavior_payload.get("field") == field:
                source_path = behavior_path
                locator = f"behavior_intent_definitions_args.yaml#field={field}"
        return {
            "content": raw,
            "locator": locator,
            "provenance": {
                "project_id": spec.project_id,
                "source_path": source_path,
            },
        }

    return index, resolve_target, validate_target


def build_field_key_index_registry(
    spec: ProjectSpec,
    provider: ClientSearchFieldDefinitionProvider | None = None,
) -> InvestigationKeyIndexRegistry:
    from impl.projects.client_search.catalog import make_exact_strategy

    index, resolve_target, validate_target = field_index_components(spec, provider)
    registry = InvestigationKeyIndexRegistry()
    registry.register(
        index,
        resolver=resolve_target,
        search_strategy=make_exact_strategy(index),
        target_validator=validate_target,
    )
    return registry


def create_minimal_field_definition_tool(
    provider: ClientSearchFieldDefinitionProvider,
    registry: InvestigationKeyIndexRegistry | None = None,
) -> VerifiableTool:
    def lookup_definition(**kwargs: Any) -> ToolResult:
        field = str(kwargs.get("field") or "").strip()
        try:
            if registry is not None:
                loaded, receipt = registry.load("client-search.field-definitions", field)
                raw = loaded["content"]
            else:
                receipt = None
                raw = provider.get_field_definition(field)
                if raw:
                    raw = dict(raw)
                    supported, explicit = load_explicit_field_support(provider.spec, field)
                    if explicit:
                        raw["is_supported"] = supported
                        raw["is_supported_explicit"] = True
            if not raw:
                return ToolResult(
                    tool_id="field.search_definition",
                    tool_type="client_search_field_definition",
                    status="inconclusive",
                    actual={"field": field, "found": False},
                    evidence=f"field '{field}' not found",
                )
            definition = {
                "field": str(raw.get("field") or field),
                "operators": list(raw.get("operators") or []),
                "value_types": list(raw.get("value_types") or []),
                "is_supported": raw.get("is_supported") is not False,
            }
            description = _short_name(raw.get("description"))
            if description:
                definition["short_name"] = description
            enums = list(raw.get("enums") or [])
            if enums:
                definition["enums"] = enums[:5]
            if raw.get("unit"):
                definition["unit"] = raw["unit"]
            return ToolResult(
                tool_id="field.search_definition",
                tool_type="client_search_field_definition",
                status="succeeded",
                actual=definition,
                evidence=f"retrieved minimal definition for {field}",
                runtime_metadata=(
                    {"receipt": receipt.as_dict()} if receipt is not None else {}
                ),
            )
        except Exception as exc:
            return ToolResult(
                tool_id="field.search_definition",
                tool_type="client_search_field_definition",
                status="failed",
                error=f"Error retrieving field definition: {exc}",
            )

    lookup_definition.__name__ = "field_search_definition"
    return VerifiableTool(
        tool_id="field.search_definition",
        description=(
            "按字段 key 读取一个字段是否支持搜索、短名称、操作符、值类型及少量枚举。"
            "operators 列表只描述该字段支持哪些操作符，并不使 live 排他 `LT n` 非法。"
        ),
        applicable_scenario="client_search-judge",
        parameters={
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": "从字段索引获得的精确 key。",
                },
            },
            "required": ["field"],
        },
        execute_fn=lookup_definition,
    )
