"""A2 端点 prompt 容量契约：声明了上限的端点只服务装得下的请求。"""
from dataclasses import replace

from impl.core.config import get_llm_config
from impl.core.llm_client import LlmClient, _ROUTER_REGISTRY
from impl.core.llm_router import LlmEndpoint, LlmRouter
from impl.core.structured_output import StructuredOutputSpec
from tests.test_llm_client_json_extract import _InvestigationOutput


def _isolate(monkeypatch) -> None:
    _ROUTER_REGISTRY.clear()
    monkeypatch.setattr(LlmClient, "_endpoint_probe", staticmethod(lambda _endpoint: True))
    monkeypatch.setattr("impl.core.llm_client._track_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("impl.core.llm_client.time.sleep", lambda _seconds: None)


def test_endpoint_without_declared_capacity_serves_anything():
    endpoint = LlmEndpoint(name="primary", base_url="http://x/v1", model="m", api_key="k")
    assert endpoint.serves(10_000_000)
    assert LlmEndpoint(name="p", base_url="http://x/v1", model="m", api_key="k", max_prompt_chars=1000).serves(1000)
    assert not LlmEndpoint(name="p", base_url="http://x/v1", model="m", api_key="k", max_prompt_chars=1000).serves(1001)


def _drive(monkeypatch, endpoints, route, payload='{"investigation_summary":"ok"}'):

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
            route.append(str(getattr(self.model, "base_url", "")))
            return Result(payload)

    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", FakeOpenAILike)

    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    client.llm_router = LlmRouter(endpoints)
    return client


def test_transient_failure_on_every_endpoint_is_rescued_by_one_last_resort_retry(monkeypatch):
    """实测：可用端点只剩一个时，单次抖动曾让整轴失败（AxisRequestFailed / no untried llm endpoint remains）。"""
    route = []
    failures = {}

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
            url = str(getattr(self.model, "base_url", ""))
            route.append(url)
            failures[url] = failures.get(url, 0) + 1
            if failures[url] == 1:
                raise TimeoutError("provider timeout")
            return Result()

    _isolate(monkeypatch)
    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", FakeOpenAILike)
    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    client.llm_router = LlmRouter([
        LlmEndpoint(name="primary", base_url="http://a/v1", model="m", api_key="k"),
        LlmEndpoint(name="fallback1", base_url="http://b/v1", model="m", api_key="k"),
    ])

    result = client.complete_json(
        "system",
        "user",
        output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert result["investigation_summary"] == "ok"
    assert route == ["http://a/v1", "http://b/v1", "http://a/v1"]


def test_last_resort_gives_every_not_cooling_endpoint_a_second_chance(monkeypatch):
    """实测：优先级高的端点连错两次进冷却后，兜底不能就此放弃——另一个只抖了一次的端点还能救回整轴。"""
    route = []
    failures = {}

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
            url = str(getattr(self.model, "base_url", ""))
            route.append(url)
            failures[url] = failures.get(url, 0) + 1
            if url.endswith("a/v1") or failures[url] == 1:
                raise TimeoutError("provider timeout" if url.endswith("b/v1") else "location error")
            return Result()

    _isolate(monkeypatch)
    monkeypatch.setattr("impl.core.llm_client.Agent", FakeAgent)
    monkeypatch.setattr("impl.core.llm_client.OpenAILike", FakeOpenAILike)
    client = LlmClient(config=replace(get_llm_config(), api_key="test-key"))
    client.llm_router = LlmRouter([
        LlmEndpoint(name="primary", base_url="http://a/v1", model="m", api_key="k"),
        LlmEndpoint(name="fallback1", base_url="http://b/v1", model="m", api_key="k"),
    ])

    result = client.complete_json(
        "system",
        "user",
        output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert result["investigation_summary"] == "ok"
    assert route == ["http://a/v1", "http://b/v1", "http://a/v1", "http://b/v1"]


def test_prompt_over_every_declared_capacity_is_refused_without_calling(monkeypatch):
    route = []
    _isolate(monkeypatch)
    client = _drive(
        monkeypatch,
        [
            LlmEndpoint(name="primary", base_url="http://a/v1", model="m", api_key="k", max_prompt_chars=10),
            LlmEndpoint(name="fallback1", base_url="http://b/v1", model="m", api_key="k", max_prompt_chars=10),
        ],
        route,
    )

    result = client.complete_json(
        "system",
        "x" * 100,
        output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert route == []  # 没有发出任何请求
    assert result["error"] == "llm_request_failed"
    assert "max_prompt_chars" in result["raw_text"]


def test_prompt_too_large_for_primary_routes_to_capacity_fit_fallback(monkeypatch):
    route = []
    _isolate(monkeypatch)
    client = _drive(
        monkeypatch,
        [
            LlmEndpoint(name="primary", base_url="http://small/v1", model="m", api_key="k", max_prompt_chars=10),
            LlmEndpoint(name="fallback1", base_url="http://big/v1", model="m", api_key="k"),
        ],
        route,
    )

    result = client.complete_json(
        "system",
        "x" * 100,
        output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput),
    )

    assert result["investigation_summary"] == "ok"
    assert route == ["http://big/v1"]


def test_tool_incapable_endpoints_are_skipped_for_tool_requests(monkeypatch):
    """声明了 tool_calls=False 的端点不服务带工具的请求：实测本地 cursor 桥把工具调用
    拼成正文标记并拼错工具名，发过去只会拿到废产出、还把废产出当模型结论。"""
    route = []
    _isolate(monkeypatch)
    client = _drive(
        monkeypatch,
        [
            LlmEndpoint(name="primary", base_url="http://no-tools/v1", model="m", api_key="k", tool_calls=False),
            LlmEndpoint(name="fallback1", base_url="http://tools/v1", model="m", api_key="k"),
        ],
        route,
    )
    client.tools = [lambda query: {"ok": True}]

    result = client.complete_json("system", "x" * 10, output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput))

    assert route == ["http://tools/v1"]
    assert result["investigation_summary"] == "ok"


def test_tool_request_refused_when_no_endpoint_declares_tool_support(monkeypatch):
    route = []
    _isolate(monkeypatch)
    client = _drive(
        monkeypatch,
        [
            LlmEndpoint(name="primary", base_url="http://a/v1", model="m", api_key="k", tool_calls=False),
            LlmEndpoint(name="fallback1", base_url="http://b/v1", model="m", api_key="k", tool_calls=False),
        ],
        route,
    )
    client.tools = [lambda query: {"ok": True}]

    result = client.complete_json("system", "x" * 10, output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput))

    assert route == []  # 没有发出任何请求
    assert result["error"] == "llm_request_failed"
    assert "tool_calls" in result["raw_text"]


def test_tool_incapable_endpoint_still_serves_text_only_requests(monkeypatch):
    """工具能力只对带工具的请求生效：不用工具的卷不因为端点不支持工具而被跳过。"""
    route = []
    _isolate(monkeypatch)
    client = _drive(
        monkeypatch,
        [LlmEndpoint(name="primary", base_url="http://no-tools/v1", model="m", api_key="k", tool_calls=False)],
        route,
    )

    result = client.complete_json("system", "x" * 10, output_spec=StructuredOutputSpec.from_dataclass(_InvestigationOutput))

    assert route == ["http://no-tools/v1"]
    assert result["investigation_summary"] == "ok"


def test_fallback_tool_capability_flows_from_config(monkeypatch):
    """配置里声明的端点工具能力必须真的落到路由器端点上（默认全开、只做减法）。"""
    from impl.core.config import get_llm_config
    from dataclasses import replace as dc_replace
    from impl.core.config_schema import LlmFallback

    config = get_llm_config()
    configured = dc_replace(
        config,
        fallbacks=(LlmFallback(base_url="http://x/v1", model="m", api_key="k", tool_calls=False),),
    )
    client = LlmClient(config=configured)
    by_name = {endpoint.name: endpoint for endpoint in client.llm_router.endpoints}
    assert by_name["fallback1"].tool_calls is False
    assert by_name["primary"].tool_calls is True
