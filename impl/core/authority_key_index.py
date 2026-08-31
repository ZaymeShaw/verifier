"""MaterialDecision navigation index for Authority.

The index only narrows which investigated material/statement to inspect.  Its
entries and loaded targets are not EvidenceSpace facts and cannot be cited as
``basis_evidence_ref_ids``.  Authority must still Load the linked ContextUnit.
"""
from __future__ import annotations

import re
from urllib.parse import unquote
from typing import Any, Callable, Mapping, Sequence

from impl.core.investigation_key_index import (
    InvestigationKeyIndexRegistry,
    create_key_index_tools,
)
from impl.core.schema.investigation_judge import (
    AuthorityInvestigationReport,
    decision_proof_power,
)
from impl.core.schema.investigation_key_index import (
    InvestigationKeyEntry,
    InvestigationKeyIndex,
)

MATERIAL_DECISION_INDEX_KEY = "authority.material-decisions"
_TARGET_PREFIX = "material-decision://"
_COVERAGE_GAP_TARGET_PREFIX = "coverage-gap://"
_TOKEN = re.compile(r"[A-Za-z0-9_.-]+")
_EVIDENCE_NAVIGATION_PREFIX = "evidence-navigation://"
LoadTargetResolver = Callable[[str, str], Mapping[str, Any]]


def _resolve_load_targets(
    *,
    source_ref_id: str,
    locator: str,
    load_target_resolver: LoadTargetResolver | None,
) -> dict[str, Any]:
    if load_target_resolver is None:
        return {}
    resolution = dict(load_target_resolver(source_ref_id, locator))
    load_targets = [
        str(item).strip()
        for item in resolution.pop("load_targets", ())
        if str(item).strip()
    ]
    return {
        "load_targets": load_targets,
        "target_resolution": resolution,
    }


def _evidence_navigation_target(
    target_ref: str,
    *,
    load_target_resolver: LoadTargetResolver | None = None,
) -> dict[str, Any]:
    payload = target_ref[len(_EVIDENCE_NAVIGATION_PREFIX):]
    source_ref_id, separator, encoded_locator = payload.partition("/")
    if not source_ref_id or not separator or not encoded_locator:
        raise ValueError(f"invalid evidence navigation target_ref: {target_ref}")
    locator = unquote(encoded_locator)
    content = {
        "source_ref_id": source_ref_id,
        "evidence_search_hint": f"{source_ref_id} {locator}",
        "locator": locator,
        "navigation_only": True,
    }
    return {
        "content": content,
        "locator": locator,
        **_resolve_load_targets(
            source_ref_id=source_ref_id,
            locator=locator,
            load_target_resolver=load_target_resolver,
        ),
        "provenance": {
            "source_ref_id": source_ref_id,
            "projection": "source-derived-key-index",
        },
    }

def _terms(text: str) -> set[str]:
    normalized = str(text or "").lower()
    tokens = set(_TOKEN.findall(normalized))
    compact_cjk = "".join(ch for ch in normalized if "\u3400" <= ch <= "\u9fff")
    tokens.update(compact_cjk[index : index + 2] for index in range(max(0, len(compact_cjk) - 1)))
    return {item for item in tokens if item}


def lexical_material_decision_search(
    query: str,
    entries: Sequence[InvestigationKeyEntry],
    limit: int,
) -> Sequence[tuple[InvestigationKeyEntry, float | None]]:
    """Small deterministic default; projects may replace it with another strategy."""
    query_text = str(query or "").strip().lower()
    query_terms = _terms(query_text)
    ranked: list[tuple[InvestigationKeyEntry, float]] = []
    for entry in entries:
        haystack = f"{entry.name} {entry.search_text}".lower()
        overlap = len(query_terms & _terms(haystack))
        phrase_bonus = 4 if query_text and query_text in haystack else 0
        name_bonus = 2 if query_text and query_text in entry.name.lower() else 0
        score = float(overlap + phrase_bonus + name_bonus)
        if score > 0:
            ranked.append((entry, score))
    ranked.sort(key=lambda item: (-item[1], item[0].key))
    return ranked[:limit]


