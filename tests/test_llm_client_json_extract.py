from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from impl.core.config import get_llm_config
from impl.core.llm_client import (
    LlmClient,
    _ROUTER_REGISTRY,
    _select_schema_matching_object,
    _tool_budget_error,
    extract_json,
    provider_error_body,
    OutputRejected,
)
from impl.core.judge import _build_judge_output_spec
from impl.core.schema.judge import JudgeLLMOutput
from impl.core.structured_output import StructuredOutputSpec, enforce_output, render_output_constraint


def test_extract_json_parses_plain_and_fenced_json():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_tool_budget_is_checked_against_actual_calls_not_sdk_rounds():
    calls = [{"tool_name": "search_context_units"}] * 7

    assert _tool_budget_error(calls[:6], 6) is None
    assert _tool_budget_error(calls, 6) == (
        "actual tool calls 7 exceed configured limit 6"
    )


def test_tool_budget_ignores_calls_the_sdk_refused_to_execute():
    # 模型一轮并发发两个调用，agno 到上限后拒绝执行多出的那个并以固定文案回给模型；
    # 它没花预算，也不该让模型随后给出的合法答案作废。
    refused = "Tool call limit reached. Tool call es_read not executed. Don't try to execute it again."
    calls = [{"tool_name": "es_search", "result": "{...}"}] * 6 + [{"tool_name": "es_read", "result": refused}] * 2

    assert _tool_budget_error(calls, 6) is None
    assert _tool_budget_error(calls + [{"tool_name": "es_read", "result": "ok"}], 6) == (
        "actual tool calls 7 exceed configured limit 6"
    )


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


def _isolate_llm_router(monkeypatch) -> None:
    _ROUTER_REGISTRY.clear()
    monkeypatch.setattr(LlmClient, "_endpoint_probe", staticmethod(lambda _endpoint: True))


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

        def run(self, _user, **_run_kwargs):
            return Result()

    _isolate_llm_router(monkeypatch)
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


