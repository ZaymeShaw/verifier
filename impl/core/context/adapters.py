from __future__ import annotations

import importlib.util
import inspect
import re
from abc import ABC, abstractmethod
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, Optional, Sequence

from .errors import ContextConfigurationError
from .models import ContextUnitRecord
from .runtime import ContextRuntime


class BaseContextAdapter(ABC):
    """Independent context adapter; never writes Registry or Vector Index directly."""

    def __init__(self, project_spec: Any = None):
        self.project_spec = project_spec

    @abstractmethod
    def iter_stable_context_units(self, context: Mapping[str, Any]) -> Iterable[ContextUnitRecord]:
        raise NotImplementedError

    def adapt_dynamic_context(
        self, event: Any, context: Mapping[str, Any]
    ) -> Iterable[ContextUnitRecord]:
        return ()


class ConfiguredContextAdapter(BaseContextAdapter):
    """Adapt explicit stable units from extra.context.units without inventing IDs or descriptions."""

    def __init__(self, project_spec: Any, units: Sequence[Mapping[str, Any]]):
        super().__init__(project_spec)
        self._units = tuple(dict(unit) for unit in units)

    def iter_stable_context_units(self, context: Mapping[str, Any]) -> Iterable[ContextUnitRecord]:
        project_id = str(getattr(self.project_spec, "project_id", "") or "")
        for index, unit in enumerate(self._units):
            if "project_id" in unit and str(unit["project_id"]) != project_id:
                raise ContextConfigurationError(
                    f"extra.context.units[{index}] cannot target another project"
                )
            try:
                configured_roles = unit["roles"]
                if isinstance(configured_roles, (str, bytes)):
                    raise ContextConfigurationError(
                        f"extra.context.units[{index}].roles must be a list of roles"
                    )
                yield ContextUnitRecord(
                    id=unit["id"],
                    name=unit["name"],
                    description=unit["description"],
                    content=unit.get("content"),
                    content_ref=unit.get("content_ref"),
                    project_id=project_id,
                    scope=unit["scope"],
                    roles=tuple(configured_roles),
                    unit_type=unit["unit_type"],
                    source_type=unit["source_type"],
                    status=unit.get("status", "active"),
                    tags=dict(unit.get("tags") or {}),
                )
            except KeyError as exc:
                raise ContextConfigurationError(
                    f"extra.context.units[{index}] is missing required field {exc.args[0]!r}"
                ) from exc


def load_configured_context_adapter(project_spec: Any) -> Optional[ConfiguredContextAdapter]:
    extra = getattr(project_spec, "extra", {}) or {}
    context_config = extra.get("context") if isinstance(extra, Mapping) else None
    units = context_config.get("units") if isinstance(context_config, Mapping) else None
    if units is None:
        return None
    if isinstance(units, (str, bytes)) or not isinstance(units, Sequence):
        raise ContextConfigurationError("extra.context.units must be a list of explicit unit mappings")
    if not units:
        return None
    if not all(isinstance(unit, Mapping) for unit in units):
        raise ContextConfigurationError("every extra.context.units item must be a mapping")
    return ConfiguredContextAdapter(project_spec, units)


def load_project_context_adapter(project_spec: Any) -> Optional[BaseContextAdapter]:
    project_root = Path(str(getattr(project_spec, "root", "") or ""))
    module_path = project_root / "context_adapter.py"
    if not module_path.is_file():
        return None
    project_id = str(getattr(project_spec, "project_id", project_root.name) or project_root.name)
    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", project_id)
    module = _load_module(module_path, f"impl_project_{safe_name}_context_adapter")
    candidates = [
        value
        for value in vars(module).values()
        if inspect.isclass(value)
        and value.__module__ == module.__name__
        and issubclass(value, BaseContextAdapter)
        and value is not BaseContextAdapter
    ]
    if len(candidates) != 1:
        raise TypeError(f"{module_path} must define exactly one BaseContextAdapter subclass")
    return candidates[0](project_spec)


def initialize_context_adapters(
    runtime: ContextRuntime,
    *,
    project_spec: Any,
    public_adapters: Sequence[BaseContextAdapter] = (),
    project_adapters: Sequence[BaseContextAdapter] = (),
) -> Mapping[str, Any]:
    context = {
        "project_id": runtime.project_id,
        "project_root": str(getattr(project_spec, "root", "") or ""),
        "project_spec": project_spec,
    }
    adapters = list(public_adapters) + list(project_adapters)
    records = []
    for adapter in adapters:
        records.extend(adapter.iter_stable_context_units(context))
    result = dict(runtime.register_context_units(records))
    result["adapter_count"] = len(adapters)
    result["record_count"] = len(records)
    result["public_adapters"] = [adapter.__class__.__name__ for adapter in public_adapters]
    result["project_adapters"] = [adapter.__class__.__name__ for adapter in project_adapters]
    return result


def _load_module(path: Path, module_name: str) -> ModuleType:
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"cannot load context adapter: {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module
