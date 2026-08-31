"""Strict JSON schema for the Judge investigation hand-off contract."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..portable_artifact import (
    project_artifact_repository_root,
    write_active_artifact,
    write_portable_export,
)
from ..path_contract import (
    LogicalPathRef,
    PathContractError,
    PathScope,
    parse_prefixed_path,
)


JUDGE_CONTRACT_SCHEMA_VERSION = 1

_ROOT_FIELDS = {
    "schema_version",
    "business_expectations",
    "live_boundary",
    "evaluation_dimensions",
    "mandatory_reviews",
}
_MANDATORY_REVIEW_FIELDS = {
    "honest_refusal_is_not_fulfilled",
    "three_states_exclusive",
    "no_escape",
}
_EXPECTATION_FIELDS = {"expectation_id", "user_role", "use_scenario", "desired_outcome"}
_BOUNDARY_FIELDS = {
    "live_role",
    "in_scope_responsibilities",
    "out_of_scope_responsibilities",
    "external_constraints",
}
_DIMENSION_FIELDS = {
    "dimension_id",
    "expectation_ids",
    "name",
    "evaluation_question",
    "fulfilled_when",
    "not_fulfilled_when",
    "not_evaluable_when",
}

# Only reject explicit protocol leakage. Semantic questions such as whether the user
# role is real remain part of the Harness hand-off review required by the spec.
_RESERVED_CONTENT = re.compile(
    r"(?i)(?:\bcase[_ -]?id\b|\bunseen[_ -]?case\b|\bexpected[_ -]?answer\b|"
    r"\bcurrent[_ -]?verdict\b|\bcandidate[_ -]?instruction\b|"
    r"\bnot_fulfilled\b|\bnot_evaluable\b|\bjudge_result\b)"
)


@dataclass(frozen=True)
class BusinessExpectation:
    expectation_id: str
    user_role: str
    use_scenario: str
    desired_outcome: str


@dataclass(frozen=True)
class LiveBoundary:
    live_role: str
    in_scope_responsibilities: tuple[str, ...]
    out_of_scope_responsibilities: tuple[str, ...]
    external_constraints: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationDimension:
    dimension_id: str
    expectation_ids: tuple[str, ...]
    name: str
    evaluation_question: str
    fulfilled_when: tuple[str, ...]
    not_fulfilled_when: tuple[str, ...]
    not_evaluable_when: tuple[str, ...]


@dataclass(frozen=True)
class MandatoryReviews:
    honest_refusal_is_not_fulfilled: str
    three_states_exclusive: str
    no_escape: str


@dataclass(frozen=True)
class JudgeInvestigationContract:
    business_expectations: tuple[BusinessExpectation, ...]
    live_boundary: LiveBoundary
    evaluation_dimensions: tuple[EvaluationDimension, ...]
    schema_version: int = JUDGE_CONTRACT_SCHEMA_VERSION
    mandatory_reviews: MandatoryReviews | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JudgeInvestigationContract":
        root = _object(value, "JudgeInvestigationContract", _ROOT_FIELDS)
        schema_version = _required_int(root, "schema_version", "JudgeInvestigationContract")
        expectations = tuple(
            _business_expectation(item, index)
            for index, item in enumerate(
                _required_list(root, "business_expectations", "JudgeInvestigationContract")
            )
        )
        boundary = _live_boundary(
            _object(
                _required(root, "live_boundary", "JudgeInvestigationContract"),
                "JudgeInvestigationContract.live_boundary",
                _BOUNDARY_FIELDS,
            )
        )
        dimensions = tuple(
            _evaluation_dimension(item, index)
            for index, item in enumerate(
                _required_list(root, "evaluation_dimensions", "JudgeInvestigationContract")
            )
        )
        reviews_raw = _object(
            _required(root, "mandatory_reviews", "JudgeInvestigationContract"),
            "JudgeInvestigationContract.mandatory_reviews",
            _MANDATORY_REVIEW_FIELDS,
        )
        reviews = MandatoryReviews(
            honest_refusal_is_not_fulfilled=_required_text_value(
                reviews_raw.get("honest_refusal_is_not_fulfilled"),
                "mandatory_reviews.honest_refusal_is_not_fulfilled",
            ),
            three_states_exclusive=_required_text_value(
                reviews_raw.get("three_states_exclusive"),
                "mandatory_reviews.three_states_exclusive",
            ),
            no_escape=_required_text_value(
                reviews_raw.get("no_escape"),
                "mandatory_reviews.no_escape",
            ),
        )
        return cls(expectations, boundary, dimensions, schema_version, reviews)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "business_expectations": [
                {
                    "expectation_id": item.expectation_id,
                    "user_role": item.user_role,
                    "use_scenario": item.use_scenario,
                    "desired_outcome": item.desired_outcome,
                }
                for item in self.business_expectations
            ],
            "live_boundary": {
                "live_role": self.live_boundary.live_role,
                "in_scope_responsibilities": list(self.live_boundary.in_scope_responsibilities),
                "out_of_scope_responsibilities": list(
                    self.live_boundary.out_of_scope_responsibilities
                ),
                "external_constraints": list(self.live_boundary.external_constraints),
            },
            "evaluation_dimensions": [
                {
                    "dimension_id": item.dimension_id,
                    "expectation_ids": list(item.expectation_ids),
                    "name": item.name,
                    "evaluation_question": item.evaluation_question,
                    "fulfilled_when": list(item.fulfilled_when),
                    "not_fulfilled_when": list(item.not_fulfilled_when),
                    "not_evaluable_when": list(item.not_evaluable_when),
                }
                for item in self.evaluation_dimensions
            ],
            "mandatory_reviews": {
                "honest_refusal_is_not_fulfilled": (
                    self.mandatory_reviews.honest_refusal_is_not_fulfilled
                    if self.mandatory_reviews
                    else ""
                ),
                "three_states_exclusive": (
                    self.mandatory_reviews.three_states_exclusive
                    if self.mandatory_reviews
                    else ""
                ),
                "no_escape": self.mandatory_reviews.no_escape if self.mandatory_reviews else "",
            },
        }


def load_judge_contract(path: Path) -> JudgeInvestigationContract:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return JudgeInvestigationContract.from_dict(raw)


def dump_judge_contract(contract: JudgeInvestigationContract, path: Path) -> None:
    target = Path(path)
    repository_root = project_artifact_repository_root(target)
    if repository_root is None:
        write_portable_export(target, contract.as_dict())
        return
    write_active_artifact(
        "judge_investigation_contract",
        target,
        contract.as_dict(),
        repository_root=repository_root,
    )


def project_judge_runtime_contract(contract: JudgeInvestigationContract) -> dict[str, Any]:
    """Project the investigation contract to the stable business contract used at runtime.

    Authority investigation is not copied into this contract (spec/alg/investigate-judge.md
    §3): runtime authority questions are resolved on demand via authority.resolve within the
    materialized evidence space (spec/alg/authority.md §5).
    """
    return contract.as_dict()


def validate_judge_contract(
    contract: JudgeInvestigationContract,
    *,
    evidence_ref_ids: set[str] | None = None,
    tool_requirement_ids: set[str] | None = None,
) -> None:
    if contract.schema_version != JUDGE_CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported JudgeInvestigationContract.schema_version: {contract.schema_version}"
        )
    if not contract.business_expectations:
        raise ValueError("JudgeInvestigationContract.business_expectations must be non-empty")
    if contract.mandatory_reviews is None:
        raise ValueError("JudgeInvestigationContract.mandatory_reviews is required")
    for field_name in (
        "honest_refusal_is_not_fulfilled",
        "three_states_exclusive",
        "no_escape",
    ):
        if not str(getattr(contract.mandatory_reviews, field_name) or "").strip():
            raise ValueError(f"JudgeInvestigationContract.mandatory_reviews.{field_name} is required")

    expectation_ids: set[str] = set()
    for expectation in contract.business_expectations:
        _required_text_value(expectation.expectation_id, "BusinessExpectation.expectation_id")
        if expectation.expectation_id in expectation_ids:
            raise ValueError(
                f"duplicate BusinessExpectation.expectation_id: {expectation.expectation_id}"
            )
        expectation_ids.add(expectation.expectation_id)
        for field_name in ("user_role", "use_scenario", "desired_outcome"):
            text = _required_text_value(
                getattr(expectation, field_name),
                f"BusinessExpectation.{field_name}: {expectation.expectation_id}",
            )
            _reject_reserved_content(text, f"BusinessExpectation.{field_name}")

    boundary = contract.live_boundary
    _required_text_value(boundary.live_role, "LiveBoundary.live_role")
    _require_nonempty_texts(
        boundary.in_scope_responsibilities,
        "LiveBoundary.in_scope_responsibilities",
    )
    _require_texts(
        boundary.out_of_scope_responsibilities,
        "LiveBoundary.out_of_scope_responsibilities",
    )
    _require_texts(boundary.external_constraints, "LiveBoundary.external_constraints")

    if not contract.evaluation_dimensions:
        raise ValueError("JudgeInvestigationContract.evaluation_dimensions must be non-empty")
    dimension_ids: set[str] = set()
    for dimension in contract.evaluation_dimensions:
        _required_text_value(dimension.dimension_id, "EvaluationDimension.dimension_id")
        if dimension.dimension_id in dimension_ids:
            raise ValueError(f"duplicate EvaluationDimension.dimension_id: {dimension.dimension_id}")
        dimension_ids.add(dimension.dimension_id)
        _required_text_value(dimension.name, f"EvaluationDimension.name: {dimension.dimension_id}")
        _required_text_value(
            dimension.evaluation_question,
            f"EvaluationDimension.evaluation_question: {dimension.dimension_id}",
        )
        if not dimension.expectation_ids:
            raise ValueError(
                f"EvaluationDimension must reference at least one expectation: {dimension.dimension_id}"
            )
        if len(set(dimension.expectation_ids)) != len(dimension.expectation_ids):
            raise ValueError(
                f"EvaluationDimension has duplicate expectation_ids: {dimension.dimension_id}"
            )
        unknown = sorted(set(dimension.expectation_ids) - expectation_ids)
        if unknown:
            raise ValueError(
                f"EvaluationDimension {dimension.dimension_id} references unknown expectation_id: "
                + ", ".join(unknown)
            )
        for field_name in ("fulfilled_when", "not_fulfilled_when", "not_evaluable_when"):
            values = getattr(dimension, field_name)
            _require_nonempty_texts(
                values, f"EvaluationDimension.{field_name}: {dimension.dimension_id}"
            )
            for text in values:
                _reject_reserved_content(text, f"EvaluationDimension.{field_name}")
        endpoints = {
            "fulfilled_when": {_normalized_condition(v) for v in dimension.fulfilled_when},
            "not_fulfilled_when": {
                _normalized_condition(v) for v in dimension.not_fulfilled_when
            },
            "not_evaluable_when": {
                _normalized_condition(v) for v in dimension.not_evaluable_when
            },
        }
        for left, right in (
            ("fulfilled_when", "not_fulfilled_when"),
            ("fulfilled_when", "not_evaluable_when"),
            ("not_fulfilled_when", "not_evaluable_when"),
        ):
            overlap = sorted(endpoints[left] & endpoints[right])
            if overlap:
                raise ValueError(
                    f"EvaluationDimension tri-state conditions overlap: {dimension.dimension_id}: "
                    f"{left}/{right}: {overlap[0]}"
                )

def _business_expectation(value: Any, index: int) -> BusinessExpectation:
    owner = f"business_expectations[{index}]"
    item = _object(value, owner, _EXPECTATION_FIELDS)
    return BusinessExpectation(
        _required_str(item, "expectation_id", owner),
        _required_str(item, "user_role", owner),
        _required_str(item, "use_scenario", owner),
        _required_str(item, "desired_outcome", owner),
    )


def _live_boundary(value: Mapping[str, Any]) -> LiveBoundary:
    owner = "live_boundary"
    return LiveBoundary(
        _required_str(value, "live_role", owner),
        _str_tuple(value, "in_scope_responsibilities", owner),
        _str_tuple(value, "out_of_scope_responsibilities", owner),
        _str_tuple(value, "external_constraints", owner),
    )


def _evaluation_dimension(value: Any, index: int) -> EvaluationDimension:
    owner = f"evaluation_dimensions[{index}]"
    item = _object(value, owner, _DIMENSION_FIELDS)
    return EvaluationDimension(
        _required_str(item, "dimension_id", owner),
        _str_tuple(item, "expectation_ids", owner),
        _required_str(item, "name", owner),
        _required_str(item, "evaluation_question", owner),
        _str_tuple(item, "fulfilled_when", owner),
        _str_tuple(item, "not_fulfilled_when", owner),
        _str_tuple(item, "not_evaluable_when", owner),
    )


def _object(value: Any, owner: str, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{owner} must be a JSON object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{owner} contains unknown field: {unknown[0]}")
    return value


def _required(value: Mapping[str, Any], key: str, owner: str) -> Any:
    if key not in value:
        raise ValueError(f"{owner}.{key} is required")
    return value[key]


def _required_int(value: Mapping[str, Any], key: str, owner: str) -> int:
    raw = _required(value, key, owner)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError(f"{owner}.{key} must be an integer")
    return raw


def _required_str(value: Mapping[str, Any], key: str, owner: str) -> str:
    raw = _required(value, key, owner)
    if not isinstance(raw, str):
        raise TypeError(f"{owner}.{key} must be a string")
    return raw


def _required_list(value: Mapping[str, Any], key: str, owner: str) -> Sequence[Any]:
    raw = _required(value, key, owner)
    if not isinstance(raw, list):
        raise TypeError(f"{owner}.{key} must be a JSON array")
    return raw


def _str_tuple(value: Mapping[str, Any], key: str, owner: str) -> tuple[str, ...]:
    raw = _required_list(value, key, owner)
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            raise TypeError(f"{owner}.{key}[{index}] must be a string")
    return tuple(raw)


def _required_text_value(value: str, owner: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} is required")
    return value.strip()


def _require_texts(values: tuple[str, ...], owner: str) -> None:
    if values is None:
        raise ValueError(f"{owner} is required")
    for index, item in enumerate(values):
        _required_text_value(item, f"{owner}[{index}]")


def _require_nonempty_texts(values: tuple[str, ...], owner: str) -> None:
    if not values:
        raise ValueError(f"{owner} must be non-empty")
    _require_texts(values, owner)


def _reject_reserved_content(text: str, owner: str) -> None:
    match = _RESERVED_CONTENT.search(text)
    if match:
        raise ValueError(f"{owner} contains forbidden case/verdict/instruction content: {match.group(0)}")


def _normalized_condition(value: str) -> str:
    return " ".join(value.casefold().split())


# ---------------------------------------------------------------------------
# AuthorityInvestigationReport: 调查阶段的权威调查报告
# spec/alg/investigate-authority-judge.md §8-15
# ---------------------------------------------------------------------------

AUTHORITY_REPORT_SCHEMA_VERSION = 2

_REPORT_FIELDS = {
    "schema_version",
    "report_id",
    "investigation_snapshot_id",
    "business_scope",
    "materials",
    "coverage_gaps",
}
_MATERIAL_FIELDS = {
    "source_ref_id",
    "source_location",
    "decisions",
    "related_to",
    "connections",
    "limitations",
}
_DECISION_FIELDS = {
    "conclusion_kind",
    "governs",
    "statement",
    "locator",
    "scenario",
    "conditions",
    # 可选显式担保档位（judge.md §6）：档位随"谁担保/担保多强"定；
    # 未声明时按 conclusion_kind（内容类型）缺省映射，结果与既有口径完全一致。
    "warrant_tier",
}
_CONNECTION_FIELDS = {
    "direction",
    "source_ref_id",
    "source_location",
    "locator",
    "relation",
    "effect",
}
_GAP_FIELDS = {
    "gap_id",
    "conclusion_kind",
    "governs",
    "conditions",
    "dimension_ids",
    "basis_source_ref_ids",
    "gap_reason",
    "required_evidence",
}

_VALID_CONCLUSION_KINDS = {
    "current_behavior",
    "normative_rule",
    "external_fact",
    # 边界代理（条件定位）：须项目登记信任模型，material-positioning.md §4/§5。
    "inlive_boundary",
}
_VALID_CONNECTION_DIRECTIONS = {"upstream", "downstream", "peer"}
_VALID_CONNECTION_RELATIONS = {
    "dependency",
    "derived_from",
    "validated_by",
    "supersedes",
    "conflicts_with",
}
# gap_id 项目内稳定且唯一：固定 slug，不得从 governs 文案临时生成。
_GAP_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
# 信任模型登记（material-positioning.md §5.2）：登记是 governs 含「信任模型」的
# normative_rule Decision；inlive_boundary Decision 的 conditions 必须带
# trust_model: 前缀回指登记。
_TRUST_MODEL_GOVERNS_MARKER = "信任模型"
_TRUST_MODEL_CONDITION_PREFIX = "trust_model:"
_AMORPHOUS_CONNECTION_EFFECT = re.compile(r"^\s*(?:相关|被使用|related|used)\s*$", re.IGNORECASE)


def _logical_path_ref(value: Any, *, field_path: str) -> LogicalPathRef:
    """Parse a LogicalPathRef from the report's structured JSON form.

    The frozen report JSON stores the full LogicalPathRef mapping (spec
    investigate-authority-judge.md §8). Compact ``scope:location`` strings and
    prefixed ``scope://location`` strings are tolerated so hand-written drafts
    and Markdown-rendered forms stay usable, but ``as_dict`` always persists
    the structured mapping.
    """
    if isinstance(value, Mapping):
        return LogicalPathRef.from_mapping(value, field_path=field_path)
    if not isinstance(value, str) or not value.strip():
        raise PathContractError(
            "PATH_TYPE_MISMATCH", field_path, "expected a LogicalPathRef mapping"
        )
    text = value.strip()
    if "://" in text:
        return LogicalPathRef.from_prefixed_path(
            parse_prefixed_path(
                text,
                field_path=field_path,
                allowed_scopes=tuple(PathScope),
            )
        )
    scope_text, sep, location = text.partition(":")
    if sep and scope_text in {item.value for item in PathScope} and location:
        return LogicalPathRef(PathScope(scope_text), location)
    raise PathContractError(
        "PATH_TYPE_MISMATCH",
        field_path,
        "source_location must be a LogicalPathRef mapping or a scope:location string",
    )


def _logical_path_ref_compact(ref: LogicalPathRef) -> str:
    """Compact ``scope:location`` key used for cross-checks and Markdown."""
    return f"{ref.location_scope.value}:{ref.location}"


@dataclass(frozen=True)
class MaterialDecision:
    """一份资料在某个结论种类、场景和条件下直接决定的唯一范围。

    ``warrant_tier`` 是可选的显式担保档位（judge.md §6）：证明力随
    "谁担保/担保多强"定，``conclusion_kind``（内容类型）只是缺省映射。
    未声明时（既有全部报告）证明力 = conclusion_kind，与既有口径逐位一致。
    """

    conclusion_kind: str
    governs: str
    statement: str
    locator: str
    scenario: str
    conditions: tuple[str, ...]
    warrant_tier: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MaterialDecision":
        root = _object(value, "MaterialDecision", _DECISION_FIELDS)
        return cls(
            conclusion_kind=_required_text_value(
                root["conclusion_kind"], "MaterialDecision.conclusion_kind"
            ),
            governs=_required_text_value(root["governs"], "MaterialDecision.governs"),
            statement=_required_text_value(root["statement"], "MaterialDecision.statement"),
            locator=_required_text_value(root["locator"], "MaterialDecision.locator"),
            scenario=_required_text_value(root["scenario"], "MaterialDecision.scenario"),
            conditions=_str_tuple(root, "conditions", "MaterialDecision"),
            warrant_tier=str(root.get("warrant_tier") or "").strip(),
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "conclusion_kind": self.conclusion_kind,
            "governs": self.governs,
            "statement": self.statement,
            "locator": self.locator,
            "scenario": self.scenario,
            "conditions": list(self.conditions),
        }
        # 未声明担保档位的既有报告序列化逐键不变（零迁移）。
        if self.warrant_tier:
            payload["warrant_tier"] = self.warrant_tier
        return payload


def decision_proof_power(decision: MaterialDecision) -> str:
    """证明力档位：显式担保档位优先，内容类型只是缺省映射（judge.md §6）。

    档位随"谁担保/担保多强"定，不由内容类型单独决定；无显式担保元数据时，
    缺省映射 = conclusion_kind 本身——与既有"内容类型即定义"的结果完全一致。
    """
    return decision.warrant_tier or decision.conclusion_kind


@dataclass(frozen=True)
class MaterialConnection:
    """资料与上游、下游或同级资料之间的实质业务连接。"""

    direction: str
    source_ref_id: str
    source_location: LogicalPathRef
    locator: str
    relation: str
    effect: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MaterialConnection":
        root = _object(value, "MaterialConnection", _CONNECTION_FIELDS)
        return cls(
            direction=_required_text_value(root["direction"], "MaterialConnection.direction"),
            source_ref_id=_required_text_value(
                root["source_ref_id"], "MaterialConnection.source_ref_id"
            ),
            source_location=_logical_path_ref(
                root["source_location"], field_path="MaterialConnection.source_location"
            ),
            locator=str(root.get("locator") or ""),
            relation=_required_text_value(root["relation"], "MaterialConnection.relation"),
            effect=_required_text_value(root["effect"], "MaterialConnection.effect"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "source_ref_id": self.source_ref_id,
            "source_location": dict(self.source_location.to_mapping()),
            "locator": self.locator,
            "relation": self.relation,
            "effect": self.effect,
        }


@dataclass(frozen=True)
class MaterialInvestigation:
    """对一份已登记资料完成的完整调查记录。"""

    source_ref_id: str
    source_location: LogicalPathRef
    decisions: tuple[MaterialDecision, ...]
    related_to: tuple[str, ...]
    connections: tuple[MaterialConnection, ...]
    limitations: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MaterialInvestigation":
        root = _object(value, "MaterialInvestigation", _MATERIAL_FIELDS)
        return cls(
            source_ref_id=_required_text_value(
                root["source_ref_id"], "MaterialInvestigation.source_ref_id"
            ),
            source_location=_logical_path_ref(
                root["source_location"], field_path="MaterialInvestigation.source_location"
            ),
            decisions=tuple(
                MaterialDecision.from_dict(item)
                for item in _required_list(root, "decisions", "MaterialInvestigation")
            ),
            related_to=_str_tuple(root, "related_to", "MaterialInvestigation"),
            connections=tuple(
                MaterialConnection.from_dict(item)
                for item in _required_list(root, "connections", "MaterialInvestigation")
            ),
            limitations=_str_tuple(root, "limitations", "MaterialInvestigation"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_ref_id": self.source_ref_id,
            "source_location": dict(self.source_location.to_mapping()),
            "decisions": [item.as_dict() for item in self.decisions],
            "related_to": list(self.related_to),
            "connections": [item.as_dict() for item in self.connections],
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class CoverageGap:
    """覆盖缺口：业务事项 × 条件缺少唯一决定资料，或重叠无法消解（确定性事实）。

    覆盖缺口不是结论对象：没有 resolved/unresolved 状态，不承载任何"问题→结论"
    配对；最终裁决由 Runtime 在证据空间内现场综合（spec/alg/investigate-authority-judge.md §11）。
    """

    gap_id: str
    conclusion_kind: str
    governs: str
    conditions: tuple[str, ...]
    dimension_ids: tuple[str, ...]
    basis_source_ref_ids: tuple[str, ...]
    gap_reason: str
    required_evidence: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageGap":
        root = _object(value, "CoverageGap", _GAP_FIELDS)
        return cls(
            gap_id=_required_text_value(root["gap_id"], "CoverageGap.gap_id"),
            conclusion_kind=_required_text_value(
                root["conclusion_kind"], "CoverageGap.conclusion_kind"
            ),
            governs=_required_text_value(root["governs"], "CoverageGap.governs"),
            conditions=_str_tuple(root, "conditions", "CoverageGap"),
            dimension_ids=_str_tuple(root, "dimension_ids", "CoverageGap"),
            basis_source_ref_ids=_str_tuple(root, "basis_source_ref_ids", "CoverageGap"),
            gap_reason=_required_text_value(root["gap_reason"], "CoverageGap.gap_reason"),
            required_evidence=_str_tuple(root, "required_evidence", "CoverageGap"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "conclusion_kind": self.conclusion_kind,
            "governs": self.governs,
            "conditions": list(self.conditions),
            "dimension_ids": list(self.dimension_ids),
            "basis_source_ref_ids": list(self.basis_source_ref_ids),
            "gap_reason": self.gap_reason,
            "required_evidence": list(self.required_evidence),
        }


@dataclass(frozen=True)
class AuthorityInvestigationReport:
    """调查阶段交付的结构化真相源。"""

    report_id: str
    investigation_snapshot_id: str
    business_scope: str
    materials: tuple[MaterialInvestigation, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    schema_version: int = AUTHORITY_REPORT_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorityInvestigationReport":
        root = _object(value, "AuthorityInvestigationReport", _REPORT_FIELDS)
        schema_version = _required_int(root, "schema_version", "AuthorityInvestigationReport")
        if schema_version != AUTHORITY_REPORT_SCHEMA_VERSION:
            raise ValueError(
                f"AuthorityInvestigationReport.schema_version must be "
                f"{AUTHORITY_REPORT_SCHEMA_VERSION}: {schema_version}"
            )
        return cls(
            report_id=_required_text_value(root["report_id"], "AuthorityInvestigationReport.report_id"),
            investigation_snapshot_id=_required_text_value(
                root["investigation_snapshot_id"],
                "AuthorityInvestigationReport.investigation_snapshot_id",
            ),
            business_scope=_required_text_value(
                root["business_scope"], "AuthorityInvestigationReport.business_scope"
            ),
            materials=tuple(
                MaterialInvestigation.from_dict(item)
                for item in _required_list(root, "materials", "AuthorityInvestigationReport")
            ),
            coverage_gaps=tuple(
                CoverageGap.from_dict(item)
                for item in _required_list(root, "coverage_gaps", "AuthorityInvestigationReport")
            ),
            schema_version=schema_version,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "investigation_snapshot_id": self.investigation_snapshot_id,
            "business_scope": self.business_scope,
            "materials": [item.as_dict() for item in self.materials],
            "coverage_gaps": [item.as_dict() for item in self.coverage_gaps],
        }


def load_authority_investigation_report(path: Path) -> AuthorityInvestigationReport:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return AuthorityInvestigationReport.from_dict(raw)


def dump_authority_investigation_report(report: AuthorityInvestigationReport, path: Path) -> None:
    target = Path(path)
    repository_root = project_artifact_repository_root(target)
    if repository_root is None:
        write_portable_export(target, report.as_dict())
        return
    write_active_artifact(
        "authority_investigation_report",
        target,
        report.as_dict(),
        repository_root=repository_root,
    )


def validate_authority_report(
    report: AuthorityInvestigationReport,
    *,
    evidence_locations: Mapping[str, str],
    dimension_ids: set[str],
) -> None:
    """冻结权威报告的确定性校验（spec/alg/investigate-authority-judge.md §14）。

    校验层只检查引用、边界和禁止项，不代替业务语义审查：资料与覆盖缺口是否
    足够由 Harness AI 与交接审查负责。
    """
    if not report.materials:
        raise ValueError("AuthorityInvestigationReport.materials must be non-empty")

    # 报告是导航摘要：不得包含 current Case actual、score、confidence、verdict。
    _reject_case_level_content(report.as_dict())

    material_locations: dict[str, str] = {}
    seen_materials: set[str] = set()
    decision_keys: set[tuple[str, str]] = set()
    has_inlive_boundary = False
    trust_model_registration: str | None = None
    for material in report.materials:
        if material.source_ref_id in seen_materials:
            raise ValueError(
                f"duplicate MaterialInvestigation.source_ref_id: {material.source_ref_id}"
            )
        seen_materials.add(material.source_ref_id)
        expected_location = evidence_locations.get(material.source_ref_id)
        if expected_location is None:
            raise ValueError(
                f"MaterialInvestigation.source_ref_id is not a registered EvidenceRef: "
                f"{material.source_ref_id}"
            )
        if _logical_path_ref_compact(material.source_location) != expected_location:
            raise ValueError(
                f"MaterialInvestigation.source_location for {material.source_ref_id} must "
                f"match the EvidenceRef location_ref: "
                f"{_logical_path_ref_compact(material.source_location)!r} != "
                f"{expected_location!r}"
            )
        location = _logical_path_ref_compact(material.source_location)
        if _is_report_artifact_location(location):
            raise ValueError(
                f"MaterialInvestigation.{material.source_ref_id} registers the authority "
                f"report artifact itself as a material; the report is a navigation summary, "
                f"not a business material (spec/alg/investigate-authority-judge.md §16)"
            )
        material_locations[material.source_ref_id] = location
        if not material.decisions:
            raise ValueError(
                f"MaterialInvestigation.decisions must be non-empty: {material.source_ref_id}"
            )
        for index, decision in enumerate(material.decisions):
            owner = f"MaterialInvestigation.{material.source_ref_id}.decisions[{index}]"
            if decision.conclusion_kind not in _VALID_CONCLUSION_KINDS:
                raise ValueError(f"{owner}.conclusion_kind is invalid: {decision.conclusion_kind}")
            if decision.warrant_tier and decision.warrant_tier not in _VALID_CONCLUSION_KINDS:
                raise ValueError(f"{owner}.warrant_tier is invalid: {decision.warrant_tier}")
            for field, value in (
                ("governs", decision.governs),
                ("statement", decision.statement),
                ("locator", decision.locator),
                ("scenario", decision.scenario),
            ):
                if not value:
                    raise ValueError(f"{owner}.{field} must be non-empty")
            decision_keys.add(
                (decision.conclusion_kind, _normalized_governs(decision.governs))
            )
            # 信任模型登记要求（material-positioning.md §5.2）：只要内容类型或
            # 显式担保档位任一为 inlive_boundary 即须回指登记——warrant_tier
            # 不得成为绕开边界代理登记的旁路。
            if "inlive_boundary" in {decision.conclusion_kind, decision_proof_power(decision)}:
                has_inlive_boundary = True
                if not any(
                    item.strip().startswith(_TRUST_MODEL_CONDITION_PREFIX)
                    for item in decision.conditions
                ):
                    raise ValueError(
                        f"{owner} is inlive_boundary but no condition references the "
                        f"registered trust model (expected a condition starting with "
                        f"{_TRUST_MODEL_CONDITION_PREFIX!r}; "
                        f"spec/alg/material-positioning.md §5.2)"
                    )
            if (
                decision_proof_power(decision) == "normative_rule"
                and _TRUST_MODEL_GOVERNS_MARKER in _normalized_governs(decision.governs)
            ):
                trust_model_registration = owner
        for connection in material.connections:
            conn_owner = (
                f"MaterialInvestigation.{material.source_ref_id}.connections"
                f"[{connection.source_ref_id}]"
            )
            if connection.direction not in _VALID_CONNECTION_DIRECTIONS:
                raise ValueError(f"{conn_owner}.direction is invalid: {connection.direction}")
            if connection.relation not in _VALID_CONNECTION_RELATIONS:
                raise ValueError(f"{conn_owner}.relation is invalid: {connection.relation}")
            if connection.source_ref_id not in evidence_locations:
                raise ValueError(
                    f"{conn_owner}.source_ref_id is not a registered EvidenceRef: "
                    f"{connection.source_ref_id}"
                )
            if (
                _logical_path_ref_compact(connection.source_location)
                != evidence_locations[connection.source_ref_id]
            ):
                raise ValueError(
                    f"{conn_owner}.source_location must match the EvidenceRef location_ref"
                )
            if not connection.effect.strip() or _AMORPHOUS_CONNECTION_EFFECT.match(
                connection.effect
            ):
                raise ValueError(
                    f"{conn_owner}.effect must state the actual business transfer, not only "
                    f"'related' or 'used'"
                )
            if connection.relation in {"derived_from", "validated_by"}:
                if not connection.locator:
                    raise ValueError(
                        f"{conn_owner} with relation={connection.relation} requires a locator"
                    )

    if has_inlive_boundary and trust_model_registration is None:
        raise ValueError(
            "report contains inlive_boundary decisions but no registered trust model: "
            "a normative_rule MaterialDecision whose governs states the 信任模型登记 "
            "is required (spec/alg/material-positioning.md §5.2)"
        )

    seen_gaps: set[str] = set()
    for gap in report.coverage_gaps:
        owner = f"CoverageGap[{gap.gap_id}]"
        if gap.gap_id in seen_gaps:
            raise ValueError(f"duplicate CoverageGap.gap_id: {gap.gap_id}")
        seen_gaps.add(gap.gap_id)
        if not _GAP_ID_PATTERN.fullmatch(gap.gap_id):
            raise ValueError(
                f"{owner}.gap_id must be a stable slug (lowercase words joined by '-'), "
                f"not generated from governs text"
            )
        if gap.conclusion_kind not in _VALID_CONCLUSION_KINDS:
            raise ValueError(f"{owner}.conclusion_kind is invalid: {gap.conclusion_kind}")
        if not gap.governs:
            raise ValueError(f"{owner}.governs must be non-empty")
        if not gap.gap_reason:
            raise ValueError(f"{owner}.gap_reason must be non-empty")
        if not gap.required_evidence:
            raise ValueError(f"{owner}.required_evidence must be non-empty")
        # 确定性覆盖检查：同一 conclusion_kind 下已有相同 governs 的 MaterialDecision
        # 时，该事项已被资料覆盖，不得再记缺口（§11.3）。
        if (gap.conclusion_kind, _normalized_governs(gap.governs)) in decision_keys:
            raise ValueError(
                f"{owner} overlaps an existing MaterialDecision with the same "
                f"conclusion_kind and governs; coverage exists, no gap may be recorded"
            )
        if gap.basis_source_ref_ids:
            unknown_basis = sorted(set(gap.basis_source_ref_ids) - set(evidence_locations))
            if unknown_basis:
                raise ValueError(
                    f"{owner}.basis_source_ref_ids reference unknown EvidenceRef: "
                    + ", ".join(unknown_basis)
                )
        else:
            raise ValueError(
                f"{owner}.basis_source_ref_ids must list the materials actually used that "
                f"still fail to cover the governs"
            )
        unknown_dimensions = sorted(set(gap.dimension_ids) - dimension_ids)
        if unknown_dimensions:
            raise ValueError(
                f"{owner}.dimension_ids reference unknown EvaluationDimension: "
                + ", ".join(unknown_dimensions)
            )
        # gap_reason 不得只复述 required_evidence（§14：必须说明已跟进方向与停止原因）。
        normalized_reason = _normalized_governs(gap.gap_reason)
        if all(
            _normalized_governs(item) and _normalized_governs(item) in normalized_reason
            for item in gap.required_evidence
        ) and normalized_reason in _normalized_governs(
            "；".join(gap.required_evidence)
        ):
            raise ValueError(
                f"{owner}.gap_reason must explain why the basis materials still fail to "
                f"cover the governs, not restate required_evidence"
            )


def _normalized_governs(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


_REPORT_ARTIFACT_LOCATIONS = (
    "authority-investigation-report.json",
    "authority-investigation-report.md",
)


def _is_report_artifact_location(location: str) -> bool:
    return any(location.endswith(suffix) for suffix in _REPORT_ARTIFACT_LOCATIONS)


_CASE_LEVEL_KEYS = frozenset(
    {
        "actual",
        "actual_output",
        "actual_evidence",
        "final_output",
        "score",
        "confidence",
        "verdict",
        "verdict_derivation",
    }
)


def _reject_case_level_content(value: Any) -> None:
    """报告不得包含 current Case actual、Comparator、score、confidence 或 verdict（§14）。"""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in _CASE_LEVEL_KEYS:
                raise ValueError(
                    f"AuthorityInvestigationReport must not contain case-level content: {key}"
                )
            _reject_case_level_content(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_case_level_content(item)


def render_authority_report_markdown(report: AuthorityInvestigationReport) -> str:
    """Deterministic Markdown rendering of the frozen report.

    The report is the navigation summary of the investigation: first every
    material with its direct decisions and connections, then the coverage gaps.
    The renderer never emits case-level actuals, comparator, score or verdict.
    """
    lines: list[str] = []
    lines.append(f"# Authority Investigation Report: {report.report_id}")
    lines.append("")
    lines.append(f"- report_id: `{report.report_id}`")
    lines.append(f"- investigation_snapshot_id: `{report.investigation_snapshot_id}`")
    lines.append(f"- business_scope: {report.business_scope}")
    lines.append("")
    lines.append("## Materials")
    lines.append("")
    for material in report.materials:
        lines.append(f"### {material.source_ref_id}")
        lines.append("")
        lines.append(
            f"- source_location: `{_logical_path_ref_compact(material.source_location)}`"
        )
        lines.append("")
        lines.append("#### Decisions（该资料在下列范围内直接决定）")
        lines.append("")
        for index, decision in enumerate(material.decisions, start=1):
            lines.append(f"{index}. **{decision.conclusion_kind}** — {decision.governs}")
            if decision.warrant_tier:
                lines.append(
                    f"   - warrant_tier: `{decision.warrant_tier}`"
                    f"（证明力以显式担保档位为准，conclusion_kind 仅为内容类型）"
                )
            lines.append(f"   - statement: {decision.statement}")
            lines.append(f"   - locator: `{decision.locator}`")
            lines.append(f"   - scenario: {decision.scenario}")
            if decision.conditions:
                lines.append(
                    "   - conditions: " + "; ".join(f"`{item}`" for item in decision.conditions)
                )
        if material.related_to:
            lines.append("")
            lines.append("#### Related（仅相关，不由该资料决定）")
            lines.append("")
            for item in material.related_to:
                lines.append(f"- {item}")
        if material.connections:
            lines.append("")
            lines.append("#### Connections")
            lines.append("")
            for connection in material.connections:
                locator = f" (`{connection.locator}`)" if connection.locator else ""
                lines.append(
                    f"- {connection.direction} → {connection.source_ref_id}"
                    f"{locator} [{connection.relation}]: {connection.effect}"
                )
        if material.limitations:
            lines.append("")
            lines.append("#### Limitations")
            lines.append("")
            for item in material.limitations:
                lines.append(f"- {item}")
        lines.append("")
    lines.append("## Coverage Gaps（业务事项 × 条件缺少唯一决定资料）")
    lines.append("")
    if not report.coverage_gaps:
        lines.append("- 无：调查范围内每个业务事项 × 条件均有唯一决定资料。")
        lines.append("")
    for gap in report.coverage_gaps:
        lines.append(f"### {gap.gap_id}")
        lines.append("")
        lines.append(f"- conclusion_kind: `{gap.conclusion_kind}`")
        lines.append(f"- governs: {gap.governs}")
        if gap.conditions:
            lines.append(
                "- conditions: " + "; ".join(f"`{item}`" for item in gap.conditions)
            )
        if gap.dimension_ids:
            lines.append(
                "- dimension_ids: " + ", ".join(f"`{item}`" for item in gap.dimension_ids)
            )
        lines.append(
            "- basis_source_ref_ids: "
            + ", ".join(f"`{item}`" for item in gap.basis_source_ref_ids)
        )
        lines.append(f"- gap_reason: {gap.gap_reason}")
        lines.append("- required_evidence:")
        for item in gap.required_evidence:
            lines.append(f"  - {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