def test_complete_json_records_stage_and_each_application_attempt(monkeypatch):
    calls = {"count": 0}
    tracked = []

    class Result:
        content = '{"investigation_summary":"ok"}'
        status = type("Status", (), {"value": "COMPLETED"})()
        metrics = None
        messages = []

        def to_dict(self):
            return {"content": self.content, "status": "COMPLETED"}

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, _user, **_run_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("provider timeout")
            return Result()

    _isolate_llm_router(monkeypatch)
    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", lambda **_kwargs: object())
    monkeypatch.setattr(
        "impl.core.llm_client._track_context",
        lambda *_args, **kwargs: tracked.append(kwargs.get("runtime")),
    )
    monkeypatch.setattr("impl.core.llm_client.time.sleep", lambda _seconds: None)

    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    result = client.complete_json(
        "system",
        "user",
        stage="judge-plan-semantic-review",
        output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert result["investigation_summary"] == "ok"
    assert tracked[-1]["stage"] == "judge-plan-semantic-review"
    assert [item["status"] for item in tracked[-1]["attempts"]] == [
        "failed",
        "succeeded",
    ]
    assert tracked[-1]["attempts"][0]["error_type"] == "TimeoutError"
    attempts = tracked[-1]["attempts"]
    assert len({item["endpoint"] for item in attempts}) == 2
    assert all(item["model"] for item in attempts)
    assert tracked[-1]["selected_endpoint"] == attempts[-1]["endpoint"]
    assert tracked[-1]["selected_model"] == attempts[-1]["model"]
    assert all(item["elapsed_ms"] >= 0 for item in tracked[-1]["attempts"])


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


def test_complete_json_falls_back_to_second_endpoint_within_one_call(monkeypatch):
    calls = {"count": 0}
    route = []

    class Result:
        content = '{"investigation_summary":"ok"}'
        status = type("Status", (), {"value": "COMPLETED"})()
        metrics = None
        messages = []

        def to_dict(self):
            return {"content": self.content, "status": "COMPLETED"}

    class FakeOpenAILike:
        def __init__(self, **kwargs):
            self.base_url = kwargs.get("base_url")
            self.model = kwargs.get("id")

    class FakeAgent:
        def __init__(self, **kwargs):
            self.model = kwargs["model"]

        def run(self, _user, **_run_kwargs):
            calls["count"] += 1
            base = str(getattr(self.model, "base_url", ""))
            route.append(base)
            if "127.0.0.1:9" in base:
                raise ConnectionError("connection refused (simulated dead endpoint)")
            return Result()

    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", FakeOpenAILike)
    monkeypatch.setattr("impl.core.llm_client._track_context", lambda *_a, **_k: None)
    monkeypatch.setattr("impl.core.llm_client.time.sleep", lambda _s: None)

    from impl.core.llm_router import LlmEndpoint, LlmRouter

    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    client.llm_router = LlmRouter(
        [
            LlmEndpoint(name="primary", base_url="http://127.0.0.1:9/v1", model="m", api_key="k"),
            LlmEndpoint(name="fallback1", base_url="http://fallback.example/v1", model="m", api_key="k"),
        ]
    )

    result = client.complete_json(
        "system",
        "user",
        stage="judge-plan-semantic-review",
        output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert result["investigation_summary"] == "ok"
    assert calls["count"] == 2
    assert "127.0.0.1:9" in route[0]
    assert "fallback.example" in route[1]


def test_provider_error_body_detects_gateway_and_quota_plain_text():
    assert provider_error_body("Prompt too large (209077 chars)") == "Prompt too large (209077 chars)"
    assert provider_error_body("insufficient quota") == "insufficient quota"
    assert provider_error_body("当前账户余额不足，请联系管理员") == "当前账户余额不足，请联系管理员"


def test_provider_error_body_ignores_legitimate_output():
    assert provider_error_body('{"investigation_summary":"ok"}') == ""
    assert provider_error_body("结论：" + "x" * 3000) == ""
    # 长回答里顺带提到 rate limit 不得误判
    assert provider_error_body("本次分析未触发 rate limit。" + "补充说明。" * 100) == ""
    assert provider_error_body("done") == ""


def test_complete_json_treats_provider_error_body_as_endpoint_failure(monkeypatch):
    """HTTP 200 的纯文本端点错误体必须计端点失败，不得 record_success 毒化健康度。"""
    route = []

    class Result:
        status = type("Status", (), {"value": "COMPLETED"})()
        metrics = None
        messages = []

        def __init__(self, content):
            self.content = content

        def to_dict(self):
            return {"content": self.content, "status": "COMPLETED"}

    class FakeOpenAILike:
        def __init__(self, **kwargs):
            self.base_url = kwargs.get("base_url")
            self.model = kwargs.get("id")

    class FakeAgent:
        def __init__(self, **kwargs):
            self.model = kwargs["model"]

        def run(self, _user, **_run_kwargs):
            base = str(getattr(self.model, "base_url", ""))
            route.append(base)
            if "quota-dead" in base:
                return Result("Prompt too large (209077 chars)")
            return Result('{"investigation_summary":"ok"}')

    _isolate_llm_router(monkeypatch)
    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", FakeOpenAILike)
    monkeypatch.setattr("impl.core.llm_client._track_context", lambda *_a, **_k: None)
    monkeypatch.setattr("impl.core.llm_client.time.sleep", lambda _s: None)

    from impl.core.llm_router import LlmEndpoint, LlmRouter

    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    client.llm_router = LlmRouter(
        [
            LlmEndpoint(name="primary", base_url="http://quota-dead/v1", model="m", api_key="k"),
            LlmEndpoint(name="fallback1", base_url="http://healthy/v1", model="m", api_key="k"),
        ]
    )

    result = client.complete_json(
        "system", "user", output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput)
    )

    assert result["investigation_summary"] == "ok"
    assert len(route) == 2
    assert "quota-dead" in route[0] and "healthy" in route[1]
    assert client.llm_router._health["primary"].consecutive_failures >= 1


def test_enforce_blocked_call_is_recorded_before_raising(monkeypatch):
    """enforce 阻断的那次调用同样花了钱、产出了内容：必须先落 context 记录再抛。

    否则 context 页只看到 reprompt 那次成功调用，看不到触发它的首轮失败，也看不到
    被丢弃的那份产出（boundary=null 这类 reprompt 的成本完全不可见）。
    """
    tracked = []

    class Result:
        content = '{"investigation_summary":""}'
        status = type("Status", (), {"value": "COMPLETED"})()
        metrics = None
        messages = []

        def to_dict(self):
            return {"content": self.content, "status": "COMPLETED"}

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, _user, **_run_kwargs):
            return Result()

    def capture(_self, request, result, trace_id, token_metrics, elapsed_ms, error, **kwargs):
        tracked.append({
            "system": request[0]["content"],
            "user": request[1]["content"],
            "trace_id": trace_id,
            "elapsed_ms": elapsed_ms,
            "error": error,
            "runtime": kwargs.get("runtime"),
        })

    _isolate_llm_router(monkeypatch)
    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", lambda **_kwargs: object())
    monkeypatch.setattr("impl.core.llm_client._track_context", capture)

    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    spec = StructuredOutputSpec.from_dataclass(
        _InvestigationOutput,
        required_nonempty=["investigation_summary"],
    )

    with pytest.raises(ValueError, match="结构化输出约束"):
        client.complete_json("system", "user", trace_id="trace-enforce", output_spec=spec)

    assert len(tracked) == 1
    assert "结构化输出约束" in tracked[0]["error"]
    assert tracked[0]["trace_id"] == "trace-enforce"
    # 记录的是注入输出约束文案之后、真正发给模型的 system（与成功路径一致）。
    assert tracked[0]["system"].startswith("system")
    assert "### 强约束" in tracked[0]["system"]
    assert tracked[0]["user"] == "user"
    assert tracked[0]["runtime"]["attempts"]
    assert tracked[0]["elapsed_ms"] >= 0


