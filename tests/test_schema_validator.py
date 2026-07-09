from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from impl.core.judge import _build_judge_output_spec
from impl.core.schema import AttributeLLMOutput
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


def test_attribute_llm_schema_expands_expectation_attribution_items():
    spec = StructuredOutputSpec.from_dataclass(
        AttributeLLMOutput,
        required_nonempty=["expectation_attributions", "root_cause_hypothesis"],
    )

    schema = spec.json_schema()

    expectation_schema = schema["$defs"]["ExpectationAttribution"]
    assert expectation_schema["type"] == "object"
    assert set(expectation_schema["properties"]) == {
        "expectation_id",
        "fulfillment_status",
        "suspected_locations",
        "root_cause_hypothesis",
        "evidence",
    }
    assert set(expectation_schema["required"]) == {"expectation_id", "fulfillment_status"}


def test_structured_output_rejects_extra_fields():
    spec = StructuredOutputSpec.from_dataclass(
        AttributeLLMOutput,
        required_nonempty=["expectation_attributions", "root_cause_hypothesis"],
    )

    try:
        enforce_output(
            {
                "expectation_attributions": [
                    {
                        "expectation_id": "子女性别为男性",
                        "fulfillment_status": "not_fulfilled",
                        "attributed_to": "client_search_parse",
                    }
                ],
                "root_cause_hypothesis": "缺失 familyInfo.familyclientsex=男",
            },
            spec,
            caller="attribute",
        )
    except ValueError as exc:
        assert "expectation_attributions.[0].额外字段不允许：attributed_to" in str(exc)
    else:
        raise AssertionError("extra attribute fields should be rejected")


def test_judge_schema_defs_are_not_self_embedded():
    schema = _build_judge_output_spec(True, project_id="client_search", has_reference=False).json_schema()

    defs = schema["$defs"]
    assert "$defs" not in defs["BusinessExpectation"]
    assert "$defs" not in defs["FulfillmentAssessment"]
    assert "$defs" not in defs["GapItem"]
    assert defs["BusinessExpectation"]["type"] == "object"
    assert defs["FulfillmentAssessment"]["type"] == "object"
    assert defs["GapItem"]["type"] == "object"
