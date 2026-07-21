from __future__ import annotations

from dataclasses import dataclass, replace

from impl.core.config import get_llm_config
from impl.core.llm_client import LlmClient, extract_json, _select_schema_matching_object
from impl.core.judge import _build_judge_output_spec
from impl.core.schema.judge import JudgeLLMOutput
from impl.core.structured_output import StructuredOutputSpec, enforce_output, render_output_constraint


def test_extract_json_parses_plain_and_fenced_json():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_repairs_unescaped_quotes_inside_string_values():
    bad = '```json\n{"description": "用户口语"重疾险"应映射"}\n```'

    assert extract_json(bad) == {"description": "用户口语\"重疾险\"应映射"}


def test_repaired_judge_output_still_passes_the_strict_judge_schema():
    raw = (
        '{"business_expectations":[{"expectation_id":"儿子关系",'
        '"blocking":true,"user_intent":"用户查询"儿子生日""}],'
        '"fulfillment_assessments":[{"expectation_id":"儿子关系",'
        '"status":"fulfilled"}],"reasoning_summary":"条件满足"}'
    )
    spec = _build_judge_output_spec(
        has_actual=True,
        project_id="client_search",
        has_reference=True,
    )

    repaired = extract_json(raw)
    enforce_output(repaired, spec, caller="judge")

    assert repaired["business_expectations"][0]["user_intent"] == '用户查询"儿子生日"'


def test_render_output_constraint_requires_json_only_output():
    spec = StructuredOutputSpec.from_dataclass(
        JudgeLLMOutput,
        required_nonempty=["business_expectations", "overall_fulfillment", "reasoning_summary"],
    )

    prompt = render_output_constraint(spec)

    assert "不要使用 ```json 代码块" in prompt
    assert "首字符必须是 `{`" in prompt
    assert "末字符必须是 `}`" in prompt
    assert "未转义英文双引号" in prompt


@dataclass
class _InvestigationOutput:
    investigation_summary: str


def test_complete_json_classifies_agno_error_before_json_parsing(monkeypatch):
    class Result:
        content = ""
        status = type("Status", (), {"value": "ERROR"})()
        metrics = None

        def to_dict(self):
            return {"content": "", "status": "ERROR", "model_provider": "DeepSeek"}

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, _user):
            return Result()

    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", lambda **_kwargs: object())
    monkeypatch.setattr("impl.core.llm_client._track_context", lambda *_args, **_kwargs: None)

    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    result = client.complete_json(
        "system",
        "user",
        output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert result["error"] == "llm_request_failed"
    assert "status ERROR" in result["raw_text"]
    assert result["raw_model_response"]["status"] == "ERROR"


def test_schema_matching_object_ignores_leading_tool_span_and_repaired_list():
    text = (
        '匹配位置 [10, 14]，结论如下：\n'
        '{"investigation_summary":"当前输入命中 homepage rule。"}'
    )
    repaired = extract_json(text)

    selected = _select_schema_matching_object(
        text,
        repaired,
        StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert selected == {"investigation_summary": "当前输入命中 homepage rule。"}


def test_schema_matching_object_can_recover_from_top_level_list_without_repairing_fields():
    text = '[[10, 14], {"investigation_summary":"当前输入命中 homepage rule。"}]'

    selected = _select_schema_matching_object(
        text,
        extract_json(text),
        StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert selected == {"investigation_summary": "当前输入命中 homepage rule。"}


def test_schema_matching_object_does_not_accept_wrong_embedded_shape():
    selected = _select_schema_matching_object(
        '说明 {"summary":"字段名错误"}',
        {"summary": "字段名错误"},
        StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert selected == {"summary": "字段名错误"}