def test_unusable_endpoint_output_is_detected_before_success():
    """端点回了 200 但产出没法当结构化输出用：必须判为不可用，否则会被记为成功、不切换端点。"""
    from impl.core.llm_client import _usable_structured
    from impl.core.structured_output import FREE_TEXT_OUTPUT

    class Spec:
        pass

    assert _usable_structured('{"result": "ok"}', FREE_TEXT_OUTPUT) == ""
    assert '不是 JSON 对象' in _usable_structured('""', FREE_TEXT_OUTPUT)
    assert '不是 JSON 对象' in _usable_structured('"plain text"', FREE_TEXT_OUTPUT)
    assert _usable_structured('{"a": 1}', None) == ""


def test_json_error_body_from_a_proxy_is_a_provider_error():
    """中转站把上游 4xx 当 200 回吐成 {"error": {...}}：必须计端点失败，不能当模型产出。"""
    from impl.core.llm_client import provider_error_body

    body = '{"error": {"code": 400, "message": "User location is not supported for the API use.", "status": "FAILED_PRECONDITION"}}'
    hit = provider_error_body(body)
    assert "400" in hit and "User location" in hit
    assert provider_error_body('{"error": "rate limited"}')
    # 正常产出（多个键）不是错误体
    assert provider_error_body('{"route": [], "error": "in evidence"}') == ""


def test_tool_call_messages_are_serialisable_for_context_store():
    """带工具调用的消息里藏着 pydantic 对象：不拍平的话整条调用记录会被静默丢掉。"""
    import json
    from impl.core.llm_client import _extract_messages

    class FakeMessage:
        def model_dump(self):
            return {"role": "assistant", "content": "", "tool_calls": [object()]}

    class Result:
        messages = [FakeMessage(), {"role": "tool", "content": "{}", "tool_call_id": "1"}]

    messages = _extract_messages(Result())
    assert json.dumps(messages)          # 不抛异常即可
    assert messages[0]["tool_calls"] and isinstance(messages[0]["tool_calls"][0], str)


def _flaky_client(monkeypatch, fail_times: int, sleeps: list):
    """primary 先失败 fail_times 次再成功；备用端点一开始就在冷却。"""
    calls = {"count": 0}

    class Result:
        content = '{"investigation_summary":"ok"}'
        status = type("Status", (), {"value": "COMPLETED"})()
        metrics = None
        messages = []

        def to_dict(self):
            return {"content": self.content, "status": "COMPLETED"}

    class FakeAgent:
        def __init__(self, **kwargs):
            self.model = kwargs["model"]

        def run(self, _user, **_run_kwargs):
            calls["count"] += 1
            if calls["count"] <= fail_times:
                raise ConnectionError("simulated transient failure")
            return Result()

    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", lambda **_k: object())
    monkeypatch.setattr("impl.core.llm_client._track_context", lambda *_a, **_k: None)
    monkeypatch.setattr("impl.core.llm_client.time.sleep", sleeps.append)

    from impl.core.llm_router import LlmEndpoint, LlmRouter

    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    router = LlmRouter([
        LlmEndpoint(name="primary", base_url="http://p/v1", model="m", api_key="k"),
        LlmEndpoint(name="fallback1", base_url="http://f/v1", model="m", api_key="k"),
    ], cooldown_seconds=0.0)
    router._health["fallback1"].cooldown_until = float("inf")
    client.llm_router = router
    return client, calls


def test_cooling_untried_endpoint_falls_back_to_retrying_tried_one(monkeypatch):
    # 旧行为：primary 失败后只剩冷却中的 fallback1，select 直接抛 "no untried llm endpoint remains"。
    sleeps: list = []
    client, calls = _flaky_client(monkeypatch, fail_times=1, sleeps=sleeps)
    result = client.complete_json("s", "u", output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput))
    assert result["investigation_summary"] == "ok"
    assert calls["count"] == 2 and sleeps == []


