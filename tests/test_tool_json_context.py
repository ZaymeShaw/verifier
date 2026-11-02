"""CG-ENG-002：工具结果进入模型上下文前序列化为 JSON 文本。

工具层仍返回结构化 ToolResult/dict（程序化消费者不变），只有 LLM 边界（json_tool /
_json_context_tools）把返回值转成 JSON 文本，且不破坏 agno 的参数 schema 推断。
"""
from __future__ import annotations

import inspect
import json
from typing import Annotated, List, Optional, get_type_hints

from pydantic import Field

from impl.core.llm_client import _json_context_tools
from impl.core.structured_output import StructuredOutputSpec
from impl.tools.protocol import ToolResult, VerifiableTool, build_agno_tools, json_tool


def _candidate_payload():
    return {"selection_ref": "C7", "ok": True, "items": [1, 2, None]}


class _Guarded:
    def search_context_units(
        self,
        queries: Annotated[List[str], Field(min_length=1, max_length=4)],
        top_k_per_query: Optional[int] = None,
    ):
        return ToolResult(
            tool_id="ctx.search",
            status="succeeded",
            actual={"hits": len(queries)},
            evidence="ok",
        )


def test_json_tool_preserves_callable_signature_and_serializes_result():
    guarded = _Guarded()
    wrapped = json_tool(guarded.search_context_units)

    params = inspect.signature(wrapped).parameters
    assert set(params) == {"queries", "top_k_per_query"}
    assert "queries" in get_type_hints(wrapped)

    out = wrapped(queries=["a", "b"], top_k_per_query=2)
    assert isinstance(out, str)
    payload = json.loads(out)
    assert payload["actual"]["hits"] == 2
    assert payload["tool_id"] == "ctx.search"


def test_json_tool_serializes_dict_list_and_passthrough_scalars():
    assert json.loads(json_tool(lambda: {"a": 1})()) == {"a": 1}
    assert json.loads(json_tool(lambda: [True, None])()) == [True, None]
    assert json_tool(lambda: "plain text")() == "plain text"


def test_json_tool_survives_agno_from_callable_schema_inference():
    """裸 callable 经 json_tool 包装后，agno from_callable -> process_entrypoint
    仍能推出原始参数 schema（防 agno 版本变化导致 schema 退化）。"""
    from agno.tools import Function

    wrapped = json_tool(_Guarded().search_context_units)
    function = Function.from_callable(wrapped)
    function.process_entrypoint()

    schema = function.to_dict()["parameters"]
    assert set(schema["properties"]) == {"queries", "top_k_per_query"}
    assert schema["required"] == ["queries"]


def test_json_context_tools_wraps_function_copy_without_mutating_source():
    tool = VerifiableTool(
        tool_id="search.conditions",
        description="search conditions",
        parameters={
            "type": "object",
            "properties": {"params": {"type": "object", "description": "query"}},
        },
        execute_fn=lambda params=None: _candidate_payload(),
    )
    [source_fn] = build_agno_tools([tool])
    [wrapped_fn] = _json_context_tools([source_fn])

    assert wrapped_fn is not source_fn
    assert source_fn.entrypoint()["selection_ref"] == "C7"  # 工具层契约不变

    assert wrapped_fn.skip_entrypoint_processing is True
    assert wrapped_fn.entrypoint.__name__ == "search_conditions"
    assert getattr(wrapped_fn.entrypoint, "logical_tool_id", None) == "search.conditions"

    out = wrapped_fn.entrypoint()
    assert isinstance(out, str)
    assert json.loads(out)["ok"] is True

    # agno 侧 process_entrypoint 因 skip 标志不重写 entrypoint；schema 原样
    wrapped_fn.process_entrypoint()
    schema = wrapped_fn.to_dict()["parameters"]
    assert schema["properties"]["params"]["type"] == "object"


def test_complete_json_model_tool_messages_are_json_and_match_audit(monkeypatch):
    """端到端模拟：agno 把 str(entrypoint()) 写入 tool 消息时，模型视角是 JSON，
    且 audit 日志（_extract_tool_call_log）与模型视角逐字节一致。"""
    from dataclasses import dataclass, replace

    from impl.core.config import get_llm_config
    from impl.core.llm_client import LlmClient, _extract_tool_call_log

    @dataclass
    class _SimOut:
        summary: str

    captured = {"tools": None, "messages": []}

    class FakeAgent:
        def __init__(self, **_kwargs):
            captured["tools"] = _kwargs.get("tools") or []

        def run(self, _user, **_run_kwargs):
            messages = []
            for i, tool in enumerate(captured["tools"]):
                fn = tool.entrypoint if hasattr(tool, "entrypoint") else tool
                name = getattr(tool, "name", None) or getattr(tool, "__name__", "tool")
                args = (
                    {"queries": ["orphanType 枚举"]}
                    if name == "search_context_units"
                    else {"params": {"q": "orphanType"}}
                )
                result = fn(**args)
                tcid = f"call_{i}"
                messages.append({"role": "tool", "tool_call_id": tcid, "content": str(result)})
                messages.append({
                    "role": "assistant",
                    "tool_calls": [{"id": tcid, "function": {"name": name, "arguments": json.dumps(args)}}],
                })
            captured["messages"] = messages
            msgs = messages

            class Result:
                content = '{"summary":"ok"}'
                status = type("S", (), {"value": "COMPLETED"})()
                metrics = None
                messages = msgs

                def to_dict(self):
                    return {"content": self.content, "status": "COMPLETED"}

            return Result()

    import impl.core.llm_client as llm_client_mod

    class FakeModel:
        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr(llm_client_mod, "Agent", FakeAgent)
    monkeypatch.setattr(llm_client_mod, "OpenAILike", FakeModel)
    monkeypatch.setattr(llm_client_mod, "_track_context", lambda *_a, **_k: None)
    import impl.core.context_governance as context_governance_mod
    monkeypatch.setattr(context_governance_mod, "ensure_call_context_governance", lambda *_a, **_k: None)

    tools: list = [_Guarded().search_context_units]
    tools += build_agno_tools([
        VerifiableTool(
            tool_id="search.conditions",
            description="search conditions",
            parameters={"type": "object", "properties": {"params": {"type": "object", "description": "query"}}},
            execute_fn=lambda params=None: {"candidates": [{"selection_ref": "C7"}]},
        )
    ])
    client = LlmClient(
        config=replace(get_llm_config(), api_key="test-key"),
        tools=tools,
        role="attribute",
    )
    result = client.complete_json("system", "user", output_spec=StructuredOutputSpec.from_dataclass(_SimOut))
    assert result["summary"] == "ok"

    model_views = [m["content"] for m in captured["messages"] if m["role"] == "tool"]
    assert len(model_views) == 2
    for view in model_views:
        assert isinstance(json.loads(view), (dict, list))  # 合法 JSON，不是 Python repr

    class MessagesWrap:
        def __init__(self, messages):
            self.messages = messages

    audit = _extract_tool_call_log(MessagesWrap(captured["messages"]))
    assert [e["result"] for e in audit] == model_views  # audit 与模型视角一致
