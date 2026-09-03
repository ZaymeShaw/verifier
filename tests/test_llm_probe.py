from __future__ import annotations

import io
import json
import urllib.error

import pytest

from impl.core.live_protocol import LiveServiceUnavailableError, _is_service_unavailable
from impl.core.live_transport import LiveHTTPStatusError, LiveTransport
from impl.core.mock_agent import load_live_schema
from impl.core.project_loader import load_project
from impl.core.schema import RunTrace
from impl.projects.llm_probe import live_schema as probe_schema
from impl.projects.llm_probe.capability import default_capability_ref, mock_body, resolve_capability
from impl.projects.llm_probe.judge import LlmProbeJudge
from impl.projects.llm_probe.live import LlmProbeLive, resolve_http
from impl.projects.llm_probe.mock import LlmProbeMock


class _Response:
    def __init__(self, body: bytes, content_type: str = "application/json", status: int = 200):
        self.body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self.body


def test_request_requires_capability_xor_and_url_or_ref():
    check = probe_schema.check
    assert check.request({"body": {"q": 1}, "capability_ref": "client_search"})
    assert check.request({
        "body": {"q": 1},
        "url": "http://127.0.0.1/x",
        "capability": "echo JSON",
    })
    assert not check.request({"body": {"q": 1}})
    assert not check.request({"body": {"q": 1}, "capability": "echo JSON"})
    assert not check.request({"body": {"q": 1}, "url": "http://127.0.0.1/x"})
    assert not check.request({"body": {"q": 1}, "capability_ref": "missing_project"})


def test_load_live_schema_keeps_probe_xor_check():
    loaded = load_live_schema("llm_probe")
    assert loaded.check is probe_schema.check
    assert loaded.check.request({"body": {"q": 1}, "capability_ref": "client_search"})
    assert not loaded.check.request({"body": {"q": 1}})


def test_explicit_capability_wins_over_map():
    assert resolve_capability({
        "capability": "custom probe",
        "capability_ref": "client_search",
    }) == "custom probe"
    text = resolve_capability({"capability_ref": "client_search"})
    assert "查询谓词集" in text


def test_resolve_http_sends_nested_body_and_maps_capability_ref_url():
    spec = load_project("llm_probe")
    url, method, headers, body, timeout, response_mode = resolve_http(
        {
            "body": {"user_text": "张伟"},
            "capability_ref": "client_search",
            "headers": {"X-Trace": "1"},
        },
        spec,
    )
    assert body == {"user_text": "张伟"}
    assert method == "POST"
    assert headers == {"X-Trace": "1"}
    assert timeout > 0
    assert response_mode == "json"
    client = load_project("client_search").require_service("primary")
    expected = str(client["base_url"]).rstrip("/") + "/" + str(client["endpoint"]).lstrip("/")
    assert url == expected


def test_extract_output_stringifies_response_body():
    live = LlmProbeLive(load_project("llm_probe"))
    assert live.extract_output([{"ok": True}]) == {"output_text": '{"ok": true}'}
    assert live.extract_output(["plain"]) == {"output_text": "plain"}
    assert live.extract_output([]) == {"output_text": ""}


def test_non_json_response_keeps_raw_text_through_full_transport(monkeypatch):
    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: _Response("纯文本响应 not json".encode("utf-8"), "text/plain"),
    )
    live = LlmProbeLive(load_project("llm_probe"))
    output = live.deliver_turn(
        {
            "body": {"q": 1},
            "url": "http://127.0.0.1:9/llm-probe",
            "method": "POST",
            "capability": "echo text",
        }
    )
    assert output == {"output_text": "纯文本响应 not json"}


def test_json_response_keeps_json_string_through_full_transport(monkeypatch):
    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: _Response(json.dumps({"answer": "好"}, ensure_ascii=False).encode("utf-8")),
    )
    live = LlmProbeLive(load_project("llm_probe"))
    output = live.deliver_turn(
        {
            "body": {"q": 1},
            "url": "http://127.0.0.1:9/llm-probe",
            "method": "POST",
            "capability": "echo JSON",
        }
    )
    assert output == {"output_text": '{"answer": "好"}'}