def test_endpoint_wait_seconds_backs_off_until_endpoint_recovers(monkeypatch):
    sleeps: list = []
    client, calls = _flaky_client(monkeypatch, fail_times=3, sleeps=sleeps)
    router = client.llm_router
    router.cooldown_seconds = 1e9            # primary 连续失败后进入冷却，只有等待能让它恢复

    def sleep(seconds):
        sleeps.append(seconds)
        router._health["primary"].cooldown_until = 0.0   # 模拟冷却期过去

    monkeypatch.setattr("impl.core.llm_client.time.sleep", sleep)
    client.endpoint_wait_seconds = (1.0, 2.0, 4.0)
    result = client.complete_json("s", "u", output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput))
    assert result["investigation_summary"] == "ok"
    assert calls["count"] == 4
    assert sleeps and sleeps[0] == 1.0


def test_no_wait_configured_still_fails_fast(monkeypatch):
    sleeps: list = []
    client, calls = _flaky_client(monkeypatch, fail_times=99, sleeps=sleeps)
    result = client.complete_json("s", "u", output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput))
    assert result["error"] == "llm_request_failed"
    assert sleeps == [] and calls["count"] <= 4


def test_stray_inner_quotes_in_prose_are_escaped_not_guessed_into_a_wrong_structure():
    from impl.core.llm_client import _strict_json_error, extract_json
    text = '{"reason":"定义 PARTIAL 为"已命中但所问字段缺失"，而字段存在","units":[{"fact":"回答"是任言琳的保单"，对应 E1","k":"a\\"b"}]}'
    assert extract_json(text) == {'reason': '定义 PARTIAL 为"已命中但所问字段缺失"，而字段存在',
                                  'units': [{'fact': '回答"是任言琳的保单"，对应 E1', 'k': 'a"b'}]}
    assert _strict_json_error(text) == ''


def test_wellformed_json_and_real_structure_errors_are_unaffected_by_quote_escaping():
    from impl.core.llm_client import _strict_json_error, extract_json
    assert extract_json('{"a":"x", "b" : ["y", "z"], "c": {"d": "e"}}') == {'a': 'x', 'b': ['y', 'z'], 'c': {'d': 'e'}}
    broken = '{"a": "x" "b": 1}'  # missing comma is a structure error, not a stray quote
    assert _strict_json_error(broken) != ''


def test_quoted_json_looking_fragments_and_fenced_bodies_are_repaired_the_same_way():
    from impl.core.llm_client import extract_json
    prose = '{"fact":"gaps 一致为["本轮部分内容缺少可核验来源"]，唯一差异是 trace_id 从"TR-1"变为 null","ok":true}'
    assert extract_json(prose) == {'fact': 'gaps 一致为["本轮部分内容缺少可核验来源"]，唯一差异是 trace_id 从"TR-1"变为 null', 'ok': True}
    fenced = '```json\n{"reason":"称"已命中"字段","n":[1, 2],"s":"x"}\n```'
    assert extract_json(fenced) == {'reason': '称"已命中"字段', 'n': [1, 2], 's': 'x'}


def _fake_agent(monkeypatch, content, seen):
    class Result:
        status = type("Status", (), {"value": "COMPLETED"})()
        metrics = None
        messages = []

        def __init__(self):
            self.content = content

        def to_dict(self):
            return {"content": self.content, "status": "COMPLETED"}

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, messages, **_run_kwargs):
            seen.append([(m.role, m.content) for m in messages])
            return Result()

    _isolate_llm_router(monkeypatch)
    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", lambda **_kwargs: object())
    monkeypatch.setattr("impl.core.llm_client._track_context", lambda *_args, **_kwargs: None)
    return LlmClient(config=replace(get_llm_config(), api_key="test-key"))


def test_history_sits_between_system_and_this_turn(monkeypatch):
    """纠错轮是新一轮追加：前几轮消息原样插在 system 与本轮 user 之间，前缀才与上一次请求一致。"""
    seen = []
    client = _fake_agent(monkeypatch, '{"investigation_summary":"ok"}', seen)
    spec = StructuredOutputSpec.from_dataclass(_InvestigationOutput, required_nonempty=["investigation_summary"])
    history = [{"role": "user", "content": "原题"}, {"role": "assistant", "content": "上次产出"}]
    out = client.complete_json("system", "更正说明", trace_id="t-history", output_spec=spec, history=history)
    assert out["investigation_summary"] == "ok"
    assert seen == [[("user", "原题"), ("assistant", "上次产出"), ("user", "更正说明")]]


def test_rejected_output_carries_the_model_text(monkeypatch):
    """被强校验拒收时，异常带出模型原文，调用方的纠错轮才能把它作为上一轮 assistant 带回。"""
    seen = []
    client = _fake_agent(monkeypatch, '{"investigation_summary":""}', seen)
    spec = StructuredOutputSpec.from_dataclass(_InvestigationOutput, required_nonempty=["investigation_summary"])
    with pytest.raises(OutputRejected) as caught:
        client.complete_json("system", "user", trace_id="t-reject", output_spec=spec)
    assert caught.value.content == '{"investigation_summary":""}'
