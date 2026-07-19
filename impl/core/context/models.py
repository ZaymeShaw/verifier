from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from .errors import ContextValidationError


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _required_content(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_content(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContextValidationError(f"{field_name} must be a non-empty string when provided")
    return value


@dataclass(frozen=True)
class ContextUnit:
    """Complete information returned only after guarded loading."""

    id: str
    name: str
    description: str
    content: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required_text(self.id, "id"))
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "description", _required_text(self.description, "description"))
        object.__setattr__(self, "content", _required_content(self.content, "content"))


@dataclass(frozen=True)
class ContextUnitRecord:
    """Authoritative registration and governance form of a ContextUnit."""

    id: str
    name: str
    description: str
    content: Optional[str]
    content_ref: Optional[str]
    project_id: str
    scope: str
    roles: Tuple[str, ...]
    unit_type: str
    source_type: str
    status: str = "active"
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required_text(self.id, "id"))
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "description", _required_text(self.description, "description"))
        object.__setattr__(self, "project_id", _required_text(self.project_id, "project_id"))
        object.__setattr__(self, "scope", _required_text(self.scope, "scope"))
        object.__setattr__(self, "unit_type", _required_text(self.unit_type, "unit_type"))
        object.__setattr__(self, "source_type", _required_text(self.source_type, "source_type"))
        object.__setattr__(self, "status", _required_text(self.status, "status"))

        content = _optional_content(self.content, "content")
        content_ref = _optional_content(self.content_ref, "content_ref")
        if (content is None) == (content_ref is None):
            raise ContextValidationError("content and content_ref must be provided exclusively")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "content_ref", content_ref)

        if isinstance(self.roles, str):
            raw_roles = (self.roles,)
        else:
            raw_roles = tuple(self.roles or ())
        roles = tuple(dict.fromkeys(_required_text(role, "roles item") for role in raw_roles))
        if not roles:
            raise ContextValidationError("roles must contain at least one role")
        object.__setattr__(self, "roles", roles)

        normalized_tags = {
            _required_text(key, "tags key"): str(value)
            for key, value in dict(self.tags or {}).items()
        }
        object.__setattr__(self, "tags", MappingProxyType(normalized_tags))
