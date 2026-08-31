"""Structured capability form: field × operator × value readings.

This is one Axis-2 form. The protocol contract lives in capability_carrier.py.
Chinese description parsing (表示/如/例如/不表示) is a convention of this form's
material, not of the protocol. Project domain aliases belong on the material.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .capability_carrier import (
    CARRY_NO,
    CARRY_UNDECIDABLE,
    CARRY_YES,
    DEFAULT_TRUST_TIER,
    CarrierError,
    CarrierVerdict,
    CapabilityCarrierBase,
    GAP_AMBIGUITY,
    GAP_TOOL,
    GAP_UNGOVERNED,
    RECOG_MISSING_OPERATOR,
    RECOG_MISSING_VALUE,
    RECOG_UNMAPPED,
    RECOG_UNSUPPORTED,
    assertion_tier,
    require_stamped_claims,
    snapshot_id,
    stamp_claims,
)

PROCESS_FIELD = "*"

_STOP_ALIASES = {
    "客户", "表示", "字段", "条件", "搜索", "查询", "筛选", "目标",
    "群体", "名单", "系统", "当前", "本人", "业务", "动作", "月份",
    "日期", "时间", "年度", "名称", "记录",
}
_HEAD_NOUN = re.compile(r"([一-龥]{2,4})(?:业务|月份|动作|条件|字段|号码|名称)")
_EXAMPLE_LIST = re.compile(r"(?:如|例如)([^。；;]+)")
_POSITIVE_DENOTE = re.compile(r"(?<!不)(?:仅)?表示([^；。，,]+)")

_ENUM_PROMPT_LIMIT = 12
_DEFAULT_MAPPER_RETRIES = 3
_DEFAULT_RETRY_BACKOFF = (0.5, 1.5, 3.0)
_CJK = re.compile(r"[\u4e00-\u9fff]")
_ALIAS_JUNK = re.compile(r"字段|操作符|枚举|支持")
_TOKEN_SPLIT = re.compile(r"[、，,；;/\s与或和及“”\"'()（）]+")

MapperFn = Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]


class MapperExhausted(Exception):
    """Mapper retries exhausted or every attempt produced an unusable payload."""


@dataclass
class _MapperReading:
    field: str = ""
    value: Optional[Any] = None
    operator: Optional[Any] = None
    match_mode: Optional[str] = None


@dataclass
class _MapperAlternative:
    readings: list[_MapperReading] = field(default_factory=list)


@dataclass
class _MapperNearest:
    field: str = ""
    why: str = ""


@dataclass
class _MapperUnmapped:
    surface: str = ""
    nearest: list[_MapperNearest] = field(default_factory=list)


@dataclass
class _MapperOutput:
    process_only: bool = False
    alternatives: list[_MapperAlternative] = field(default_factory=list)
    unmapped: list[_MapperUnmapped] = field(default_factory=list)


@dataclass(frozen=True)
class CatalogHit:
    field: str
    kind: str
    evidence: str
    value: str = ""


@dataclass(frozen=True)
class CarrierReading:
    field: str
    value: str = ""
    operator: str = ""
    kind: str = "dimension"
    match_mode: str = ""


def _field_entry(snapshot: Mapping[str, Any], field: str) -> Mapping[str, Any] | None:
    fields = snapshot.get("fields")
    if not isinstance(fields, Mapping):
        return None
    entry = fields.get(field)
    return entry if isinstance(entry, Mapping) else None


def _catalog_fields(snapshot: Mapping[str, Any]) -> set[str]:
    fields = snapshot.get("fields")
    if not isinstance(fields, Mapping):
        return set()
    return {str(name) for name in fields if str(name).strip()}


def _catalog_tier(snapshot: Mapping[str, Any]) -> str:
    return str(snapshot.get("trust_tier") or "").strip() or DEFAULT_TRUST_TIER


def _citation(entry: Mapping[str, Any], field: str, snapshot: Mapping[str, Any], note: str = "") -> dict[str, str]:
    # source 即担保 w 的材料引用（judge.md §3），保链不删；tier 随断言戳记透传。
    payload = {
        "source": str(entry.get("source") or "capability_manifest"),
        "ref": field,
        "revision": str(snapshot.get("revision") or snapshot_id(snapshot)[:16]),
        "tier": assertion_tier(entry),
    }
    if note:
        payload["note"] = note
    return payload


def evaluate_reading(
    reading: CarrierReading,
    snapshot: Mapping[str, Any],
) -> CarrierVerdict:
    if snapshot.get("fields") is None:
        return CarrierVerdict(
            CARRY_UNDECIDABLE,
            "capability snapshot unavailable",
            gap_kind=GAP_TOOL,
            missing_material="本次能力空间快照",
        )
    if reading.kind == "process":
        return CarrierVerdict(
            CARRY_YES,
            "过程约束空间可遵守",
            citations=(
                {
                    "source": "capability_manifest",
                    "ref": "fields",
                    "revision": str(snapshot.get("revision") or snapshot_id(snapshot)[:16]),
                    "tier": _catalog_tier(snapshot),
                    "note": "过程约束不要求新增维度",
                },
            ),
        )
    field = str(reading.field or "").strip()
    if not field:
        return CarrierVerdict(
            CARRY_UNDECIDABLE,
            "reading missing field",
            gap_kind=GAP_TOOL,
            missing_material="读法字段必须属于受治理维度目录",
        )
    entry = _field_entry(snapshot, field)
    if entry is None:
        return CarrierVerdict(
            CARRY_UNDECIDABLE,
            f"读法字段 {field} 不在目录内",
            gap_kind=GAP_TOOL,
            missing_material="读法字段必须属于受治理维度目录",
        )
    if entry.get("governed") is False:
        return CarrierVerdict(
            CARRY_UNDECIDABLE,
            f"{field} 未受治理",
            gap_kind=GAP_UNGOVERNED,
            missing_material=f"M1 登记：{field}",
        )
    citation = _citation(entry, field, snapshot)
    if entry.get("is_supported") is False:
        return CarrierVerdict(
            CARRY_NO,
            f"{field} is_supported=false",
            citations=(citation,),
            recognition=RECOG_UNSUPPORTED,
        )
    operators = {str(item).strip() for item in (entry.get("operators") or []) if str(item).strip()}
    operator = str(reading.operator or "").strip()
    if operator and operators and operator not in operators:
        return CarrierVerdict(
            CARRY_NO,
            f"{field} 缺操作符 {operator}",
            citations=(citation,),
            recognition=RECOG_MISSING_OPERATOR,
        )
    enums = [str(item) for item in (entry.get("enums") or [])]
    value = str(reading.value or "").strip()
    if value and enums:
        # 列表值在归一时以 "~" 连接（如 CONTAINS ["潜客","意向"]），
        # 枚举承载性按元素逐个裁，不拿连接串整体查。
        parts = [part for part in value.split("~") if part] or [value]
        missing = [part for part in parts if part not in enums]
        if missing:
            return CarrierVerdict(
                CARRY_NO,
                f"{field} 缺值 {'、'.join(missing)}",
                citations=(citation,),
                recognition=RECOG_MISSING_VALUE,
            )
    return CarrierVerdict(CARRY_YES, f"{field} 可完整表达", citations=(citation,))


def resolve_carrier(
    alternatives: Sequence[Sequence[CarrierReading]],
    snapshot: Mapping[str, Any],
) -> CarrierVerdict:
    """Each alternative is one complete reading of the expectation.

    All alternatives yes → yes; all no → no; mixed → 口径分歧.
    An alternative is yes only when every reading in it is yes.
    """
    if not alternatives:
        return CarrierVerdict(
            CARRY_UNDECIDABLE,
            "no readings",
            gap_kind=GAP_UNGOVERNED,
            missing_material="期望的目标维度读法",
        )
    outcomes: list[CarrierVerdict] = []
    for group in alternatives:
        if not group:
            outcomes.append(
                CarrierVerdict(
                    CARRY_UNDECIDABLE,
                    "empty reading",
                    gap_kind=GAP_UNGOVERNED,
                    missing_material="期望的目标维度读法",
                )
            )
            continue
        parts = [evaluate_reading(item, snapshot) for item in group]
        if any(item.carry == CARRY_UNDECIDABLE for item in parts):
            outcomes.append(next(item for item in parts if item.carry == CARRY_UNDECIDABLE))
            continue
        if any(item.carry == CARRY_NO for item in parts):
            outcomes.append(next(item for item in parts if item.carry == CARRY_NO))
            continue
        citations = tuple(cite for item in parts for cite in item.citations)
        outcomes.append(CarrierVerdict(CARRY_YES, "完整表达存在", citations=citations))
    kinds = {item.carry for item in outcomes}
    if CARRY_UNDECIDABLE in kinds and kinds != {CARRY_UNDECIDABLE}:
        unclear = next(item for item in outcomes if item.carry == CARRY_UNDECIDABLE)
        return unclear
    if kinds == {CARRY_UNDECIDABLE}:
        return outcomes[0]
    if kinds == {CARRY_YES}:
        return outcomes[0]
    if kinds == {CARRY_NO}:
        return outcomes[0]
    return CarrierVerdict(
        CARRY_UNDECIDABLE,
        "不同读法承载性答案不一致",
        gap_kind=GAP_AMBIGUITY,
        missing_material="受治理口径",
        citations=tuple(cite for item in outcomes for cite in item.citations),
    )


def _expectation_text(expectation: Mapping[str, Any]) -> str:
    parts = [
        str(expectation.get(key) or "")
        for key in ("expectation_id", "user_intent", "expected_outcome")
    ]
    criteria = expectation.get("acceptance_criteria")
    if isinstance(criteria, (list, tuple)):
        parts.extend(str(item) for item in criteria)
    elif criteria:
        parts.append(str(criteria))
    return " ".join(part for part in parts if part)


def _spoken_aliases(spoken: Any) -> list[str]:
    if isinstance(spoken, Mapping):
        return [str(key).strip() for key in spoken if str(key).strip()]
    if isinstance(spoken, (list, tuple)):
        aliases: list[str] = []
        for item in spoken:
            if isinstance(item, Mapping):
                aliases.extend(
                    str(item.get(key) or "").strip()
                    for key in ("spoken", "alias", "key")
                    if str(item.get(key) or "").strip()
                )
            elif str(item).strip():
                aliases.append(str(item).strip())
        return aliases
    return []


def _add_phrase_aliases(aliases: set[str], phrase: str) -> None:
    phrase = str(phrase or "").strip()
    if not phrase:
        return
    aliases.add(phrase)
    for piece in re.split(r"[、/或]", phrase):
        piece = piece.strip()
        if 2 <= len(piece) <= 16:
            aliases.add(piece)
        tail = re.sub(r"^(?:保单|客户)?(?:本人)?的?", "", piece).strip()
        if 2 <= len(tail) <= 8:
            aliases.add(tail)
        for match in _HEAD_NOUN.finditer(piece):
            aliases.add(match.group(1))


def _aliases_for(name: str, entry: Mapping[str, Any]) -> set[str]:
    aliases = {name, name.split(".")[-1], name.lower()}
    desc = str(entry.get("description") or "")
    notes = str(entry.get("notes") or "")
    for raw in (desc, notes):
        head = re.split(r"[，,；;。]", raw, maxsplit=1)[0].strip()
        head = re.sub(r"^(?:仅)?表示", "", head).strip()
        if 2 <= len(head) <= 16:
            _add_phrase_aliases(aliases, head)
        for match in _POSITIVE_DENOTE.finditer(raw):
            phrase = match.group(1).strip()
            if phrase:
                _add_phrase_aliases(aliases, phrase)
        for match in _EXAMPLE_LIST.finditer(raw):
            for piece in re.split(r"[、，,和与或等]", match.group(1)):
                piece = piece.strip()
                if 2 <= len(piece) <= 12:
                    aliases.add(piece)
        for match in re.finditer(r"([一-龥]{2}(?:、[一-龥]{2,4}){1,8})等", raw):
            prefix = raw[max(0, match.start() - 8):match.start()]
            if "不" in prefix:
                continue
            for piece in match.group(1).split("、"):
                if 2 <= len(piece) <= 8:
                    aliases.add(piece)
    aliases.update(_spoken_aliases(entry.get("spoken")))
    aliases.update(str(item).strip() for item in (entry.get("aliases") or []) if str(item).strip())
    return {item for item in aliases if _usable_alias(item)}


def _usable_alias(item: str) -> bool:
    text = str(item or "").strip()
    if not text or text in _STOP_ALIASES:
        return False
    if text.isdigit():
        return False
    return True


def _negatives_for(entry: Mapping[str, Any]) -> set[str]:
    desc = str(entry.get("description") or "")
    negatives: set[str] = set()
    for match in re.finditer(r"不(?:表示|作为)([^。；]+)", desc):
        for piece in re.split(r"[、/，,或与和]", match.group(1)):
            piece = piece.strip()
            if 2 <= len(piece) <= 24:
                negatives.add(piece)
    negatives.update(
        str(item).strip() for item in (entry.get("negatives") or []) if str(item).strip()
    )
    return negatives


def catalog_prompt(snapshot: Mapping[str, Any]) -> str:
    fields = snapshot.get("fields")
    if not isinstance(fields, Mapping):
        return ""
    lines = []
    for name in sorted(fields):
        entry = fields[name]
        if not isinstance(entry, Mapping):
            continue
        operators = ",".join(str(item) for item in (entry.get("operators") or []) if str(item).strip())
        enums = [str(item) for item in (entry.get("enums") or []) if str(item).strip()]
        enum_text = ",".join(enums[:_ENUM_PROMPT_LIMIT])
        if len(enums) > _ENUM_PROMPT_LIMIT:
            enum_text += f"…(+{len(enums) - _ENUM_PROMPT_LIMIT})"
        aliases = [str(item) for item in (entry.get("aliases") or []) if str(item).strip()][:8]
        supported = "false" if entry.get("is_supported") is False else "true"
        desc = str(entry.get("description") or "").replace("\n", " ")[:80]
        piece = f"{name} supported={supported}"
        if operators:
            piece += f" op={operators}"
        if enum_text:
            piece += f" enum={enum_text}"
        if aliases:
            piece += f" alias={','.join(aliases)}"
        if desc:
            piece += f" {desc}"
        lines.append(piece)
    body = "\n".join(lines)
    lex = lexicon_prompt(snapshot)
    if lex:
        body = f"{body}\n\n受治理业务词口径：\n{lex}" if body else f"受治理业务词口径：\n{lex}"
    hints = attention_prompt(snapshot)
    if hints:
        section = (
            "调用方注意力提示（caller_stated 最低档：仅提示读法注意某处，"
            "不构成承载证据，不改变任何断言档位）：\n" + hints
        )
        body = f"{body}\n\n{section}" if body else section
    return body


def attention_prompt(snapshot: Mapping[str, Any]) -> str:
    """caller-stated 注意力提示（judge.md §7.3 第二用途）：只进提示面，不进断言。"""
    lines = []
    for item in snapshot.get("attention") or []:
        if not isinstance(item, Mapping):
            continue
        note = str(item.get("note") or "").strip()
        if not note:
            continue
        field = str(item.get("field") or "").strip()
        lines.append(f"{field}：{note}" if field else note)
    return "\n".join(lines)


def normalize_lexicon(raw: Any) -> list[dict[str, Any]]:
    payload = raw.get("terms") if isinstance(raw, Mapping) else raw
    terms: list[dict[str, Any]] = []
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return terms
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        term = str(item.get("term") or "").strip()
        status = str(item.get("status") or "").strip()
        field = str(item.get("field") or "").strip()
        if not term or status not in {"unsupported", "carried", "missing"}:
            continue
        if status != "missing" and not field:
            continue
        aliases = [
            str(alias).strip()
            for alias in (item.get("aliases") or [])
            if str(alias).strip()
        ]
        terms.append({
            "term": term,
            "aliases": aliases,
            "field": field,
            "status": status,
            "note": str(item.get("note") or "").strip(),
            "evidence": str(item.get("evidence") or "").strip(),
        })
    return terms


def lexicon_prompt(snapshot: Mapping[str, Any]) -> str:
    lines = []
    for item in snapshot.get("lexicon") or []:
        if not isinstance(item, Mapping):
            continue
        term = str(item.get("term") or "").strip()
        if not term:
            continue
        if item.get("status") == "missing":
            note = str(item.get("note") or "目录无此维").strip()
            lines.append(f"{term} 确认缺维度 {note}".rstrip())
            continue
        field = str(item.get("field") or "").strip()
        status = str(item.get("status") or "").strip()
        lines.append(f"{term} → {field} status={status}")
    return "\n".join(lines)


def lexicon_hits(query: str, snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    text = str(query or "").strip()
    if not text:
        return []
    found: list[dict[str, Any]] = []
    for item in snapshot.get("lexicon") or []:
        if not isinstance(item, Mapping):
            continue
        needles = [str(item.get("term") or "").strip(), *[
            str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip()
        ]]
        matched = [needle for needle in needles if needle and needle in text]
        if not matched:
            continue
        found.append({**dict(item), "matched": max(matched, key=len)})
    if not found:
        return []
    best = max(len(str(item.get("matched") or "")) for item in found)
    return [item for item in found if len(str(item.get("matched") or "")) == best]


def unmapped_verdict(items: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any]) -> CarrierVerdict:
    revision = str(snapshot.get("revision") or snapshot_id(snapshot)[:16])
    citations: list[dict[str, str]] = [{
        "source": "capability_manifest",
        "ref": "fields",
        "revision": revision,
        "tier": _catalog_tier(snapshot),
        "note": "unmapped",
    }]
    surfaces: list[str] = []
    for item in items:
        surface = str(item.get("surface") or "").strip()
        if surface:
            surfaces.append(surface)
        for near in item.get("nearest") or []:
            if not isinstance(near, Mapping):
                continue
            field = str(near.get("field") or "").strip()
            why = str(near.get("why") or "").strip()
            if not field:
                continue
            entry = _field_entry(snapshot, field)
            citations.append({
                "source": "capability_manifest",
                "ref": field,
                "revision": revision,
                "tier": assertion_tier(entry) if entry else _catalog_tier(snapshot),
                "note": why or f"unmapped:{surface}",
            })
    label = "、".join(surfaces) or "未登记维度"
    return CarrierVerdict(
        CARRY_NO,
        f"空间缺维度 {label}",
        citations=tuple(citations),
        recognition=RECOG_UNMAPPED,
    )


def _has_cjk(text: str) -> bool:
    return bool(_CJK.search(text))


def _governed_alias(alias: str, description: str, negatives: Iterable[str] = ()) -> bool:
    text = str(alias or "").strip()
    if not _usable_alias(text) or len(text) < 2 or not _has_cjk(text):
        return False
    if _ALIAS_JUNK.search(text):
        return False
    if text in {str(item).strip() for item in negatives if str(item).strip()}:
        return False
    return text in str(description or "")


def _enum_substring_ok(value: str) -> bool:
    text = str(value or "")
    if not _usable_alias(text):
        return False
    if _has_cjk(text):
        return len(text) >= 2
    return len(text) >= 4


def _tokens(text: str) -> list[str]:
    return [part for part in _TOKEN_SPLIT.split(str(text or "")) if part]


def _short_cjk(text: str) -> bool:
    return _has_cjk(text) and len(text) == 2


def _enum_in_query(value: str, text: str) -> bool:
    if value == text:
        return True
    if not _enum_substring_ok(value):
        return False
    if _short_cjk(value):
        return value in _tokens(text)
    return value in text


def _alias_in_query(alias: str, text: str) -> bool:
    if alias == text or alias in _tokens(text):
        return True
    if _short_cjk(alias):
        return any(
            token.endswith(alias) and len(token) == len(alias) + 1
            for token in _tokens(text)
        )
    return alias in text


def build_catalog_index(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    fields = snapshot.get("fields")
    if not isinstance(fields, Mapping):
        return {"enum_to_fields": {}, "alias_to_field": {}, "operators": {}, "field_enums": {}}
    enum_to_fields: dict[str, list[str]] = {}
    alias_owners: dict[str, list[str]] = {}
    operators: dict[str, list[str]] = {}
    field_enums: dict[str, list[str]] = {}
    for name, entry in fields.items():
        if not isinstance(entry, Mapping):
            continue
        field = str(name)
        operators[field] = [
            str(item).strip() for item in (entry.get("operators") or []) if str(item).strip()
        ]
        field_enums[field] = [
            str(item).strip() for item in (entry.get("enums") or []) if str(item).strip()
        ]
        description = str(entry.get("description") or "")
        negatives = set(_negatives_for(entry))
        negatives.update(str(item).strip() for item in (entry.get("negatives") or []) if str(item).strip())
        for raw in entry.get("enums") or []:
            value = str(raw).strip()
            if value:
                enum_to_fields.setdefault(value, []).append(field)
        for raw in entry.get("aliases") or []:
            alias = str(raw).strip()
            if _governed_alias(alias, description, negatives):
                alias_owners.setdefault(alias, []).append(field)
    return {
        "enum_to_fields": enum_to_fields,
        "alias_to_field": {
            alias: names[0]
            for alias, names in alias_owners.items()
            if len(set(names)) == 1
        },
        "operators": operators,
        "field_enums": field_enums,
    }


def _longest_uncontained(values: Sequence[str]) -> list[str]:
    ordered = sorted({str(item) for item in values if item}, key=len, reverse=True)
    kept: list[str] = []
    for item in ordered:
        if any(item != other and item in other for other in kept):
            continue
        kept.append(item)
    return kept


def catalog_hits(query: str, index: Mapping[str, Any]) -> list[CatalogHit]:
    text = str(query or "").strip()
    if not text:
        return []
    enum_to_fields = index.get("enum_to_fields") or {}
    matched_enums: list[str] = []
    if text in enum_to_fields:
        matched_enums.append(text)
    for value in enum_to_fields:
        if value == text:
            continue
        if _enum_in_query(value, text):
            matched_enums.append(value)
    hits = [
        CatalogHit(field=field, kind="enum", evidence=value, value=value)
        for value in _longest_uncontained(matched_enums)
        for field in enum_to_fields.get(value) or []
    ]
    enum_fields = {item.field for item in hits}
    alias_hits = []
    for alias, field in (index.get("alias_to_field") or {}).items():
        if field in enum_fields:
            continue
        if not _alias_in_query(alias, text):
            continue
        alias_hits.append(CatalogHit(field=field, kind="alias", evidence=alias, value=""))
    kept_aliases = _longest_uncontained([item.evidence for item in alias_hits])
    hits.extend(item for item in alias_hits if item.evidence in kept_aliases)
    return hits


def _default_operator(field: str, index: Mapping[str, Any]) -> str:
    operators = list(index.get("operators", {}).get(field) or [])
    for preferred in ("MATCH", "CONTAINS", "EQ"):
        if preferred in operators:
            return preferred
    return operators[0] if operators else ""


def _reading_from_hit(hit: CatalogHit, index: Mapping[str, Any]) -> CarrierReading:
    value = hit.value
    if not value and hit.kind == "alias" and (index.get("field_enums") or {}).get(hit.field):
        value = hit.evidence
    return CarrierReading(
        field=hit.field,
        value=value,
        operator=_default_operator(hit.field, index),
    )


def _reading_from_lexicon(hit: Mapping[str, Any], index: Mapping[str, Any]) -> CarrierReading:
    field = str(hit.get("field") or "").strip()
    matched = str(hit.get("matched") or hit.get("term") or "").strip()
    enums = (index.get("field_enums") or {}).get(field) or []
    value = ""
    if enums:
        needles = [str(hit.get("term") or "").strip(), *[
            str(alias).strip() for alias in (hit.get("aliases") or []) if str(alias).strip()
        ]]
        in_enum = [needle for needle in needles if needle in enums]
        value = "~".join(in_enum) if in_enum else matched
    return CarrierReading(
        field=field,
        value=value,
        operator=_default_operator(field, index),
    )


def _lexicon_missing_item(item: Mapping[str, Any], hit: Mapping[str, Any]) -> dict[str, Any]:
    leftover = dict(item)
    note = str(hit.get("note") or "口径表确认空间缺该维").strip()
    nearest: list[dict[str, Any]] = []
    for near in leftover.get("nearest") or []:
        if not isinstance(near, Mapping):
            continue
        row = dict(near)
        if note:
            row["why"] = note
        nearest.append(row)
    leftover["nearest"] = nearest or [{"field": "searchClientName", "why": note}]
    return leftover


def rescue_catalog_misses(
    alternatives: Sequence[Sequence[CarrierReading]],
    unmapped: Sequence[Mapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> tuple[list[list[CarrierReading]], list[dict[str, Any]]]:
    """缺值/缺维度定案前，先口径表再全量枚举和受治理别名反查。命中则改写成读法再裁承载。"""
    index = build_catalog_index(snapshot)
    rescued = _rescue_missing_values(alternatives, snapshot, index)
    remaining: list[dict[str, Any]] = []
    unmapped_alts: list[list[CarrierReading]] = []
    for item in unmapped:
        if not isinstance(item, Mapping):
            continue
        surface = str(item.get("surface") or "")
        lex = lexicon_hits(surface, snapshot)
        if lex:
            for hit in lex:
                if hit.get("status") == "missing":
                    remaining.append(_lexicon_missing_item(item, hit))
                elif str(hit.get("field") or "").strip():
                    unmapped_alts.append([_reading_from_lexicon(hit, index)])
            continue
        hits = catalog_hits(surface, index)
        if hits:
            unmapped_alts.extend([[_reading_from_hit(hit, index)] for hit in hits])
        else:
            remaining.append(dict(item))
    if rescued:
        return rescued, remaining
    if unmapped_alts:
        return unmapped_alts, []
    return [], remaining


def _rescue_missing_values(
    alternatives: Sequence[Sequence[CarrierReading]],
    snapshot: Mapping[str, Any],
    index: Mapping[str, Any],
) -> list[list[CarrierReading]]:
    rescued: list[list[CarrierReading]] = []
    for group in alternatives:
        new_group: list[CarrierReading] = []
        extras: list[list[CarrierReading]] = []
        for reading in group:
            verdict = evaluate_reading(reading, snapshot)
            if verdict.recognition != RECOG_MISSING_VALUE:
                new_group.append(reading)
                continue
            homes: list[CatalogHit] = []
            seen: set[tuple[str, str]] = set()
            parts = [part for part in str(reading.value or "").split("~") if part] or [str(reading.value or "")]
            for part in parts:
                for hit in catalog_hits(part, index):
                    if hit.kind != "enum" or hit.field == reading.field:
                        continue
                    key = (hit.field, hit.value)
                    if key in seen:
                        continue
                    seen.add(key)
                    homes.append(hit)
            if not homes:
                new_group.append(reading)
                continue
            fields_hit = {hit.field for hit in homes}
            if len(fields_hit) == 1:
                field = homes[0].field
                values = [hit.value for hit in homes]
                new_group.append(CarrierReading(
                    field=field,
                    value="~".join(values) if len(values) > 1 else values[0],
                    operator=_default_operator(field, index),
                    match_mode=reading.match_mode,
                ))
            else:
                extras.extend([[_reading_from_hit(hit, index)] for hit in homes])
        if new_group:
            rescued.append(new_group)
        rescued.extend(extras)
    return rescued


def _canonical_value(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return str(raw).lower()
    if isinstance(raw, (int, float)):
        return str(raw)
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (list, tuple)):
        parts = [_canonical_value(item) for item in raw]
        return "~".join(part for part in parts if part)
    if isinstance(raw, Mapping):
        if any(key in raw for key in ("min", "max", "start", "end", "from", "to", "lower", "upper")):
            lo = _canonical_value(raw.get("min", raw.get("start", raw.get("from", raw.get("lower")))))
            hi = _canonical_value(raw.get("max", raw.get("end", raw.get("to", raw.get("upper")))))
            return "~".join(part for part in (lo, hi) if part)
        if "value" in raw:
            return _canonical_value(raw.get("value"))
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)
    return str(raw).strip()


def _canonical_operator(raw: Any) -> tuple[str, str]:
    if raw is None:
        return "", ""
    if isinstance(raw, str):
        return raw.strip(), ""
    if isinstance(raw, Mapping):
        operator = str(raw.get("operator") or raw.get("op") or "").strip()
        match_mode = str(raw.get("match_mode") or raw.get("mode") or "").strip()
        if not operator and match_mode:
            operator = "MATCH"
        return operator, match_mode
    return str(raw).strip(), ""


def parse_mapper_payload(
    data: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
) -> tuple[list[list[CarrierReading]], list[dict[str, Any]]] | None:
    if not isinstance(data, Mapping):
        return None
    catalog = _catalog_fields(snapshot)
    if bool(data.get("process_only")):
        return ([[CarrierReading(field=PROCESS_FIELD, kind="process")]], [])
    alternatives: list[list[CarrierReading]] = []
    for group in data.get("alternatives") or []:
        raw_readings = group.get("readings") if isinstance(group, Mapping) else None
        if not isinstance(raw_readings, (list, tuple)):
            continue
        readings: list[CarrierReading] = []
        for item in raw_readings:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("field") or "").strip()
            if name not in catalog:
                continue
            operator, match_from_op = _canonical_operator(item.get("operator"))
            raw_value = item.get("value")
            match_from_value = ""
            if isinstance(raw_value, Mapping):
                match_from_value = str(raw_value.get("match_mode") or raw_value.get("mode") or "").strip()
            match_mode = (
                str(item.get("match_mode") or "").strip()
                or match_from_op
                or match_from_value
            )
            readings.append(CarrierReading(
                field=name,
                value=_canonical_value(raw_value),
                operator=operator,
                match_mode=match_mode,
            ))
        if readings:
            alternatives.append(readings)
    unmapped: list[dict[str, Any]] = []
    for item in data.get("unmapped") or []:
        if not isinstance(item, Mapping):
            continue
        surface = str(item.get("surface") or "").strip()
        nearest: list[dict[str, str]] = []
        for near in item.get("nearest") or []:
            if not isinstance(near, Mapping):
                continue
            field = str(near.get("field") or "").strip()
            why = str(near.get("why") or "").strip()
            if field not in catalog or not why:
                continue
            nearest.append({"field": field, "why": why})
        if not surface or not nearest:
            continue
        unmapped.append({"surface": surface, "nearest": nearest})
    if not alternatives and not unmapped:
        return None
    return alternatives, unmapped


def _verdict_signature(verdict: CarrierVerdict) -> tuple[Any, ...]:
    """复读一致性只比裁决签名：承载答案、成因、缺口类型。

    carry=yes 时不比引用字段集——等价读法的字段差异不是不稳。
    carry=no 仍比引用维度，避免把不同缺口合成同一票。
    LLM 自由文本不参与比较。
    """
    if verdict.carry == CARRY_YES:
        return (verdict.carry, verdict.recognition, verdict.gap_kind)
    return (
        verdict.carry,
        verdict.recognition,
        verdict.gap_kind,
        tuple(sorted(str(item.get("ref") or "") for item in verdict.citations)),
    )


def _mapper_output_spec():
    from .structured_output import StructuredOutputSpec

    return StructuredOutputSpec.from_dataclass(
        _MapperOutput,
        description="轴2读法抽取：只输出期望在受治理目录里的最小完整表达，不输出裁决三态",
    )


_MAPPER_SYSTEM = """你把一条未达成的业务期望，映射到受治理能力空间的最小完整表达。
只输出读法，不要判断办成了没有，不要输出做不了/做错了/说不清。
输入里没有这次交付，也不许假设交付内容。