def test_http_status_error_raises_and_is_not_service_unavailable(monkeypatch):
    payload = {"detail": "bad request"}

    def fake_urlopen(_request, timeout=0):
        raise urllib.error.HTTPError(
            "http://127.0.0.1:9/llm-probe",
            422,
            "Unprocessable Content",
            {"Content-Type": "application/json"},
            io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

    monkeypatch.setattr("impl.core.live_transport.urllib.request.urlopen", fake_urlopen)
    live = LlmProbeLive(load_project("llm_probe"))
    with pytest.raises(LiveHTTPStatusError) as caught:
        live.deliver_real(
            {
                "body": {"q": 1},
                "url": "http://127.0.0.1:9/llm-probe",
                "method": "POST",
                "capability": "echo JSON",
            },
            LiveTransport(),
        )
    assert caught.value.status_code == 422
    assert not isinstance(caught.value, LiveServiceUnavailableError)


def test_http_status_error_is_classified_separately_from_unavailable():
    assert _is_service_unavailable(LiveHTTPStatusError(500, {"error": "boom"})) is False
    assert _is_service_unavailable(LiveHTTPStatusError(404, None)) is False
    assert _is_service_unavailable(LiveServiceUnavailableError("target down")) is True
    assert _is_service_unavailable(urllib.error.URLError("connection refused")) is True
    assert _is_service_unavailable(TimeoutError("timed out")) is True
    assert _is_service_unavailable(ValueError("schema error")) is False


def _probe_trace(request: dict, output_text: str = "ok") -> RunTrace:
    return RunTrace(
        trace_id="llm_probe:test",
        project_id="llm_probe",
        input=dict(request),
        normalized_request=dict(request),
        extracted_output={"output_text": output_text},
    )


def test_judge_capability_resolution_failure_fails_fast():
    judge = LlmProbeJudge(load_project("llm_probe"))
    trace = _probe_trace({"body": {"q": 1}, "url": "http://127.0.0.1:9/llm-probe"})
    with pytest.raises(ValueError, match="capability"):
        judge.build_context(trace)


SAMPLE_TOKEN = "{material://llm_probe/client-search-match-rule}"
SAMPLE_BODY_MARK = "姓名全值等值匹配"


def test_judge_context_expands_sample_material_into_capability() -> None:
    """轴1 喂给 judge 的 user_intent / extras.capability 必须是展开后的资料正文。"""
    judge = LlmProbeJudge(load_project("llm_probe"))
    before = judge.build_context(_probe_trace({
        "body": {"user_text": "客户姓名是张伟的人"},
        "url": "http://127.0.0.1:8000/x",
        "capability": "接收自然语言客户群体描述，输出结构化搜索条件。",
    }))
    after = judge.build_context(_probe_trace({
        "body": {"user_text": "客户姓名是张伟的人"},
        "url": "http://127.0.0.1:8000/x",
        "capability": f"接收自然语言客户群体描述。匹配规则见 {SAMPLE_TOKEN}",
    }))
    assert SAMPLE_BODY_MARK not in before["user_intent"]
    assert SAMPLE_BODY_MARK not in json.dumps(before["user_prompt_extras"], ensure_ascii=False)
    assert SAMPLE_BODY_MARK in after["user_intent"]
    assert SAMPLE_BODY_MARK in after["user_prompt_extras"]["capability"]
    # 展开后的能力描述里应带正文，而不是只剩未解析记号
    assert "--- material://llm_probe/client-search-match-rule ---" in after["user_intent"]


def test_judge_context_redacts_credential_headers():
    judge = LlmProbeJudge(load_project("llm_probe"))
    trace = _probe_trace({
        "body": {"q": 1},
        "url": "http://127.0.0.1:9/llm-probe",
        "capability": "echo JSON",
        "headers": {
            "Authorization": "Bearer sk-secret",
            "X-Api-Key": "raw-key",
            "X-Trace": "1",
        },
    })
    context = judge.build_context(trace)
    headers = context["user_prompt_extras"]["request"]["headers"]
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["X-Api-Key"] == "[REDACTED]"
    assert headers["X-Trace"] == "1"
    assert "sk-secret" not in json.dumps(context, ensure_ascii=False, default=str)


def test_resolve_http_rejects_non_http_scheme():
    spec = load_project("llm_probe")
    with pytest.raises(ValueError, match="http/https"):
        resolve_http(
            {"body": {"q": 1}, "url": "file:///etc/passwd", "capability": "echo"},
            spec,
        )


def test_resolve_http_merges_ref_config_even_when_url_is_explicit():
    spec = load_project("llm_probe")
    client = load_project("client_search").require_service("primary")
    url, method, _headers, _body, timeout, _mode = resolve_http(
        {
            "body": {"user_text": "张伟"},
            "url": "http://override.test/parse",
            "capability_ref": "client_search",
        },
        spec,
    )
    assert url == "http://override.test/parse"
    assert method == str(client["method"]).upper()
    assert timeout == float(client["timeout_seconds"])


def test_deliver_real_writes_back_resolved_url_and_method(monkeypatch):
    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: _Response(b'{"ok": true}'),
    )
    live = LlmProbeLive(load_project("llm_probe"))
    request = {"body": {"user_text": "张伟"}, "capability_ref": "client_search"}
    live.deliver_real(request, LiveTransport())
    client = load_project("client_search").require_service("primary")
    expected = str(client["base_url"]).rstrip("/") + "/" + str(client["endpoint"]).lstrip("/")
    assert request["url"] == expected
    assert request["method"] == str(client["method"]).upper()


