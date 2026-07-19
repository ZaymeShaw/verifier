from __future__ import annotations


class ContextRuntimeError(Exception):
    """Base error for the governed context runtime."""


class ContextValidationError(ContextRuntimeError, ValueError):
    """A context model or request violates the public protocol."""


class ContextConfigurationError(ContextRuntimeError):
    """The runtime is missing or has invalid configuration."""


class ContextAuthorizationError(ContextRuntimeError, PermissionError):
    """A search or load request exceeds the resolved run policy."""


class ContextBudgetError(ContextRuntimeError):
    """A search or load request exceeds a deterministic budget."""


class ContextNotFoundError(ContextRuntimeError, LookupError):
    """A requested ContextUnitRecord does not exist."""


class ContextResolutionError(ContextRuntimeError):
    """A content_ref cannot be resolved safely."""


class ContextRegistrationConflictError(ContextRuntimeError):
    """Concurrent or cross-project registration produced a conflict."""
