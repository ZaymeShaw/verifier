from __future__ import annotations

import copy
import importlib
from dataclasses import fields, is_dataclass
from threading import RLock
from typing import Any, Callable, Dict, Mapping

FixtureFactory = Callable[[], Any]

_REGISTRY: Dict[str, Dict[str, FixtureFactory]] = {}
_CORE_LOADED = False
_CORE_LOAD_LOCK = RLock()


def _class_path(class_path_or_type: str | type) -> str:
    if isinstance(class_path_or_type, str):
        return class_path_or_type
    return f"{class_path_or_type.__module__}.{class_path_or_type.__qualname__}"


def _load_class(class_path_or_type: str | type) -> type:
    if isinstance(class_path_or_type, type):
        return class_path_or_type
    module_name, _, class_name = class_path_or_type.rpartition(".")
    if not module_name or not class_name:
        raise ValueError(f"Invalid fixture class path: {class_path_or_type!r}")
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    if not isinstance(cls, type):
        raise TypeError(f"Fixture target is not a class: {class_path_or_type!r}")
    return cls


def _ensure_core_fixtures_loaded() -> None:
    global _CORE_LOADED
    with _CORE_LOAD_LOCK:
        if _CORE_LOADED:
            return
        importlib.import_module("impl.core.schema.fixture.core_fixtures")
        _CORE_LOADED = True


def register_fixture(class_path_or_type: str | type, scenario: str, factory: FixtureFactory) -> None:
    if not scenario:
        raise ValueError("Fixture scenario cannot be empty")
    if not callable(factory):
        raise TypeError("Fixture factory must be callable")
    class_path = _class_path(class_path_or_type)
    _REGISTRY.setdefault(class_path, {})[scenario] = factory


def available_fixtures(class_path_or_type: str | type | None = None) -> Dict[str, list[str]] | list[str]:
    _ensure_core_fixtures_loaded()
    if class_path_or_type is None:
        return {class_path: sorted(scenarios) for class_path, scenarios in sorted(_REGISTRY.items())}
    class_path = _class_path(class_path_or_type)
    return sorted(_REGISTRY.get(class_path, {}))


def _apply_field_overrides(value: Any, overrides: Mapping[str, Any]) -> Any:
    if not overrides:
        return value
    if is_dataclass(value):
        valid_fields = {item.name for item in fields(value)}
        unknown = [key for key in overrides if key not in valid_fields]
        if unknown:
            raise ValueError(f"Unknown fixture override field(s) for {type(value).__name__}: {', '.join(sorted(unknown))}")
        for key, item in overrides.items():
            setattr(value, key, item)
        return value
    if isinstance(value, dict):
        value.update(overrides)
        return value
    for key, item in overrides.items():
        if not hasattr(value, key):
            raise ValueError(f"Unknown fixture override field for {type(value).__name__}: {key}")
        setattr(value, key, item)
    return value


def load_fixture(
    class_path_or_type: str | type,
    scenario: str = "default",
    *,
    as_dict: bool = False,
    **field_overrides: Any,
) -> Any:
    _ensure_core_fixtures_loaded()
    class_path = _class_path(class_path_or_type)
    scenarios = _REGISTRY.get(class_path, {})
    factory = scenarios.get(scenario)
    if factory is None:
        available = ", ".join(sorted(scenarios)) or "none"
        raise KeyError(f"No fixture registered for {class_path!r} scenario {scenario!r}. Available scenarios: {available}")
    value = copy.deepcopy(factory())
    cls = _load_class(class_path_or_type)
    if not isinstance(value, cls):
        raise TypeError(f"Fixture {class_path!r}/{scenario!r} returned {type(value).__name__}, expected {cls.__name__}")
    value = _apply_field_overrides(value, field_overrides)
    if as_dict:
        from impl.core.schema import to_dict

        return to_dict(value)
    return value
