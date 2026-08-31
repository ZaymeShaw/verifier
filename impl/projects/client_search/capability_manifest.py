from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml as _yaml


def _load_enum_registry(
    enums_path: str | Path | list[str | Path] | None,
) -> dict[str, list[str]]:
    """Load enum YAML files and return a merged mapping of enum_key -> values list.

    Accepts a single path (backward compatible) or a list of paths; later files
    merge over earlier ones (later values win for the same key).
    """
    paths = _enum_paths(enums_path)
    registry: dict[str, list[str]] = {}
    for path in paths:
        registry.update(_load_enum_file(path))
    return registry


def _enum_paths(
    enums_path: str | Path | list[str | Path] | None,
) -> list[Path]:
    if not enums_path:
        return []
    if isinstance(enums_path, (str, Path)):
        return [Path(enums_path)]
    return [Path(item) for item in enums_path]


def _load_enum_file(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"client_search enum registry not found: {path}")
    try:
        data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ValueError(f"client_search enum registry is invalid YAML: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"client_search enum registry must be an object: {path}")
    registry: dict[str, list[str]] = {}
    for key, entry in data.items():
        if isinstance(entry, dict):
            values = entry.get("values")
            if isinstance(values, list):
                registry[str(key)] = [str(v) for v in values]
        elif isinstance(entry, list):
            # Tolerate flat list format: key: [v1, v2, ...]
            registry[str(key)] = [str(v) for v in entry]
    return registry


def build_capability_manifest(
    definitions_path: str | Path | None,
    enums_path: str | Path | list[str | Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate the client_search field capability manifest from source YAML.

    Args:
        definitions_path: Path to field_definitions YAML.
        enums_path: Optional path to field_enums YAML. When provided,
            ``enum_ref`` entries in field definitions are resolved to their
            actual enum value lists from this file.

    Returns:
        Mapping of field_name -> capability dict. Backward-compatible:
        when *enums_path* is omitted the behaviour is identical to before.
    """
    if not definitions_path:
        return {}
    path = Path(definitions_path)
    if not path.exists():
        return {}

    enum_registry = _load_enum_registry(enums_path)

    data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    intents = data.get("intents", []) if isinstance(data, dict) else []
    fields: dict[str, dict[str, Any]] = {}
    for item in intents:
        if not isinstance(item, dict):
            continue
        field_name = item.get("field", "")
        if not field_name:
            continue
        if field_name not in fields:
            # Resolve enums: inline "enum" list takes base; enum_ref augments.
            inline_enums = item.get("enum") or []
            enum_ref = item.get("enum_ref") or ""
            ref_enums = enum_registry.get(enum_ref, []) if enum_ref else []
            # Merge: inline first, then ref values not already present.
            merged_enums = list(inline_enums)
            seen = set(str(v) for v in merged_enums)
            for v in ref_enums:
                if v not in seen:
                    merged_enums.append(v)
                    seen.add(v)

            fields[field_name] = {
                "field": field_name,
                "operators": set(),
                "value_types": set(),
                "description": item.get("description", ""),
                "definition": item.get("description", ""),
                "enums": merged_enums,
                "enum_ref": enum_ref,
                "enum_refs": [enum_ref] if enum_ref else [],
                "unresolved_enum_refs": (
                    [enum_ref] if enum_ref and enum_ref not in enum_registry else []
                ),
                "show_enum_in_prompt": (
                    False if item.get("show_enum_in_prompt") is False else True
                ),
                "enum_candidate_limit_in_prompt": (
                    int(item["enum_candidate_limit_in_prompt"])
                    if item.get("enum_candidate_limit_in_prompt") is not None
                    else None
                ),
                "unit": item.get("unit") or "",
                "notes": item.get("notes", ""),
                # Source truth: explicitly unsupported fields must remain visible so
                # Judge can distinguish "recognizable but not searchable" from
                # out-of-manifest/unknown capability.
                "is_supported": item.get("is_supported") is not False,
                "is_supported_explicit": "is_supported" in item,
            }
        else:
            inline_enums = item.get("enum") or []
            enum_ref = str(item.get("enum_ref") or "")
            ref_enums = enum_registry.get(enum_ref, []) if enum_ref else []
            if enum_ref and enum_ref not in fields[field_name]["enum_refs"]:
                fields[field_name]["enum_refs"].append(enum_ref)
            if (
                enum_ref
                and enum_ref not in enum_registry
                and enum_ref not in fields[field_name]["unresolved_enum_refs"]
            ):
                fields[field_name]["unresolved_enum_refs"].append(enum_ref)
            known = {str(value) for value in fields[field_name]["enums"]}
            for value in [*inline_enums, *ref_enums]:
                normalized = str(value)
                if normalized not in known:
                    fields[field_name]["enums"].append(value)
                    known.add(normalized)
        if item.get("is_supported") is False:
            # A field is searchable only when every source declaration permits it.
            fields[field_name]["is_supported"] = False
            fields[field_name]["is_supported_explicit"] = True
        elif "is_supported" in item:
            fields[field_name]["is_supported_explicit"] = True
        if item.get("show_enum_in_prompt") is False:
            fields[field_name]["show_enum_in_prompt"] = False
        if item.get("enum_candidate_limit_in_prompt") is not None:
            candidate_limit = int(item["enum_candidate_limit_in_prompt"])
            current_limit = fields[field_name]["enum_candidate_limit_in_prompt"]
            fields[field_name]["enum_candidate_limit_in_prompt"] = (
                candidate_limit
                if current_limit is None
                else max(current_limit, candidate_limit)
            )
        fields[field_name]["operators"].add(item.get("operator", ""))
        fields[field_name]["value_types"].add(item.get("value_type", ""))

    for field in fields.values():
        field["operators"] = sorted(field["operators"])
        field["value_types"] = sorted(field["value_types"])
    return fields


def build_behavior_manifest(
    behavior_intents_path: str | Path | None,
) -> dict[str, dict[str, Any]]:
    """从 behavior_intent_definitions_args.yaml 只吸收空间部分。

    只把 field / operator / is_supported / activity 枚举值空间作为 capability
    manifest 条目；aliases / activity_template / selection_notes / examples /
    confusing_intents 属 current_behavior（parser 选择规则），不进入治理字段目录。
    """
    if not behavior_intents_path:
        return {}
    path = Path(behavior_intents_path)
    if not path.is_file():
        return {}
    data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    field = str(data.get("field") or "customer_activity").strip()
    if not field:
        return {}
    intents = data.get("intents") if isinstance(data, dict) else None
    if not isinstance(intents, list):
        return {}

    supported_enums: list[str] = []
    unsupported_enums: list[str] = []
    for item in intents:
        if not isinstance(item, dict):
            continue
        activity = str(item.get("activity") or "").strip()
        if not activity:
            continue
        if item.get("is_supported") is False:
            unsupported_enums.append(activity)
        else:
            supported_enums.append(activity)
    supported_enums = list(dict.fromkeys(supported_enums))
    unsupported_enums = list(dict.fromkeys(unsupported_enums))

    equivalent_groups: list[list[str]] = []
    raw_groups = data.get("equivalent_activity_groups")
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if isinstance(group, list):
                cleaned = [str(item) for item in group if str(item).strip()]
                if cleaned:
                    equivalent_groups.append(cleaned)

    is_supported = bool(supported_enums)
    entry: dict[str, Any] = {
        "field": field,
        "operators": ["MATCH"],
        "value_types": ["enum"],
        "description": (
            "客户行为字段。空间部分来自 behavior_intent_definitions_args.yaml；"
            "aliases/activity_template/selection_notes/examples 属 current_behavior，不作为裁决依据。"
        ),
        "definition": (
            "客户行为字段。空间部分来自 behavior_intent_definitions_args.yaml；"
            "aliases/activity_template/selection_notes/examples 属 current_behavior，不作为裁决依据。"
        ),
        "enums": supported_enums,
        "enum_ref": "",
        "enum_refs": [],
        "unresolved_enum_refs": [],
        "show_enum_in_prompt": True,
        "enum_candidate_limit_in_prompt": None,
        "unit": "",
        "notes": (
            "只吸收 behavior_intent_definitions_args.yaml 的空间陈述；"
            "具体行为选择规则仍以 current_behavior 处理。"
        ),
        "is_supported": is_supported,
        "is_supported_explicit": True,
        "enum_total_count": len(supported_enums),
        "equivalent_activity_groups": equivalent_groups,
        "unsupported_enums": unsupported_enums,
    }
    return {field: entry}


def lean_capability_manifest(
    manifest: dict[str, dict[str, Any]],
    *,
    default_limit: int = 5,
    threshold: int = 50,
) -> dict[str, dict[str, Any]]:
    """Prompt-safe lean manifest: keep field metadata, truncate huge enum lists.

    全量枚举保留在 authority EvidenceSpace / 文件直读通道；prompt 只注入少量
    候选（enum_candidate_limit_in_prompt 或 default_limit），并标记截断信息
    （enum_values_truncated / enum_total_count），避免把 planfullname/abbrname
    等整表（数千条）塞进 judge/attribute prompt。
    """
    if not isinstance(manifest, dict):
        return manifest
    lean: dict[str, dict[str, Any]] = {}
    for field, entry in manifest.items():
        if not isinstance(entry, dict):
            lean[field] = entry
            continue
        out = dict(entry)
        enums = list(entry.get("enums") or [])
        candidate_limit = entry.get("enum_candidate_limit_in_prompt")
        limit = int(candidate_limit) if candidate_limit else default_limit
        show_all = entry.get("show_enum_in_prompt") is not False
        if not show_all or len(enums) > threshold:
            out["enums"] = enums[:limit]
            out["enum_values_truncated"] = True
            out["enum_total_count"] = len(enums)
            out["show_enum_in_prompt"] = False
            out["enum_candidate_limit_in_prompt"] = limit
        lean[field] = out
    return lean