def coverage_gap_trigger_hit(
    report: AuthorityInvestigationReport,
    request_text: str,
    *,
    limit: int = 3,
) -> str | None:
    """返回请求文本触发的覆盖缺口 gap_id，未触发返回 None。

    确定性触发面（investigate-authority-judge.md §11/§17 的缺口索引消费）：
    请求文本在完整 material-decisions 索引中的唯一最高命中是 coverage-gap 条目时，
    说明该请求触及"当前没有唯一决定资料"的业务事项，需要装配 authority 现场裁决；
    若更相关的已登记 MaterialDecision 排在其上，说明该事项有资料覆盖，不触发。
    缺口内容由调查层固化，匹配走与字段导航同一套词法索引机制，不属于 Judge 启发式。
    """
    query = str(request_text or "").strip()
    if not query:
        return None
    entries = build_material_decision_key_index(report).entries
    hits = lexical_material_decision_search(query, entries, limit=limit)
    if not hits:
        return None
    top_entry = hits[0][0]
    if not top_entry.target_ref.startswith(_COVERAGE_GAP_TARGET_PREFIX):
        return None
    return top_entry.key.split(".", 1)[-1]


def build_material_decision_key_index(
    report: AuthorityInvestigationReport,
) -> InvestigationKeyIndex:
    entries: list[InvestigationKeyEntry] = []
    for material in report.materials:
        for position, decision in enumerate(material.decisions, start=1):
            key = f"{material.source_ref_id}.decision-{position}"
            target_ref = f"{_TARGET_PREFIX}{material.source_ref_id}/{position}"
            search_text = " ".join(
                part
                for part in (
                    decision.conclusion_kind,
                    # 显式担保档位（未声明时为空，检索面与既有逐字一致）。
                    decision.warrant_tier,
                    decision.governs,
                    decision.statement,
                    decision.scenario,
                    *decision.conditions,
                    *material.related_to,
                    *material.limitations,
                )
                if str(part or "").strip()
            )
            entries.append(
                InvestigationKeyEntry(
                    key=key,
                    name=decision.governs,
                    search_text=search_text,
                    target_ref=target_ref,
                )
            )
    for gap in report.coverage_gaps:
        search_text = " ".join(
            part
            for part in (
                gap.conclusion_kind,
                gap.governs,
                gap.gap_reason,
                *gap.conditions,
                *gap.dimension_ids,
                *gap.required_evidence,
            )
            if str(part or "").strip()
        )
        entries.append(
            InvestigationKeyEntry(
                key=f"coverage-gap.{gap.gap_id}",
                name=gap.governs,
                search_text=search_text,
                target_ref=f"{_COVERAGE_GAP_TARGET_PREFIX}{gap.gap_id}",
            )
        )
    return InvestigationKeyIndex(
        index_key=MATERIAL_DECISION_INDEX_KEY,
        collection_ref="authority-investigation-report",
        target_kind="material_decision",
        entry_granularity="investigated_statement",
        entries=tuple(entries),
    )


