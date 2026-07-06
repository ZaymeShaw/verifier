from __future__ import annotations

import pytest

from impl.core.llm_client import JsonExtractionError, extract_json
from impl.core.schema.judge import JudgeLLMOutput
from impl.core.structured_output import StructuredOutputSpec, render_output_constraint


def test_extract_json_parses_plain_and_fenced_json():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_parse_failure_is_explicit_not_raw_text_wrapper():
    bad = '```json\n{"description": "用户口语"重疾险"应映射"}\n```'

    with pytest.raises(JsonExtractionError) as excinfo:
        extract_json(bad)

    message = str(excinfo.value)
    assert "LLM 输出不是合法 JSON" in message
    assert "原始输出预览" in message
    assert "raw_text" not in message


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
