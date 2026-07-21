from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from ..config import get_runtime_config
from .errors import ContextAuthorizationError, ContextConfigurationError
from .models import ContextUnitRecord

_ALLOWED_RULE_KEYS = {
    "enabled",
    "allowed_roles",
    "forbidden_roles",
    "allowed_scopes",
    "forbidden_scopes",
    "allowed_unit_types",
    "forbidden_unit_types",
    "allowed_source_types",
    "forbidden_source_types",
    "allowed_statuses",
    "mandatory_ids",
    "candidate_limit",
    "load_limit",
    "content_char_budget",
    "query_limit",
    "top_k_per_query",
}

_context_config = get_runtime_config().context
_DEFAULT_LIMITS = {
    "candidate_limit": _context_config.candidate_limit,
    "load_limit": _context_config.load_limit,
    "content_char_budget": _context_config.content_char_budget,
    "query_limit": _context_config.query_limit,
    "top_k_per_query": _context_config.top_k_per_query,
}


def _as_set(value: Any, field_name: str) -> Optional[FrozenSet[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        items = (value,)
    else:
        items = tuple(value)
    normalized = frozenset(str(item).strip() for item in items if str(item).strip())
    if not normalized:
        return frozenset()
    return normalized


def _restrict(current: Optional[FrozenSet[str]], incoming: Optional[FrozenSet[str]]) -> Optional[FrozenSet[str]]:
    if incoming is None:
        return current
    if current is None:
        return incoming
    return current.intersection(incoming)


def _positive_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ContextConfigurationError(f"{field_name} must be a positive integer") from exc
    if number <= 0:
        raise ContextConfigurationError(f"{field_name} must be a positive integer")
    return number


def _tag_values(tags: Mapping[str, str], singular: str, plural: str) -> FrozenSet[str]:
    value = tags.get(singular) or tags.get(plural) or ""
    return frozenset(item.strip() for item in str(value).split(",") if item.strip())


@dataclass(frozen=True)
class _RunContextPolicy:
    project_id: str
    role: str
    operation: str
    trace_id: str
    run_id: str
    case_id: str
    enabled: bool
    allowed_scopes: Optional[FrozenSet[str]]
    forbidden_scopes: FrozenSet[str]
    allowed_unit_types: Optional[FrozenSet[str]]
    forbidden_unit_types: FrozenSet[str]
    allowed_source_types: Optional[FrozenSet[str]]
    forbidden_source_types: FrozenSet[str]
    allowed_statuses: FrozenSet[str]
    mandatory_ids: Tuple[str, ...]
    candidate_limit: int
    load_limit: int
    content_char_budget: int
    query_limit: int
    top_k_per_query: int

    def assert_enabled(self) -> None:
        if not self.enabled:
            raise ContextAuthorizationError(
                f"context access is disabled for role={self.role!r}, operation={self.operation!r}"
            )

    def permits(self, record: ContextUnitRecord) -> bool:
        if not self.enabled or record.project_id != self.project_id:
            return False
        if self.role not in record.roles:
            return False
        if record.status not in self.allowed_statuses:
            return False
        if record.scope in self.forbidden_scopes:
            return False
        if self.allowed_scopes is not None and record.scope not in self.allowed_scopes:
            return False
        if record.unit_type in self.forbidden_unit_types:
            return False
        if self.allowed_unit_types is not None and record.unit_type not in self.allowed_unit_types:
            return False
        if record.source_type in self.forbidden_source_types:
            return False
        if self.allowed_source_types is not None and record.source_type not in self.allowed_source_types:
            return False

        record_operations = _tag_values(record.tags, "operation", "operations")
        if record_operations and self.operation not in record_operations:
            return False
        if record.tags.get("trace_id") and record.tags.get("trace_id") != self.trace_id:
            return False
        if record.tags.get("run_id") and record.tags.get("run_id") != self.run_id:
            return False
        if record.tags.get("case_id") and record.tags.get("case_id") != self.case_id:
            return False
        return True

    def debug_dict(self) -> Dict[str, Any]:
        def values(item: Optional[FrozenSet[str]]) -> Optional[list]:
            return None if item is None else sorted(item)

        return {
            "project_id": self.project_id,
            "role": self.role,
            "operation": self.operation,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "enabled": self.enabled,
            "allowed_scopes": values(self.allowed_scopes),
            "forbidden_scopes": sorted(self.forbidden_scopes),
            "allowed_unit_types": values(self.allowed_unit_types),
            "forbidden_unit_types": sorted(self.forbidden_unit_types),
            "allowed_source_types": values(self.allowed_source_types),
            "forbidden_source_types": sorted(self.forbidden_source_types),
            "allowed_statuses": sorted(self.allowed_statuses),
            "candidate_limit": self.candidate_limit,
            "load_limit": self.load_limit,
            "content_char_budget": self.content_char_budget,
            "query_limit": self.query_limit,
            "top_k_per_query": self.top_k_per_query,
        }


class ContextPolicyResolver:
    """Resolve public, role, operation, project and run restrictions once per run."""

    def __init__(
        self,
        public_config: Optional[Mapping[str, Any]] = None,
        project_config: Optional[Mapping[str, Any]] = None,
    ):
        self._public_config = dict(public_config or {})
        self._project_config = dict(project_config or {})
        self._validate_config(self._public_config, "public policy")
        self._validate_config(self._project_config, "project policy")

    def resolve(
        self,
        *,
        role: str,
        operation: str,
        project_id: str,
        trace_id: str = "",
        run_id: str = "",
        case_id: str = "",
        run_restrictions: Optional[Mapping[str, Any]] = None,
    ) -> _RunContextPolicy:
        role = str(role or "").strip()
        operation = str(operation or "").strip()
        project_id = str(project_id or "").strip()
        if not role or not operation or not project_id:
            raise ContextConfigurationError("role, operation and project_id are required to resolve context policy")

        public_rules = self._rules_for(self._public_config, role, operation)
        project_rules = self._rules_for(self._project_config, role, operation)
        run_rules = [dict(run_restrictions)] if run_restrictions else []
        if run_rules and "mandatory_ids" in run_rules[0]:
            raise ContextConfigurationError("run restrictions cannot add mandatory context units")
        for rule in public_rules + project_rules + run_rules:
            self._validate_rule(rule)

        public_enabled = any(rule.get("enabled") is True for rule in public_rules)
        enabled = public_enabled
        if any(rule.get("enabled") is False for rule in public_rules + project_rules + run_rules):
            enabled = False

        allowed_roles: Optional[FrozenSet[str]] = None
        forbidden_roles: FrozenSet[str] = frozenset()
        allowed_scopes: Optional[FrozenSet[str]] = None
        forbidden_scopes: FrozenSet[str] = frozenset()
        allowed_unit_types: Optional[FrozenSet[str]] = None
        forbidden_unit_types: FrozenSet[str] = frozenset()
        allowed_source_types: Optional[FrozenSet[str]] = None
        forbidden_source_types: FrozenSet[str] = frozenset()
        allowed_statuses: Optional[FrozenSet[str]] = None
        mandatory_ids = []
        limits = dict(_DEFAULT_LIMITS)

        for rule in public_rules + project_rules + run_rules:
            allowed_roles = _restrict(allowed_roles, _as_set(rule.get("allowed_roles"), "allowed_roles"))
            forbidden_roles = forbidden_roles.union(_as_set(rule.get("forbidden_roles"), "forbidden_roles") or ())
            allowed_scopes = _restrict(allowed_scopes, _as_set(rule.get("allowed_scopes"), "allowed_scopes"))
            forbidden_scopes = forbidden_scopes.union(_as_set(rule.get("forbidden_scopes"), "forbidden_scopes") or ())
            allowed_unit_types = _restrict(
                allowed_unit_types, _as_set(rule.get("allowed_unit_types"), "allowed_unit_types")
            )
            forbidden_unit_types = forbidden_unit_types.union(
                _as_set(rule.get("forbidden_unit_types"), "forbidden_unit_types") or ()
            )
            allowed_source_types = _restrict(
                allowed_source_types, _as_set(rule.get("allowed_source_types"), "allowed_source_types")
            )
            forbidden_source_types = forbidden_source_types.union(
                _as_set(rule.get("forbidden_source_types"), "forbidden_source_types") or ()
            )
            allowed_statuses = _restrict(
                allowed_statuses, _as_set(rule.get("allowed_statuses"), "allowed_statuses")
            )
            for unit_id in sorted(_as_set(rule.get("mandatory_ids"), "mandatory_ids") or ()):
                if unit_id not in mandatory_ids:
                    mandatory_ids.append(unit_id)
            for field_name in _DEFAULT_LIMITS:
                if field_name in rule:
                    limits[field_name] = min(limits[field_name], _positive_int(rule[field_name], field_name))

        if allowed_roles is not None and role not in allowed_roles:
            enabled = False
        if role in forbidden_roles:
            enabled = False

        return _RunContextPolicy(
            project_id=project_id,
            role=role,
            operation=operation,
            trace_id=str(trace_id or ""),
            run_id=str(run_id or ""),
            case_id=str(case_id or ""),
            enabled=enabled,
            allowed_scopes=allowed_scopes,
            forbidden_scopes=forbidden_scopes,
            allowed_unit_types=allowed_unit_types,
            forbidden_unit_types=forbidden_unit_types,
            allowed_source_types=allowed_source_types,
            forbidden_source_types=forbidden_source_types,
            allowed_statuses=allowed_statuses if allowed_statuses is not None else frozenset({"active"}),
            mandatory_ids=tuple(mandatory_ids),
            candidate_limit=limits["candidate_limit"],
            load_limit=limits["load_limit"],
            content_char_budget=limits["content_char_budget"],
            query_limit=limits["query_limit"],
            top_k_per_query=limits["top_k_per_query"],
        )

    @classmethod
    def _validate_config(cls, config: Mapping[str, Any], label: str) -> None:
        unknown = set(config).difference({"default", "roles"})
        if unknown:
            raise ContextConfigurationError(f"unknown {label} sections: {sorted(unknown)}")
        default = config.get("default")
        if default is not None and not isinstance(default, Mapping):
            raise ContextConfigurationError(f"{label}.default must be a mapping")
        if isinstance(default, Mapping):
            cls._validate_rule(default)
        roles = config.get("roles")
        if roles is not None and not isinstance(roles, Mapping):
            raise ContextConfigurationError(f"{label}.roles must be a mapping")
        if not isinstance(roles, Mapping):
            return
        for role, role_rule in roles.items():
            if not isinstance(role_rule, Mapping):
                raise ContextConfigurationError(f"{label}.roles.{role} must be a mapping")
            cls._validate_rule({key: value for key, value in role_rule.items() if key != "operations"})
            operations = role_rule.get("operations")
            if operations is not None and not isinstance(operations, Mapping):
                raise ContextConfigurationError(
                    f"{label}.roles.{role}.operations must be a mapping"
                )
            if isinstance(operations, Mapping):
                for operation, operation_rule in operations.items():
                    if not isinstance(operation_rule, Mapping):
                        raise ContextConfigurationError(
                            f"{label}.roles.{role}.operations.{operation} must be a mapping"
                        )
                    cls._validate_rule(operation_rule)

    @staticmethod
    def _rules_for(config: Mapping[str, Any], role: str, operation: str) -> list:
        rules = []
        default = config.get("default")
        if isinstance(default, Mapping):
            rules.append(dict(default))
        roles = config.get("roles")
        if isinstance(roles, Mapping):
            role_rule = roles.get(role)
            if isinstance(role_rule, Mapping):
                rules.append({key: value for key, value in role_rule.items() if key != "operations"})
                operations = role_rule.get("operations")
                if isinstance(operations, Mapping) and isinstance(operations.get(operation), Mapping):
                    rules.append(dict(operations[operation]))
        return rules

    @staticmethod
    def _validate_rule(rule: Mapping[str, Any]) -> None:
        unknown = set(rule).difference(_ALLOWED_RULE_KEYS)
        if unknown:
            raise ContextConfigurationError(f"unknown context policy fields: {sorted(unknown)}")
