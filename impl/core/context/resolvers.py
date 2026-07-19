from __future__ import annotations

from pathlib import Path
from typing import Iterable, List
from urllib.parse import unquote, urlparse

from .errors import ContextResolutionError
from .models import ContextUnitRecord


class CompositeContentResolver:
    def __init__(self, resolvers: Iterable[object] = ()):
        self._resolvers: List[object] = list(resolvers)

    def add(self, resolver: object) -> None:
        self._resolvers.append(resolver)

    def resolve(self, content_ref: str, record: ContextUnitRecord) -> str:
        for resolver in self._resolvers:
            can_resolve = getattr(resolver, "can_resolve", None)
            if callable(can_resolve) and can_resolve(content_ref):
                content = resolver.resolve(content_ref, record)
                if not isinstance(content, str) or not content.strip():
                    raise ContextResolutionError(f"resolver returned empty content for {record.id}")
                return content
        raise ContextResolutionError(f"no content resolver registered for: {content_ref}")


class FileContentResolver:
    def __init__(self, allowed_roots: Iterable[Path]):
        roots = []
        for root in allowed_roots:
            resolved = Path(root).expanduser().resolve()
            if resolved not in roots:
                roots.append(resolved)
        if not roots:
            raise ContextResolutionError("file resolver requires at least one allowed root")
        self._allowed_roots = tuple(roots)

    def can_resolve(self, content_ref: str) -> bool:
        return str(content_ref).startswith("file://")

    def resolve(self, content_ref: str, record: ContextUnitRecord) -> str:
        parsed = urlparse(content_ref)
        if parsed.scheme != "file":
            raise ContextResolutionError(f"unsupported file reference: {content_ref}")
        raw_path = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc != "localhost":
            # Treat file://docs/guide.md as a project-relative reference, never as a remote host.
            candidate = Path(parsed.netloc) / raw_path.lstrip("/")
        else:
            candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self._allowed_roots[0] / candidate
        resolved = candidate.expanduser().resolve()
        if not any(_is_relative_to(resolved, root) for root in self._allowed_roots):
            raise ContextResolutionError(f"file reference escapes allowed roots: {content_ref}")
        if not resolved.is_file():
            raise ContextResolutionError(f"referenced content file does not exist: {resolved}")
        return resolved.read_text(encoding="utf-8")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
