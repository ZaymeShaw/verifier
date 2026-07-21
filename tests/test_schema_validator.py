from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pytest

from impl.core.judge import _build_judge_output_spec
from impl.core.schema import AttributeLLMOutput, MockContinueDecision
from impl.core.schema_validator import SchemaValidator
from impl.core.structured_output import StructuredOutputSpec, enforce_output


@dataclass
class DemoOutput:
    required_id: str
    nullable_required: Optional[str]
    optional_text: str = ""
    optional_none: Optional[str] = None
    optional_flag: bool = False
    optional_count: int = 0
    optional_items: list = field(default_factory=list)


def test_json_schema_required_uses_default_to_control_omission():
    spec = StructuredOutputSpec.from_dataclass(DemoOutput)

    schema = spec.json_schema()

    assert set(schema["required"]) == {"required_id", "nullable_required"}
    assert schema["properties"]["nullable_required"]["type"] == ["string", "null"]
    assert "optional_text" not in schema["required"]
    assert "optional_none" not in schema["required"]
    assert "optional_flag" not in schema["required"]
    assert "optional_count" not in schema["required"]
    assert "optional_items" not in schema["required"]


def test_validator_required_matches_json_schema_required():
    spec = StructuredOutputSpec.from_dataclass(DemoOutput)
    validator = SchemaValidator(spec)

    errors = validator.validate({"required_id": "id"}, strict=True, allow_extra=True)

    assert errors == ["必填字段缺失：nullable_required"]


def test_required_nonempty_adds_scene_required_and_nonempty_constraint():
    spec = StructuredOutputSpec.from_dataclass(
        DemoOutput,
        required_nonempty=["optional_text"],
    )
    validator = SchemaValidator(spec)

    assert set(spec.json_schema()["required"]) == {
        "required_id",
        "nullable_required",
        "optional_text",
    }

    missing_errors = validator.validate(
        {"required_id": "id", "nullable_required": None},
        strict=True,
        allow_extra=True,
    )
    assert missing_errors == ["必填字段缺失：optional_text"]

    empty_errors = validator.validate(
        {"required_id": "id", "nullable_required": None, "optional_text": ""},
        strict=True,
        allow_extra=True,
    )
    assert empty_errors == ["字段必须非空但产出为空：optional_text"]

    assert validator.validate(
        {"required_id": "id", "nullable_required": None, "optional_text": "note"},
        strict=True,
        allow_extra=True,
    ) == []


def test_literal_fields_render_enum_schema_and_validate_exact_values():
    spec = StructuredOutputSpec.from_dataclass(MockContinueDecision)
    schema = spec.json_schema()

    assert schema["properties"]["action"] == {
        "type": "string",
        "enum": ["continue", "stop"],
    }
    assert schema["properties"]["stop_reason"] == {
        "type": "string",
        "enum": [
            "",
            "goal_satisfied",
            "user_abandons",
            "perceived_no_progress",
        ],
    }
    assert schema["required"] == ["action"]

    validator = SchemaValidator(spec)
    assert validator.validate({"action": "continue"}) == []
    assert validator.validate(
        {"action": "stop", "stop_reason": "goal_satisfied"}
    ) == []

    invalid_action_errors = validator.validate({"action": "finish"})
    assert len(invalid_action_errors) == 1
    assert "字段类型不匹配：action" in invalid_action_errors[0]
    assert "continue" in invalid_action_errors[0]
    assert "stop" in invalid_action_errors[0]

    null_action_errors = validator.validate({"action": None})
    assert len(null_action_errors) == 1
    assert "字段类型不匹配：action" in null_action_errors[0]

    with pytest.raises(ValueError, match="字段类型不匹配：action"):
        enforce_output({"action": {}, "stop_reason": {}}, spec, caller="mock_agent")


@dataclass
class MixedLiteralOutput:
    value: Literal["auto", 1, False, None]


def test_literal_schema_preserves_mixed_json_types_and_none():
    spec = StructuredOutputSpec.from_dataclass(MixedLiteralOutput)

    assert spec.json_schema()["properties"]["value"] == {
        "type": ["string", "integer", "boolean", "null"],
        "enum": ["auto", 1, False, None],
    }

    validator = SchemaValidator(spec)
    assert validator.validate({"value": "auto"}) == []
    assert validator.validate({"value": 1}) == []
    assert validator.validate({"value": False}) == []
    assert validator.validate({"value": None}) == []
    assert validator.validate({"value": True})


@dataclass
class OptionalLiteralOutput:
    mode: Optional[Literal["auto", "manual"]]


def test_optional_literal_schema_and_validator_allow_declared_null_only():
    spec = StructuredOutputSpec.from_dataclass(OptionalLiteralOutput)

    assert spec.json_schema()["properties"]["mode"] == {
        "type": ["string", "null"],
        "enum": ["auto", "manual", None],
    }

    validator = SchemaValidator(spec)
    assert validator.validate({"mode": "auto"}) == []
    assert validator.validate({"mode": None}) == []
    assert validator.validate({"mode": "other"})


def test_non_nullable_primitive_rejects_json_null():
    spec = StructuredOutputSpec.from_dataclass(DemoOutput)

    errors = SchemaValidator(spec).validate(
        {"required_id": None, "nullable_required": None}
    )

    assert len(errors) == 1
    assert "字段类型不匹配：required_id" in errors[0]


def test_attribute_llm_schema_expands_finding_and_evidence_items():
    spec = StructuredOutputSpec.from_dataclass(AttributeLLMOutput)

    schema = spec.json_schema()

    finding_schema = schema["$defs"]["AttributeFindingOutput"]
    assert finding_schema["type"] == "object"
    assert set(finding_schema["properties"]) == {"finding_id", "affected_expectation_ids", "conclusion", "evidence"}
    assert set(finding_schema["required"]) == {"finding_id"}
    evidence_schema = schema["$defs"]["AttributeEvidenceSelection"]
    assert set(evidence_schema["properties"]) == {"context_unit_id", "reason"}


def test_structured_output_rejects_extra_fields():
    spec = StructuredOutputSpec.from_dataclass(AttributeLLMOutput)

    try:
        enforce_output(
            {
            "findings": [
                {
                    "finding_id": "finding-1",
                    "attributed_to": "client_search_parse",
                }
            ],
            "unresolved_reason": "",
            },
            spec,
            caller="attribute",
        )
    except ValueError as exc:
        assert "findings.[0].额外字段不允许：attributed_to" in str(exc)
    else:
        raise AssertionError("extra attribute fields should be rejected")


def test_judge_schema_defs_are_not_self_embedded():
    schema = _build_judge_output_spec(True, project_id="client_search", has_reference=False).json_schema()

    defs = schema["$defs"]
    assert "$defs" not in defs["JudgeBusinessExpectationOutput"]
    assert "$defs" not in defs["JudgeFulfillmentAssessmentOutput"]
    assert "$defs" not in defs["GapItem"]
    assert defs["JudgeBusinessExpectationOutput"]["type"] == "object"
    assert defs["JudgeFulfillmentAssessmentOutput"]["type"] == "object"
    assert defs["GapItem"]["type"] == "object"
    assert "evidence_refs" not in defs["JudgeBusinessExpectationOutput"]["properties"]
    assert "evidence_refs" not in defs["JudgeFulfillmentAssessmentOutput"]["properties"]
