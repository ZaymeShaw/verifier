from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from impl.core.schema_validator import SchemaValidator
from impl.core.structured_output import StructuredOutputSpec


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