def build_material_decision_key_index_registry(
    report: AuthorityInvestigationReport,
    *,
    evidence_unit_ids: Mapping[str, str] | None = None,
    index: InvestigationKeyIndex | None = None,
    load_target_resolver: LoadTargetResolver | None = None,
) -> InvestigationKeyIndexRegistry:
    evidence_units = dict(evidence_unit_ids or {})
    targets: dict[str, dict[str, Any]] = {}
    index = index or build_material_decision_key_index(report)
    if index.index_key != MATERIAL_DECISION_INDEX_KEY:
        raise ValueError(f"unexpected MaterialDecision index key: {index.index_key}")
    if index.collection_ref != "authority-investigation-report":
        raise ValueError(
            "MaterialDecision index collection_ref must be authority-investigation-report"
        )
    if index.target_kind != "material_decision":
        raise ValueError("MaterialDecision index target_kind must be material_decision")
    if index.entry_granularity != "investigated_statement":
        raise ValueError(
            "MaterialDecision index entry_granularity must be investigated_statement"
        )
    for material in report.materials:
        for position, decision in enumerate(material.decisions, start=1):
            target_ref = f"{_TARGET_PREFIX}{material.source_ref_id}/{position}"
            content = {
                "source_ref_id": material.source_ref_id,
                "source_location": material.source_location.to_mapping(),
                "evidence_unit_id": evidence_units.get(material.source_ref_id, ""),
                "evidence_search_hint": " ".join(
                    part for part in (material.source_ref_id, decision.locator) if part
                ),
                "decision": decision.as_dict(),
                # 证明力最终档位：warrant_tier 优先，未声明时缺省映射到
                # conclusion_kind（judge.md §6，与既有档位判断结果一致）。
                "proof_power": decision_proof_power(decision),
                "limitations": list(material.limitations),
                "connections": [item.as_dict() for item in material.connections],
                "navigation_only": True,
            }
            targets[target_ref] = {
                "content": content,
                "locator": decision.locator,
                **_resolve_load_targets(
                    source_ref_id=material.source_ref_id,
                    locator=decision.locator,
                    load_target_resolver=load_target_resolver,
                ),
                "provenance": {
                    "authority_report_schema_version": report.schema_version,
                    "source_ref_id": material.source_ref_id,
                },
            }

    for gap in report.coverage_gaps:
        target_ref = f"{_COVERAGE_GAP_TARGET_PREFIX}{gap.gap_id}"
        targets[target_ref] = {
            "content": {
                "coverage_gap": gap.as_dict(),
                "navigation_only": True,
                "basis_search_hints": list(gap.basis_source_ref_ids),
            },
            "locator": f"coverage_gaps[{gap.gap_id}]",
            "provenance": {
                "authority_report_schema_version": report.schema_version,
                "report_id": report.report_id,
            },
        }

    def validate_target(target_ref: str) -> None:
        if target_ref not in targets:
            raise ValueError(f"unknown MaterialDecision target_ref: {target_ref}")

    def resolve_target(target_ref: str) -> Mapping[str, Any]:
        validate_target(target_ref)
        return targets[target_ref]

    registry = InvestigationKeyIndexRegistry()
    registry.register(
        index,
        resolver=resolve_target,
        search_strategy=lexical_material_decision_search,
        target_validator=validate_target,
    )
    return registry


def build_authority_key_index_registry(
    report: AuthorityInvestigationReport,
    *,
    indexes: Sequence[InvestigationKeyIndex],
    evidence_unit_ids: Mapping[str, str] | None = None,
    load_target_resolver: LoadTargetResolver | None = None,
) -> InvestigationKeyIndexRegistry:
    material_index = next(
        (item for item in indexes if item.index_key == MATERIAL_DECISION_INDEX_KEY),
        None,
    )
    registry = build_material_decision_key_index_registry(
        report,
        evidence_unit_ids=evidence_unit_ids,
        index=material_index,
        load_target_resolver=load_target_resolver,
    )
    for index in indexes:
        if index.index_key == MATERIAL_DECISION_INDEX_KEY:
            continue
        if index.target_kind != "evidence_locator":
            raise ValueError(
                f"Authority evidence navigation index target_kind must be evidence_locator: "
                f"{index.index_key}"
            )

        def validate_target(
            target_ref: str, _index: InvestigationKeyIndex = index
        ) -> None:
            if not target_ref.startswith(_EVIDENCE_NAVIGATION_PREFIX):
                raise ValueError(
                    f"unsupported Authority navigation target_ref: {target_ref}"
                )
            target = _evidence_navigation_target(target_ref)
            source_ref_id = str(target["content"]["source_ref_id"])
            if source_ref_id != _index.collection_ref:
                raise ValueError(
                    f"Authority navigation collection_ref mismatch for {_index.index_key}: "
                    f"declared={_index.collection_ref}, target={source_ref_id}"
                )

        def resolve_target(
            target_ref: str,
            _load_target_resolver=load_target_resolver,
        ) -> Mapping[str, Any]:
            return _evidence_navigation_target(
                target_ref, load_target_resolver=_load_target_resolver
            )

        registry.register(
            index,
            resolver=resolve_target,
            search_strategy=lexical_material_decision_search,
            target_validator=validate_target,
        )
    return registry


def create_authority_navigation_tools(
    report: AuthorityInvestigationReport,
    *,
    indexes: Sequence[InvestigationKeyIndex],
    evidence_unit_ids: Mapping[str, str] | None = None,
    load_target_resolver: LoadTargetResolver | None = None,
):
    registry = build_authority_key_index_registry(
        report,
        indexes=indexes,
        evidence_unit_ids=evidence_unit_ids,
        load_target_resolver=load_target_resolver,
    )
    return create_key_index_tools(registry)