def test_mock_dynamic_request_is_valid_for_default_capability():
    class _Intent:
        query = "五十岁以上的客户都有谁"
        user_intent = "筛选五十岁以上的客户"
        scenario = ""

    mock = LlmProbeMock(load_project("llm_probe"))
    request = mock.build_initial_request(_Intent())
    assert request["capability_ref"] == default_capability_ref()
    assert probe_schema.check.request(request)
    assert request["body"]["user_text"] == _Intent.query
    assert "text" not in request["body"]


def test_mock_dynamic_request_follows_scenario_capability():
    class _Intent:
        query = "合同号码里带4826的"
        user_intent = "按保单号片段筛保单"
        scenario = "policy_search"

    mock = LlmProbeMock(load_project("llm_probe"))
    request = mock.build_initial_request(_Intent())
    assert request["capability_ref"] == "policy_search"
    assert probe_schema.check.request(request)
    assert request["body"]["extra_input_params"]["policySearchParseArgs"]["query"] == _Intent.query


def test_default_capability_ref_does_not_depend_on_yaml_key_order(monkeypatch):
    mapping = {
        "z_last": {"capability": "z capability"},
        "a_first": {"capability": "a capability"},
    }
    monkeypatch.setattr(
        "impl.projects.llm_probe.capability.load_capability_map",
        lambda: mapping,
    )
    assert default_capability_ref() == "a_first"


def test_mock_body_template_fills_query_recursively():
    body = mock_body("marketting-planning-intent", "帮我做NBEV规划")
    assert body["user_text"] == "帮我做NBEV规划"
    assert body["extra_input_params"]["agent_args"]["message"]["content"] == "帮我做NBEV规划"


def test_mock_cases_fixture_restores_regression_cases_and_passes_schema():
    import json as _json
    from pathlib import Path

    cases = _json.loads(
        (Path(__file__).parents[1] / "impl" / "data" / "llm_probe" / "mock_cases.json").read_text(encoding="utf-8")
    )
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    restored = {
        "llm-probe-client_search-age-schema",
        "llm-probe-client_search-exclusion",
        "llm-probe-client_search-multi",
        "llm-probe-client_search-unsupported",
        "llm-probe-mpi-fallback-unknown",
        "llm-probe-mpi-nbev-planning",
        "llm-probe-mpi-nbev-slots",
        "llm-probe-mpi-team-portrait",
        "llm-probe-mpi-weather-other",
        "llm-probe-policy_search-product-tail",
    }
    assert restored.issubset(set(ids))
    for case in cases:
        assert probe_schema.check.request(case["live_request"]), case["id"]
        ref = case["live_request"]["capability_ref"]
        assert case["scenario"] == ref, case["id"]
        assert ref in {
            "client_search",
            "policy_search",
            "marketting-planning-intent",
            "dashscope-qa",
        }


