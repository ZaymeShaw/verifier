"""Authorized sufficiency mouth for the draft judge.

Two questions stay apart:

    Q1  Field standard. Does this delivered value support its own dimension?
    Q2  Sufficiency. Is there enough evidence the user wanted this dimension
        and that dimension was fully delivered?

This module only speaks when the authorized sufficiency test hits.
The test is sufficient, not necessary. Missing it is inherit, not failure.

This round's only authorized sufficiency test:

    exactly one delivered field
    and its value is the whole request
    and that field has an authorized standard (name or id)

Then Q1 decides fulfilled / not_fulfilled.

This is not a name-type state machine. It does not look at leftover text,
speech particles, pack roles, or set-A projections.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Optional

import yaml

from impl.core.judge import _derive_overall_status
from impl.core.schema import (
    BusinessExpectation,
    FulfillmentAssessment,
    JudgeResult,
    ProjectSpec,
    RunTrace,
    to_dict,
    trace_extracted_output,
)
from impl.core.summary import summary_from_fulfillment

_CJK_NAME = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
_NAME_FIELD = "searchClientName"
_ID_FIELDS = frozenset({"clientNo", "polNo"})
_EXPECTATION_ID = "这一维已按标准交齐"
_PIPE = re.compile(r"\|")


@dataclass(frozen=True)
class FieldStandards:
    surnames: frozenset[str]
    compounds: tuple[str, ...]
    blacklist: frozenset[str]
    suffixes: tuple[str, ...]
    products: frozenset[str]


@dataclass(frozen=True)
class Decision:
    status: Optional[str]
    reason: str
    query: str
    field: str = ""
    value: str = ""
    dimension: str = ""

    @property
    def speaks(self) -> bool:
        return self.status in {"fulfilled", "not_fulfilled"}


def request_text(trace: RunTrace) -> str:
    """One request string. Never join keys."""
    for source in (trace.normalized_request, trace.input):
        if not isinstance(source, dict):
            continue
        for key in ("user_text", "query"):
            value = source.get(key)
            if value:
                return str(value).strip()
    return ""


def delivered_pairs(trace: RunTrace) -> Optional[list[tuple[str, str]]]:
    conditions = trace_extracted_output(trace).get("conditions")
    if not isinstance(conditions, list):
        return None
    pairs: list[tuple[str, str]] = []
    for item in conditions:
        if not isinstance(item, dict):
            return None
        field = str(item.get("field") or "").strip()
        value = item.get("value")
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                return None
            value = value[0]
        if isinstance(value, dict) or value is None:
            return None
        text = str(value).strip()
        if not field or not text:
            return None
        pairs.append((field, text))
    return pairs


def _split_pipe(raw: Any) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    return [part for part in _PIPE.split(text) if part]


def _enum_members(path: str) -> frozenset[str]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    values: list[Any] = []
    if isinstance(payload, dict):
        for node in payload.values():
            if isinstance(node, dict):
                values.extend(node.get("values") or node.get("enums") or [])
            elif isinstance(node, list):
                values.extend(node)
    elif isinstance(payload, list):
        values.extend(payload)
    return frozenset(str(item).strip() for item in values if str(item).strip())


@lru_cache(maxsize=8)
def _cached_standards(
    mapping_path: str,
    mapping_mtime: int,
    mapping_size: int,
    abbr_path: str,
    abbr_mtime: int,
    abbr_size: int,
    full_path: str,
    full_mtime: int,
    full_size: int,
) -> FieldStandards:
    del mapping_mtime, mapping_size, abbr_mtime, abbr_size, full_mtime, full_size
    payload = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8")) or {}
    block = payload.get("name_candidate") if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        raise ValueError(f"name_candidate missing in {mapping_path}")
    products = set(_enum_members(abbr_path))
    products.update(_enum_members(full_path))
    return FieldStandards(
        surnames=frozenset(_split_pipe(block.get("common_surnames"))),
        compounds=tuple(_split_pipe(block.get("compound_surnames"))),
        blacklist=frozenset(_split_pipe(block.get("business_blacklist"))),
        suffixes=tuple(_split_pipe(block.get("business_suffixes"))),
        products=frozenset(products),
    )


def load_field_standards(spec: ProjectSpec) -> FieldStandards:
    mapping = Path(spec.source_path("field_definitions")).with_name(
        "field_mapping_args.yaml"
    )
    abbr = Path(spec.source_path("abbrname_enums"))
    full = Path(spec.source_path("planfullname_enums"))
    for path, label in (
        (mapping, "field_mapping_args.yaml"),
        (abbr, "abbrname_enums"),
        (full, "planfullname_enums"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    mapping_stat = mapping.stat()
    abbr_stat = abbr.stat()
    full_stat = full.stat()
    return _cached_standards(
        str(mapping.resolve()),
        mapping_stat.st_mtime_ns,
        mapping_stat.st_size,
        str(abbr.resolve()),
        abbr_stat.st_mtime_ns,
        abbr_stat.st_size,
        str(full.resolve()),
        full_stat.st_mtime_ns,
        full_stat.st_size,
    )


def name_standard_passes(value: str, standards: FieldStandards) -> bool:
    text = value.strip()
    if not _CJK_NAME.fullmatch(text):
        return False
    if text in standards.blacklist:
        return False
    if any(text.endswith(suffix) for suffix in standards.suffixes):
        return False
    if text in standards.products:
        return False
    for compound in standards.compounds:
        if text.startswith(compound):
            return len(text) >= len(compound) + 1
    return text[0] in standards.surnames


def field_standard(
    field: str,
    value: str,
    standards: FieldStandards,
) -> Optional[tuple[str, bool]]:
    """Q1. None = this field is outside the mouth."""
    if field == _NAME_FIELD:
        return ("name", name_standard_passes(value, standards))
    if field in _ID_FIELDS:
        return ("id", bool(value.strip()))
    return None


def decide(
    query: str,
    pairs: Optional[list[tuple[str, str]]],
    standards: FieldStandards,
) -> Decision:
    query = str(query or "").strip()
    if not query:
        return Decision(None, "empty_query", query)
    if pairs is None:
        return Decision(None, "pairs_unreadable", query)
    if len(pairs) != 1:
        return Decision(None, "not_single_field" if pairs else "no_live", query)
    field, value = pairs[0]
    if value != query:
        return Decision(None, "value_not_whole_query", query, field, value)
    judged = field_standard(field, value, standards)
    if judged is None:
        return Decision(None, "field_not_authorized", query, field, value)
    dimension, passed = judged
    if passed:
        return Decision("fulfilled", f"sufficient_{dimension}", query, field, value, dimension)
    return Decision("not_fulfilled", f"{dimension}_standard_fail", query, field, value, dimension)


def decide_from_trace(spec: ProjectSpec, trace: RunTrace) -> Decision:
    return decide(request_text(trace), delivered_pairs(trace), load_field_standards(spec))


def _render_result(trace: RunTrace, decision: Decision) -> JudgeResult:
    status = decision.status or "not_evaluable"
    expected = (
        f"按{decision.dimension or '该'}维交齐：{decision.value or decision.query}"
    )
    actual = (
        f"{decision.field}={decision.value}"
        if decision.field
        else "未交出可核对该维的条件"
    )
    result = JudgeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        business_expectations=[
            BusinessExpectation(
                expectation_id=_EXPECTATION_ID,
                blocking=True,
                downstream_consumer="客户搜索下游",
                user_intent=decision.query,
                expected_outcome=expected,
                acceptance_criteria=[
                    "用户要的就是这一维",
                    "这一维已经按该维已授权标准交齐",
                ],
                priority="high",
            )
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id=_EXPECTATION_ID,
                status=status,
                expected_evidence=[expected],
                actual_evidence=[actual, decision.reason],
            )
        ],
        evidence=[{
            "source": "field_sufficiency",
            "reason": decision.reason,
            "field": decision.field,
            "value": decision.value,
            "dimension": decision.dimension,
        }],
        reasoning_summary=(
            "用户要的就是这一维，并且交出来的值已经按该维标准交齐。"
            if status == "fulfilled"
            else "用户要的就是这一维，但交出来的值撑不住该维标准。"
        ),
        actual=trace.extracted_output,
    )
    derived = _derive_overall_status(
        result.business_expectations, result.fulfillment_assessments
    )
    result.overall_fulfillment = {
        "status": derived,
        "assessment_count": len(result.fulfillment_assessments),
        "blocking_expectations": [_EXPECTATION_ID],
    }
    result.summary = summary_from_fulfillment(to_dict(result))
    return result


def sufficiency_hint(spec: ProjectSpec, trace: RunTrace) -> Optional[dict[str, Any]]:
    """Business-semantic mouth becomes a prompt hint, not a status override."""
    decision = decide_from_trace(spec, trace)
    if not decision.speaks:
        return None
    return {
        "source": "field_sufficiency.hint",
        "reason": decision.reason,
        "field": decision.field,
        "value": decision.value,
        "dimension": decision.dimension,
        "suggested_status": decision.status,
        "note": "待核对提示，不是判定。最终 status 由 Judge 给出。",
    }


def result_if_speaks(spec: ProjectSpec, trace: RunTrace) -> Optional[JudgeResult]:
    # fulfilled.md §9 任务4：业务语义预判不得绕过 LLM 直接写 F/NF。
    del spec, trace
    return None


def apply_last_word(
    spec: ProjectSpec,
    trace: RunTrace,
    result: JudgeResult,
) -> JudgeResult:
    # 保留函数位：协议级硬路径（输出不可解析等）不在本模块。
    del spec, trace
    return result
