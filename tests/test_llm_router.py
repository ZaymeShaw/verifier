"""LlmRouter 端点降级状态机单元测试。"""
import time
import threading

import pytest

from impl.core.llm_router import LlmEndpoint, LlmRouter


def _eps(names=("primary", "fb1", "fb2")):
    return [
        LlmEndpoint(name=n, base_url=f"https://{n}/v1", model="m", api_key="k")
        for n in names
    ]


def test_select_prefers_priority_when_all_healthy():
    router = LlmRouter(_eps())
    assert router.select().name == "primary"
    assert router.active_endpoint_names() == ["primary", "fb1", "fb2"]


def test_single_failure_does_not_trip_cooldown():
    router = LlmRouter(_eps())
    router.record_failure(router.endpoints[0])  # 1 failure
    assert router.select().name == "primary"  # threshold=2, not cooled yet


def test_after_threshold_falls_back_to_next():
    router = LlmRouter(_eps())
    router.record_failure(router.endpoints[0])
    router.record_failure(router.endpoints[0])  # reach threshold→cooldown
    assert router.select().name == "fb1"
    assert "fb2" in router.active_endpoint_names()


def test_all_cooled_fails_fast_without_hitting_endpoint_again():
    router = LlmRouter(_eps(), cooldown_seconds=10)
    for ep in router.endpoints:
        router.record_failure(ep)
        router.record_failure(ep)
    with pytest.raises(RuntimeError, match="all llm endpoints are cooling"):
        router.select()
    assert router.active_endpoint_names() == []


def test_success_clears_failure_and_cooldown():
    router = LlmRouter(_eps(), cooldown_seconds=10)
    router.record_failure(router.endpoints[0])
    router.record_failure(router.endpoints[0])
    assert router.select().name == "fb1"
    router.record_success(router.endpoints[0])
    assert router.select().name == "primary"
    h = router._health["primary"]
    assert h.consecutive_failures == 0 and h.cooldown_until == 0.0


def test_requires_at_least_one_endpoint():
    with pytest.raises(ValueError):
        LlmRouter([])


def test_manual_record_never_trips_by_itself():
    # success after one failure resets counter
    router = LlmRouter(_eps())
    router.record_failure(router.endpoints[0])
    router.record_success(router.endpoints[0])
    router.record_failure(router.endpoints[0])
    router.record_failure(router.endpoints[0])
    assert router.select().name == "fb1"


def test_select_excludes_all_previously_tried_endpoints():
    router = LlmRouter(_eps())
    assert router.select(exclude={"primary"}).name == "fb1"
    assert router.select(exclude={"primary", "fb1"}).name == "fb2"


def test_select_exclude_does_not_bypass_cooldown():
    router = LlmRouter(_eps(), cooldown_seconds=60)
    for ep in router.endpoints:
        router.record_failure(ep)
        router.record_failure(ep)
    with pytest.raises(RuntimeError, match="all llm endpoints are cooling"):
        router.select(exclude={"primary"})


def test_select_raises_when_all_endpoints_were_tried():
    router = LlmRouter(_eps(names=("primary",)))
    with pytest.raises(RuntimeError, match="no untried"):
        router.select(exclude={"primary"})


def test_retry_candidate_returns_tried_endpoint_that_is_not_cooling():
    """兜底重试：试过但只是单次抖动的端点还能再试一次；连续失败进了冷却就不再撞。"""
    router = LlmRouter(_eps(), cooldown_seconds=60)
    router.record_failure(router.endpoints[0])
    assert router.retry_candidate({"primary"}).name == "primary"
    router.record_failure(router.endpoints[0])
    assert router.retry_candidate({"primary"}) is None
    assert router.retry_candidate({"fb2"}).name == "fb2"
    assert router.retry_candidate({"primary", "fb1", "fb2"}).name == "fb1"


def test_retry_candidate_skips_endpoints_that_cannot_serve_the_request():
    """兜底也不能把带工具的请求发给声明不支持工具的端点。"""
    router = LlmRouter([
        LlmEndpoint(name="primary", base_url="https://primary/v1", model="m", api_key="k", tool_calls=False),
        LlmEndpoint(name="fb1", base_url="https://fb1/v1", model="m", api_key="k"),
    ])
    assert router.retry_candidate({"primary", "fb1"}, needs_tools=True).name == "fb1"
    assert router.retry_candidate({"primary"}, needs_tools=True) is None


def test_refresh_health_probes_all_stale_endpoints_once():
    probed: list[str] = []

    def probe_fn(ep):
        probed.append(ep.name)
        return True

    router = LlmRouter(_eps(), probe_fn=probe_fn)
    router.refresh_health_if_stale()
    router.refresh_health_if_stale()
    assert sorted(probed) == ["fb1", "fb2", "primary"]


def test_failed_health_probe_enters_cooldown():
    router = LlmRouter(_eps(), probe_fn=lambda ep: ep.name != "fb1", cooldown_seconds=10)
    router.refresh_health_if_stale()
    with router._lock:
        assert router._health["fb1"].in_cooldown(time.monotonic())


def test_concurrent_requests_share_one_probe_round():
    started = threading.Event()
    release = threading.Event()
    probed: list[str] = []
    probe_lock = threading.Lock()

    def probe_fn(ep):
        with probe_lock:
            probed.append(ep.name)
            if len(probed) == 3:
                started.set()
        release.wait(timeout=1)
        return True

    router = LlmRouter(_eps(), probe_fn=probe_fn, probe_wait_seconds=1)
    first = threading.Thread(target=router.refresh_health_if_stale)
    second = threading.Thread(target=router.refresh_health_if_stale)
    first.start()
    assert started.wait(timeout=1)
    second.start()
    release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert sorted(probed) == ["fb1", "fb2", "primary"]


def test_probe_timeout_does_not_block_forever():
    release = threading.Event()
    router = LlmRouter(
        _eps(names=("primary",)),
        probe_fn=lambda ep: release.wait(timeout=1),
        probe_wait_seconds=0.02,
    )

    started = time.monotonic()
    router.refresh_health_if_stale()
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 0.2
    with router._lock:
        assert router._health["primary"].in_cooldown(time.monotonic())