def test_streaming_response_is_rejected_before_body_read(monkeypatch):
    class StreamResponse:
        status = 200
        headers = {"Content-Type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return self.status

        def read(self):
            raise AssertionError("流式响应必须在读取 body 之前被拒绝")

    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: StreamResponse(),
    )
    live = LlmProbeLive(load_project("llm_probe"))
    with pytest.raises(RuntimeError, match="text/event-stream"):
        live.deliver_real(
            {
                "body": {"q": 1},
                "url": "http://127.0.0.1:9/llm-probe",
                "method": "POST",
                "capability": "echo JSON",
            },
            LiveTransport(),
        )


class _SseResponse:
    """带 read(size) 的伪流式响应：帧全部就绪，读完即 EOF。"""

    def __init__(self, body: bytes, endless: bool = False):
        self._stream = io.BytesIO(body)
        self._endless = endless
        self.status = 200
        self.headers = {"Content-Type": "text/event-stream; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if self._endless:
            return b"data: {\"delta\": \"x\"}\n\n" * 64
        return self._stream.read(size)


def test_sse_last_frame_takes_final_data_frame(monkeypatch):
    frames = (
        ": keep-alive\n\n"
        'data: {"answer": "部分"}\n\n'
        'data: {"answer": "完整答案", "done": true}\n\n'
        "data: [DONE]\n\n"
    )
    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: _SseResponse(frames.encode("utf-8")),
    )
    live = LlmProbeLive(load_project("llm_probe"))
    request = {
        "body": {"q": 1},
        "url": "http://127.0.0.1:9/llm-probe",
        "method": "POST",
        "capability": "echo JSON",
        "response_mode": "sse_last_frame",
    }
    output = live.deliver_turn(request)
    assert json.loads(output["output_text"]) == {"answer": "完整答案", "done": True}
    assert request["response_mode"] == "sse_last_frame"


def test_sse_last_frame_bounded_read_rejects_endless_stream(monkeypatch):
    from impl.core.live_transport import LiveSseReadError

    monkeypatch.setattr("impl.core.live_transport.SSE_MAX_BYTES", 4096)
    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: _SseResponse(b"", endless=True),
    )
    live = LlmProbeLive(load_project("llm_probe"))
    with pytest.raises(LiveSseReadError, match="增量流式"):
        live.deliver_real(
            {
                "body": {"q": 1},
                "url": "http://127.0.0.1:9/llm-probe",
                "method": "POST",
                "capability": "echo JSON",
                "response_mode": "sse_last_frame",
            },
            LiveTransport(),
        )


def test_sse_last_frame_json_content_type_reads_normally(monkeypatch):
    # 声明了 last-frame 但服务实际回 JSON：按普通 JSON 读，不做帧解析。
    monkeypatch.setattr(
        "impl.core.live_transport.urllib.request.urlopen",
        lambda request, timeout=0: _Response(b'{"ok": true}'),
    )
    live = LlmProbeLive(load_project("llm_probe"))
    output = live.deliver_turn(
        {
            "body": {"q": 1},
            "url": "http://127.0.0.1:9/llm-probe",
            "method": "POST",
            "capability": "echo JSON",
            "response_mode": "sse_last_frame",
        }
    )
    assert output == {"output_text": '{"ok": true}'}


def test_parse_sse_last_frame_variants():
    from impl.core.live_transport import LiveSseReadError, parse_sse_last_frame

    assert parse_sse_last_frame('data: {"a": 1}\n\ndata: {"a": 2}\n\n') == {"a": 2}
    # 帧内多条 data 行按 SSE 规范拼接
    assert parse_sse_last_frame('data: {"a":\ndata:  3}\n\n') == {"a": 3}
    # 非 JSON 数据帧保留原文
    assert parse_sse_last_frame("data: plain text\n\n") == "plain text"
    with pytest.raises(LiveSseReadError, match="没有可用的 data 帧"):
        parse_sse_last_frame(": comment only\n\ndata: [DONE]\n\n")


