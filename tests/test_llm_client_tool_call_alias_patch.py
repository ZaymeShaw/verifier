"""回归：streaming 路径的 tool-call 别名补丁必须兼容 agno 的 staticmethod parse_tool_calls。

agno>=2.3 的 OpenAIChat.parse_tool_calls 是 @staticmethod（chat.py），只被流式路径
（Model._populate_assistant_message_from_stream_data）调用。带 logical_tool_id 的工具
（如 client_search 的 investigation.search_index）会在 llm_client 里给 model 实例挂
MethodType 补丁做别名回填；补丁内部再调 OpenAILike.parse_tool_calls 时传 self 就会
TypeError。必须用真实 agno 类测，假对象测不出 staticmethod 语义。
"""
from __future__ import annotations

from types import MethodType

from agno.models.openai.like import OpenAILike
from openai.types.chat.chat_completion_chunk import (
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)

from impl.core.llm_client import _parse_tool_calls_with_aliases

_ALIASES = {"investigation.search_index": "investigation_search_index"}


def _patched_model() -> OpenAILike:
    model = OpenAILike(id="test", api_key="test")
    object.__setattr__(model, "logical_tool_aliases", dict(_ALIASES))
    object.__setattr__(
        model, "parse_tool_calls", MethodType(_parse_tool_calls_with_aliases, model)
    )
    return model


def _tool_call(name: str, arguments: str) -> ChoiceDeltaToolCall:
    return ChoiceDeltaToolCall(
        index=0,
        id="call_1",
        type="function",
        function=ChoiceDeltaToolCallFunction(name=name, arguments=arguments),
    )


def test_alias_patch_parses_runtime_tool_names():
    model = _patched_model()
    parsed = model.parse_tool_calls(
        [_tool_call("investigation_search_index", '{"q": "x"}')]
    )
    assert parsed[0]["function"]["name"] == "investigation_search_index"
    assert parsed[0]["function"]["arguments"] == '{"q": "x"}'


def test_alias_patch_maps_logical_id_to_runtime_name():
    model = _patched_model()
    parsed = model.parse_tool_calls([_tool_call("investigation.search_index", "{}")])
    assert parsed[0]["function"]["name"] == "investigation_search_index"