规则：
- alternatives：每种合理读法一组；一组内 readings 是合取。
- readings.field 必须是目录里的字段名。
- readings.operator 必须是目录里的操作符名（MATCH / RANGE / GTE 等）。前缀或尾号匹配写 operator=MATCH，match_mode=prefix 或 suffix；不要把 match_mode 做成 operator 对象。
- 区间值写成数组 [起点, 终点] 或标量字符串；数字直接写数字即可。
- 目录里找不到能完整表达该维的字段时写入 unmapped；nearest 必填，写扫过的最近候选和它为什么不是该维。
- 口径表（目录末尾「受治理业务词口径」）命中的词必须按表落地：有字段写该字段，确认缺维度写 unmapped，不得改写成别的字段。
- 纯过程约束（不增加/不虚构/不将某词误识别为条件）且不要求新维度：process_only=true，alternatives 与 unmapped 都空。
- 除非 process_only=true，alternatives 与 unmapped 不得同时为空。
- 姓名与产品等互斥读法分成多个 alternative，不要合成一组。
"""


def call_mapper_llm(
    spec: Any,
    expectation: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> Mapping[str, Any]:
    from .llm_client import project_llm_client

    client = project_llm_client(spec, role="capability_carrier_mapper", tools=[])
    user = (
        "期望：\n"
        + _expectation_text(expectation)
        + "\n\n受治理维度目录：\n"
        + catalog_prompt(snapshot)
    )
    return client.complete_json(
        _MAPPER_SYSTEM,
        user,
        reasoning_effort="low",
        output_spec=_mapper_output_spec(),
        stage="capability_carrier_mapper",
    )


def snapshot_from_capability_manifest(
    manifest: Mapping[str, Any] | None,
    *,
    spoken: Mapping[str, Any] | None = None,
    lexicon: Mapping[str, Any] | Sequence[Any] | None = None,
) -> dict[str, Any]:
    if manifest is None:
        return {"fields": None}
    fields: dict[str, Any] = {}
    spoken_map = spoken if isinstance(spoken, Mapping) else {}
    for name, entry in manifest.items():
        if not isinstance(entry, Mapping):
            continue
        operators = entry.get("operators") or []
        aliases = _aliases_for(str(name), entry)
        aliases.update(_spoken_aliases(spoken_map.get(str(name))))
        built = {
            "operators": sorted(str(item) for item in operators if str(item).strip()),
            "enums": sorted(str(item) for item in (entry.get("enums") or [])),
            "is_supported": entry.get("is_supported") is not False,
            "governed": True,
            "source": "capability_manifest",
            "description": str(entry.get("description") or ""),
            "notes": str(entry.get("notes") or ""),
            "aliases": sorted(aliases),
            "negatives": sorted(_negatives_for(entry)),
            "spoken": sorted(_spoken_aliases(spoken_map.get(str(name)))),
        }
        # 物料可显式声明戳记（出处/信任档位/新鲜度/担保），未声明的走缺省映射。
        for stamp_key in ("provenance", "trust_tier", "staleness", "warrant"):
            declared = str(entry.get(stamp_key) or "").strip()
            if declared:
                built[stamp_key] = declared
        fields[str(name)] = built
    terms = normalize_lexicon(lexicon)
    payload = {"fields": fields, "lexicon": terms}
    payload["revision"] = snapshot_id({"fields": fields, "lexicon": terms})[:16]
    return stamp_claims(payload)


class StructuredCarrier(CapabilityCarrierBase):
    """Structured form: mapper readings against a field catalog snapshot."""

    def __init__(
        self,
        snapshot: Mapping[str, Any] | None,
        *,
        spec: Any = None,
        mapper: MapperFn | None = None,
        replicate: bool | None = None,
        mapper_retries: int | None = None,
        retry_backoff: Sequence[float] | None = None,
    ):
        raw = dict(snapshot) if isinstance(snapshot, Mapping) else {"fields": None}
        if isinstance(raw.get("fields"), Mapping):
            # 装载期戳记与 fail-fast：缺省映射补齐三件套后仍不合法（如非法档位）即拒。
            raw = stamp_claims(raw)
            require_stamped_claims(raw)
        self.snapshot = raw
        self.spec = spec
        self.mapper = mapper
        self.replicate = mapper is None if replicate is None else replicate
        self.mapper_retries = max(
            1,
            mapper_retries if mapper_retries is not None else _DEFAULT_MAPPER_RETRIES,
        )
        self.retry_backoff = (
            tuple(retry_backoff)
            if retry_backoff is not None
            else ((0.0,) if mapper is not None else _DEFAULT_RETRY_BACKOFF)
        )
        self._cache: dict[tuple[str, str], CarrierVerdict] = {}
        self._mapper_cache: dict[str, list[tuple[list[list[CarrierReading]], list[dict[str, Any]]]]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_materials(
        cls,
        manifest: Mapping[str, Any],
        *,
        lexicon: Mapping[str, Any] | Sequence[Any] | None = None,
        spoken: Mapping[str, Any] | None = None,
        spec: Any = None,
        mapper: MapperFn | None = None,
        replicate: bool | None = None,
        mapper_retries: int | None = None,
        retry_backoff: Sequence[float] | None = None,
    ) -> "StructuredCarrier":
        snapshot = snapshot_from_capability_manifest(
            manifest,
            spoken=spoken,
            lexicon=lexicon,
        )
        return cls(
            snapshot,
            spec=spec,
            mapper=mapper,
            replicate=replicate,
            mapper_retries=mapper_retries,
            retry_backoff=retry_backoff,
        )

    def snapshot_revision(self) -> str:
        return snapshot_id(self.snapshot) if self.snapshot else ""

    def citation_space(self) -> set[str] | None:
        fields = self.snapshot.get("fields")
        if not isinstance(fields, Mapping):
            return None
        return {str(name) for name in fields if str(name).strip()}

    def dimension_key(
        self,
        alternatives: Sequence[Sequence[CarrierReading]],
        unmapped: Sequence[Mapping[str, Any]] | None = None,
    ) -> str:
        payload = {
            "readings": [
                [item.kind, item.field, item.value, item.operator, item.match_mode]
                for group in alternatives
                for item in group
            ],
            "unmapped": [
                str(item.get("surface") or "")
                for item in (unmapped or [])
                if isinstance(item, Mapping)
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _backoff(self, attempt: int) -> None:
        if attempt + 1 >= self.mapper_retries:
            return
        delay = self.retry_backoff[min(attempt, len(self.retry_backoff) - 1)]
        if delay > 0:
            time.sleep(delay)

    def _draw_parsed(
        self,
        expectation: Mapping[str, Any],
    ) -> tuple[list[list[CarrierReading]], list[dict[str, Any]]]:
        last_error = "读法输出无法解析为目录内读法"
        for attempt in range(self.mapper_retries):
            try:
                payload = self._invoke_mapper(expectation)
            except Exception as exc:
                last_error = str(exc)
                self._backoff(attempt)
                continue
            parsed = parse_mapper_payload(payload, self.snapshot)
            if parsed is None:
                last_error = "读法输出无法解析为目录内读法"
                self._backoff(attempt)
                continue
            return parsed
        raise MapperExhausted(last_error)

    def _load_parsed_draws(
        self,
        expectation: Mapping[str, Any],
    ) -> list[tuple[list[list[CarrierReading]], list[dict[str, Any]]]] | CarrierError:
        text = _expectation_text(expectation)
        cache_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self._lock:
            cached = self._mapper_cache.get(cache_key)
            if cached is not None:
                return cached
        try:
            draws = [self._draw_parsed(expectation)]
            if self.replicate:
                draws.append(self._draw_parsed(expectation))
        except MapperExhausted as exc:
            return CarrierError("mapper", "读法抽取重试耗尽", str(exc))
        with self._lock:
            self._mapper_cache[cache_key] = draws
        return draws

    def _invoke_mapper(self, expectation: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.mapper is not None:
            data = self.mapper(expectation, self.snapshot)
            if not isinstance(data, Mapping):
                raise ValueError("mapper must return a mapping")
            return data
        if self.spec is None:
            raise ValueError("capability_carrier mapper missing spec")
        return call_mapper_llm(self.spec, expectation, self.snapshot)

    def verdict_for(self, expectation: Mapping[str, Any]) -> CarrierVerdict | CarrierError:
        if self.snapshot.get("fields") is None:
            return CarrierError(
                "snapshot",
                "能力空间快照不可用",
                str(self.snapshot.get("load_error") or ""),
            )
        draws = self._load_parsed_draws(expectation)
        if isinstance(draws, CarrierError):
            return draws
        verdicts = [self._verdict_from_parsed(*parsed) for parsed in draws]
        if len(verdicts) > 1 and _verdict_signature(verdicts[0]) != _verdict_signature(verdicts[1]):
            try:
                third = self._draw_parsed(expectation)
            except MapperExhausted as exc:
                return CarrierError("mapper", "读法抽取重试耗尽", str(exc))
            verdicts.append(self._verdict_from_parsed(*third))
            counts = Counter(_verdict_signature(item) for item in verdicts)
            top_sig, votes = counts.most_common(1)[0]
            if votes >= 2:
                return next(item for item in verdicts if _verdict_signature(item) == top_sig)
            return CarrierVerdict(
                CARRY_UNDECIDABLE,
                "不同读法承载性答案不一致",
                gap_kind=GAP_AMBIGUITY,
                missing_material="受治理口径",
            )
        return verdicts[0]

    def _verdict_from_parsed(
        self,
        alternatives: Sequence[Sequence[CarrierReading]],
        unmapped: Sequence[Mapping[str, Any]],
    ) -> CarrierVerdict:
        cache_key = (self.dimension_key(alternatives, unmapped), snapshot_id(self.snapshot))
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached
            alternatives, unmapped = rescue_catalog_misses(
                alternatives, unmapped, self.snapshot,
            )
            if alternatives:
                verdict = resolve_carrier(alternatives, self.snapshot)
            elif unmapped:
                verdict = unmapped_verdict(unmapped, self.snapshot)
            else:
                verdict = resolve_carrier(alternatives, self.snapshot)
            self._cache[cache_key] = verdict
            return verdict