def test_resolve_http_takes_response_mode_from_capability_service(monkeypatch):
    mapping = {
        "pseudo_stream_api": {
            "capability": "echo",
            "service": {
                "url": "http://127.0.0.1:9/sse",
                "method": "POST",
                "timeout_seconds": 30,
                "response_mode": "sse_last_frame",
            },
        }
    }
    monkeypatch.setattr(
        "impl.projects.llm_probe.capability.load_capability_map",
        lambda: mapping,
    )
    spec = load_project("llm_probe")
    *_rest, response_mode = resolve_http(
        {"body": {"q": 1}, "capability_ref": "pseudo_stream_api"},
        spec,
    )
    assert response_mode == "sse_last_frame"
    with pytest.raises(ValueError, match="response_mode"):
        resolve_http(
            {"body": {"q": 1}, "capability_ref": "pseudo_stream_api", "response_mode": "sse_accumulate"},
            spec,
        )


def test_capability_store_validates_response_mode():
    from impl.core.capability_store import validate_entry

    entry = validate_entry(
        "pseudo",
        {
            "capability": "echo",
            "service": {"url": "http://127.0.0.1:9/sse", "response_mode": "sse_last_frame"},
        },
    )
    assert entry["service"]["response_mode"] == "sse_last_frame"
    plain = validate_entry(
        "plain",
        {"capability": "echo", "service": {"url": "http://127.0.0.1:9/json"}},
    )
    assert "response_mode" not in plain["service"]
    with pytest.raises(ValueError, match="response_mode"):
        validate_entry(
            "bad",
            {"capability": "echo", "service": {"url": "http://x", "response_mode": "sse_accumulate"}},
        )
    headed = validate_entry(
        "headed",
        {
            "capability": "echo",
            "service": {
                "url": "http://127.0.0.1:9/sse",
                "headers": {"Authorization": "Bearer ${BAILIAN_API_KEY}", "X-DashScope-SSE": "enable"},
            },
        },
    )
    assert headed["service"]["headers"]["Authorization"] == "Bearer ${BAILIAN_API_KEY}"


def test_project_default_timeout_is_180():
    spec = load_project("llm_probe")
    assert float(spec.require_service("primary")["timeout_seconds"]) == 180.0


def test_resolve_http_streaming_keeps_primary_timeout_when_service_omits_it(monkeypatch):
    mapping = {
        "stream-no-timeout": {
            "capability": "echo",
            "service": {"url": "http://127.0.0.1:9/sse", "response_mode": "sse_last_frame"},
        }
    }
    monkeypatch.setattr(
        "impl.projects.llm_probe.capability.load_capability_map",
        lambda: mapping,
    )
    spec = load_project("llm_probe")
    *_rest, timeout, response_mode = resolve_http(
        {"body": {"q": 1}, "capability_ref": "stream-no-timeout"},
        spec,
    )
    assert response_mode == "sse_last_frame"
    assert timeout == 180.0
    from impl.projects.llm_probe.live import application_boundary_for

    assert application_boundary_for("json") == {
        "scope": "non_streaming_http_llm_probe",
        "streaming": False,
    }
    assert application_boundary_for("sse_last_frame") == {
        "scope": "sse_last_frame_http_llm_probe",
        "streaming": "sse_last_frame",
    }


def test_resolve_http_expands_capability_header_placeholders(monkeypatch):
    mapping = {
        "dashscope-qa": {
            "capability": "echo",
            "service": {
                "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                "method": "POST",
                "timeout_seconds": 30,
                "response_mode": "sse_last_frame",
                "headers": {
                    "Authorization": "Bearer ${BAILIAN_API_KEY}",
                    "X-DashScope-SSE": "enable",
                },
            },
        }
    }
    monkeypatch.setattr(
        "impl.projects.llm_probe.capability.load_capability_map",
        lambda: mapping,
    )
    monkeypatch.setattr(
        "impl.projects.llm_probe.live.effective_environment_snapshot",
        lambda *_args, **_kwargs: {"BAILIAN_API_KEY": "sk-test-not-real"},
    )
    spec = load_project("llm_probe")
    url, method, headers, _body, _timeout, response_mode = resolve_http(
        {"body": {"q": 1}, "capability_ref": "dashscope-qa"},
        spec,
    )
    assert url.startswith("https://dashscope.aliyuncs.com/")
    assert method == "POST"
    assert response_mode == "sse_last_frame"
    assert headers["Authorization"] == "Bearer sk-test-not-real"
    assert headers["X-DashScope-SSE"] == "enable"
