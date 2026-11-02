"""llm_probe 的业务 Trace 接入点。

场景只保存稳定信封 ``{provider, config}``。provider 自己负责校验、连通性检查、
关联与采集；扩展轴通过同一个注册表读取 provider 专属证据。
"""
from __future__ import annotations

from typing import Any, Mapping

from .providers import agno, llmtracing

_PROVIDERS = {"agno": agno, "llmtracing": llmtracing}


def provider_descriptions() -> list[dict[str, Any]]:
    return [module.describe() for module in _PROVIDERS.values()]


def validate_business_trace(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("business_trace 必须是对象")
    provider = str(value.get("provider") or "").strip().lower()
    module = _PROVIDERS.get(provider)
    if module is None:
        raise ValueError(f"不支持的 business_trace.provider {provider!r}；当前支持: {', '.join(_PROVIDERS)}")
    config = module.validate_config(value.get("config"))
    return {"provider": provider, "config": config}


def check_connection(value: Any) -> dict[str, Any]:
    clean = validate_business_trace(value)
    return _PROVIDERS[clean["provider"]].check_connection(clean["config"])


def prepare(value: Any, *, case_id: str = "", run_id: str = "") -> dict[str, Any] | None:
    """发业务请求前的可选钩子：返回 {headers, association}；provider 不需要预先关联时返回 None。"""
    clean = validate_business_trace(value)
    hook = getattr(_PROVIDERS[clean["provider"]], "prepare", None)
    return hook(clean["config"], case_id=case_id, run_id=run_id) if hook else None


def collect(value: Any, *, request: Mapping[str, Any], response: Any,
            association: Mapping[str, Any] | None = None) -> dict[str, Any]:
    clean = validate_business_trace(value)
    module = _PROVIDERS[clean["provider"]]
    if hasattr(module, "prepare"):
        return module.collect(clean["config"], request=request, response=response, association=association)
    return module.collect(clean["config"], request=request, response=response)


def open_reader(snapshot: Mapping[str, Any]):
    """Open the provider's deterministic record reader (dossier route); transcript-only providers have none."""
    provider = str(snapshot.get("provider") or "").strip().lower()
    module = _PROVIDERS.get(provider)
    if module is None:
        raise ValueError(f"业务 Trace 快照使用了未注册 provider {provider!r}")
    if not hasattr(module, "open_reader"):
        raise ValueError(f"provider {provider!r} 不走案卷路线，没有 reader")
    return module.open_reader(snapshot)


__all__ = [
    "check_connection",
    "collect",
    "open_reader",
    "prepare",
    "provider_descriptions",
    "validate_business_trace",
]
