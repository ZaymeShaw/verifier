from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Sequence

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


@dataclass
class SequenceOutput:
    variadic: tuple[str, ...]
    fixed: tuple[str, int]
    abstract: Sequence[str]


@dataclass
class Pep604UnionOutput:
    required_id: str
    optional_list: list[str] | None = None
    optional_mapping: dict[str, int] | None = None
    optional_nested: "Pep604UnionOutput | None" = None


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


def test_tuple_and_sequence_render_as_json_arrays_and_validate_items():
    spec = StructuredOutputSpec.from_dataclass(SequenceOutput)
    properties = spec.json_schema()["properties"]

    assert properties["variadic"] == {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
    }
    assert properties["fixed"] == {
        "type": "array",
        "items": [
            {"type": "string", "minLength": 1},
            {"type": "integer"},
        ],
        "minItems": 2,
        "maxItems": 2,
    }
    assert properties["abstract"] == {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
    }

    validator = SchemaValidator(spec)
    valid = {
        "variadic": ["a", "b"],
        "fixed": ["name", 2],
        "abstract": ["x"],
    }
    assert validator.validate(valid) == []
    assert "期望 array" in " ".join(validator.validate({**valid, "variadic": "ab"}))
    assert "长度 2" in " ".join(validator.validate({**valid, "fixed": ["name"]}))
    assert "[1]" in " ".join(validator.validate({**valid, "fixed": ["name", "2"]}))
    assert "期望 array" in " ".join(validator.validate({**valid, "abstract": {"0": "x"}}))


def test_pep604_union_annotations_render_constrained_schema_not_empty():
    """CG-ENG-001：Python 3.9 下 X | None（含泛型与前向引用）不得静默退化为 {}。"""
    spec = StructuredOutputSpec.from_dataclass(Pep604UnionOutput)
    properties = spec.json_schema()["properties"]

    assert properties["required_id"]["type"] == "string"
    assert properties["optional_list"]["type"] == ["array", "null"]
    assert properties["optional_mapping"]["type"] == ["object", "null"]
    assert properties["optional_nested"] != {}


def test_unresolvable_annotation_fails_loudly_instead_of_silent_empty():
    """CG-ENG-001：无法解析的注解必须 fail-loud，不能把整个 schema 静默降级。"""

    @dataclass
    class UnresolvableOutput:
        x: "MissingTypeInThisModule"

    with pytest.raises(ValueError, match="无法解析"):
        StructuredOutputSpec.from_dataclass(UnresolvableOutput).json_schema()


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
    # 新 Judge LLM 协议不再暴露旧 Authority 投影或模型自报置信度。
    assert "authority_analysis_ids" not in defs["JudgeBusinessExpectationOutput"]["properties"]
    assert "confidence" not in defs["JudgeFulfillmentAssessmentOutput"]["properties"]
    assert "authority_tool_call_ids" in defs["JudgeFulfillmentAssessmentOutput"]["properties"]


def test_judge_boundary_accepts_null_but_still_rejects_non_object():
    """boundary 是 write-only 备注，模型对空表述会写 null；按非 Optional Dict 判定会整段阻断并重跑。

    允许 null（运行时归一为 {}），但数组这类真错仍要拦。
    """
    spec = _build_judge_output_spec(True, project_id="llm_probe", has_reference=True)
    assert spec.json_schema()["$defs"]["JudgeBusinessExpectationOutput"]["properties"]["boundary"] == {
        "type": ["object", "null"],
    }

    def output(boundary):
        return {
            "business_expectations": [
                {"expectation_id": "e1", "blocking": True, "boundary": boundary}
            ],
            "reasoning_summary": "判断依据",
        }

    enforce_output(output(None), spec, caller="judge")
    enforce_output(output({"note": "备注"}), spec, caller="judge")
    enforce_output(
        {
            "business_expectations": [{"expectation_id": "e1", "blocking": True}],
            "reasoning_summary": "判断依据",
        },
        spec,
        caller="judge",
    )
    with pytest.raises(ValueError, match="boundary"):
        enforce_output(output([]), spec, caller="judge")


def test_live_schema_observation_allows_projection_but_keeps_type_and_extra_checks():
    from impl.projects.client_search.live_schema import check

    projection = {
        "query": "中银保信",
        "conditions": [],
        "robot_text": "未识别到明确查询条件",
        "query_logic": "AND",
        "intent_summary": "未识别到明确查询条件",
    }

    assert check.output(projection) is False
    assert check.observation(projection) is True
    assert check.observation({**projection, "conditions": "not-a-list"}) is False
    assert check.observation({**projection, "unknown_transport_field": 1}) is False


def test_authority_output_schemas_render_constrained_not_empty():
    """CG-ENG-001：真实 Authority 输出契约在 Python 3.9 下不得有字段退化为 {}。"""
    from impl.core.schema.authority import AuthorityRequest, AuthorityResolution

    for dc in (AuthorityRequest, AuthorityResolution):
        schema = StructuredOutputSpec.from_dataclass(dc).json_schema()
        assert set(schema["properties"]) >= {"decision_question"} if dc is AuthorityRequest else set(schema["properties"]) >= {"status", "statement", "reason"}
        for prop in schema["properties"].values():
            assert prop != {}


def test_required_string_can_declare_empty_as_a_legal_value():
    @dataclass
    class EmptyMeansAbsent:
        match: str = field(metadata={'allow_empty': True, 'description': 'Empty means no event'})
        name: str
    spec = StructuredOutputSpec.from_dataclass(EmptyMeansAbsent)
    schema = spec.json_schema()
    assert set(schema['required']) == {'match', 'name'}
    assert schema['properties']['match'] == {'type': 'string', 'minLength': 0, 'description': 'Empty means no event'}
    assert schema['properties']['name']['minLength'] == 1
    enforce_output({'match': '', 'name': 'event'}, spec, caller='test')
    with pytest.raises(ValueError, match='match'):
        enforce_output({'name': 'event'}, spec, caller='test')
    with pytest.raises(ValueError, match='match'):
        enforce_output({'match': None, 'name': 'event'}, spec, caller='test')
    # A caller requiring actual content still wins over the field's base schema.
    strict = StructuredOutputSpec.from_dataclass(EmptyMeansAbsent, required_nonempty=['match'])
    assert strict.json_schema()['properties']['match']['minLength'] == 1
    with pytest.raises(ValueError, match='非空'):
        enforce_output({'match': '', 'name': 'event'}, strict, caller='test')
