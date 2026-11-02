"""扩展评估轴专用的 LLM 客户端外壳（axe-v4 D12）。

两件事，都只作用在扩展轴自己新建的客户端上，不改变公共路由的选择和回退策略：
1. 记账：每次 complete_json 实际命中的端点和模型，供 AxisResult.usage 记录（对照时能看出"这条是备用模型判的"）。
2. 模型策略（config: eval_axes.model_policy / .env: EVAL_AXES_MODEL_POLICY）：
   - any        沿用公共路由的回退：哪个端点可用就用哪个；
   - same_model 只允许与本角色策略同名模型的端点（中转站可不同）；同模型端点都不可用就让本次调用失败，不换模型顶替。

实现方式是给客户端换一个路由"视图"：健康/冷却状态仍走公共路由（与生产共享），
视图只在选端点时按模型过滤，并把 record_success / record_failure 顺手记下来。
"""
from __future__ import annotations

from typing import Any, Collection, Optional

from impl.core.config import get_runtime_config
from impl.core.llm_router import LlmEndpoint, LlmRouter

MODEL_POLICY_ANY = "any"
MODEL_POLICY_SAME_MODEL = "same_model"
# 没有可用端点时的退避等待（秒）；总和须超过公共路由冷却时长（180s），保证至少再试一次。
ENDPOINT_WAIT_SECONDS: tuple[float, ...] = (30.0, 60.0, 120.0)


def model_policy() -> str:
    return get_runtime_config().eval_axes.model_policy


class _RouterView:
    """LlmRouter 的过滤 + 记账视图。接口与 LlmRouter 在 complete_json 用到的部分一致。"""

    def __init__(self, inner: LlmRouter, *, allowed_model: Optional[str], recorder: "AxisLlm") -> None:
        self._inner = inner
        self._allowed_model = allowed_model
        self._recorder = recorder

    def _blocked(self) -> set[str]:
        if self._allowed_model is None:
            return set()
        return {ep.name for ep in self._inner.endpoints if ep.model != self._allowed_model}

    @property
    def endpoints(self) -> list[LlmEndpoint]:
        blocked = self._blocked()
        return [ep for ep in self._inner.endpoints if ep.name not in blocked]

    def __len__(self) -> int:
        return len(self.endpoints)

    def refresh_health_if_stale(self) -> None:
        # A same-model run has no cross-model routing decision to make. An
        # optimistic request is more informative than a slow probe that can
        # cool the only eligible endpoint before the real request starts.
        if self._allowed_model is None:
            self._inner.refresh_health_if_stale()

    def active_endpoint_names(self) -> list[str]:
        blocked = self._blocked()
        return [name for name in self._inner.active_endpoint_names() if name not in blocked]

    def select(self, *, exclude: Collection[str] = ()) -> LlmEndpoint:
        blocked = self._blocked()
        try:
            return self._inner.select(exclude=set(exclude) | blocked)
        except RuntimeError as exc:
            if blocked:
                raise RuntimeError(
                    f"eval_axes model_policy=same_model: no endpoint serving model "
                    f"{self._allowed_model!r} is available ({exc})"
                ) from exc
            raise

    def unavailable_reason(self) -> str:
        # Diagnostics must obey the same model filter as endpoint selection.
        reason = self._inner.unavailable_reason(exclude=self._blocked())
        if self._allowed_model is not None:
            return f"eval_axes model_policy=same_model（仅允许模型 {self._allowed_model!r}）：{reason}"
        return reason

    def retry_candidate(self, tried: Collection[str], *, prompt_chars: int = 0,
                        needs_tools: bool = False) -> Optional[LlmEndpoint]:
        active = set(self._inner.active_endpoint_names())
        return next((ep for ep in self.endpoints
                     if ep.name in active and ep.name in tried
                     and ep.serves(prompt_chars, needs_tools=needs_tools)), None)

    def record_success(self, endpoint: LlmEndpoint) -> None:
        self._recorder._note_attempt(endpoint, True)
        self._inner.record_success(endpoint)

    def record_failure(self, endpoint: LlmEndpoint) -> None:
        self._recorder._note_attempt(endpoint, False)
        self._inner.record_failure(endpoint)


class AxisLlm:
    """LlmClient 外壳：数调用、记端点/模型、套模型策略；其余属性读写全部透传给内层客户端。"""

    def __init__(self, inner: Any, *, policy: str) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "calls", 0)
        object.__setattr__(self, "attempts", [])
        object.__setattr__(self, "_selected", [])
        allowed = getattr(inner, "model", None) if policy == MODEL_POLICY_SAME_MODEL else None
        if policy == MODEL_POLICY_SAME_MODEL and not allowed:
            raise ValueError("eval_axes model_policy=same_model 需要客户端声明 model")
        router_view = _RouterView(inner.llm_router, allowed_model=allowed, recorder=self)
        inner.llm_router = router_view
        # 离线评测宁可等端点恢复，也不要因瞬时冷却把整条 case 的六轴阻断（本批整理轴失败均为此类）。
        inner.endpoint_wait_seconds = ENDPOINT_WAIT_SECONDS
        if allowed:
            # 当主端点模型与角色模型不一致时，保证 build_model(endpoint=None) 默认取允许的模型端点
            inner.model = allowed

    # ---- 记账 ---------------------------------------------------------------

    def _note_attempt(self, endpoint: LlmEndpoint, ok: bool) -> None:
        self.attempts.append({"endpoint": endpoint.name, "model": endpoint.model, "ok": ok})
        if ok:
            self._selected.append((endpoint.name, endpoint.model))

    def complete_json(self, *args: Any, **kwargs: Any) -> Any:
        object.__setattr__(self, "calls", self.calls + 1)
        return self._inner.complete_json(*args, **kwargs)

    def usage(self) -> dict[str, Any]:
        """写进 AxisResult.usage 的字段。多次调用命中不同模型时用 / 连起来，一眼能看出换过。"""
        models = list(dict.fromkeys(model for _name, model in self._selected))
        endpoints = list(dict.fromkeys(name for name, _model in self._selected))
        return {
            "llm_calls": self.calls,
            "llm_model": "/".join(models),
            "llm_endpoint": "/".join(endpoints),
            "llm_attempts": len(self.attempts),
            "llm_failed_attempts": sum(1 for item in self.attempts if not item["ok"]),
            "model_policy": self.policy,
        }

    # ---- 透传 ---------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)


def axis_llm(spec: Any, *, role: str, **kwargs: Any) -> AxisLlm:
    """扩展轴取 LLM 客户端的唯一入口：project_llm_client 的结果套上外壳。"""
    from impl.core.llm_client import project_llm_client

    return AxisLlm(project_llm_client(spec, role=role, **kwargs), policy=model_policy())


def merge_usage(target: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    """把多次调用（如轴2逐条期望）的记账合并成一份 usage。"""
    target["llm_calls"] = int(target.get("llm_calls") or 0) + int(usage.get("llm_calls") or 0)
    target["llm_attempts"] = int(target.get("llm_attempts") or 0) + int(usage.get("llm_attempts") or 0)
    target["llm_failed_attempts"] = int(target.get("llm_failed_attempts") or 0) + int(usage.get("llm_failed_attempts") or 0)
    for key in ("llm_model", "llm_endpoint"):
        seen = [x for x in str(target.get(key) or "").split("/") if x] + [x for x in str(usage.get(key) or "").split("/") if x]
        target[key] = "/".join(dict.fromkeys(seen))
    target["model_policy"] = usage.get("model_policy") or target.get("model_policy") or ""
    return target
