from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .path_contract import LogicalPathRef, PathContractError, PathResolver


_PATH_FIELD = re.compile(
    r"(?:^|_)(?:path|root|location|file|directory|dir|run_report)$"
)
# 机器本地绝对路径的字符串扫描（redact_forbidden_paths 用）
_MACHINE_PATH_TOKEN = re.compile(
    r"(?:/Users|/home|/tmp|/private|/var|/opt|/srv|/work)/[^\s\"'\\]*"
)
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


class PortableArtifactWriter:
    """Low-level portable JSON writer.

    Formal active producers must call :func:`write_active_artifact`, which adds
    family and target validation.  This class deliberately owns only payload
    normalization and atomic persistence.
    """

    def write_json(
        self,
        path: Path,
        payload: Any,
        *,
        lifecycle: str = "derived_active",
    ) -> Path:
        if lifecycle not in {"derived_active", "derived_historical"}:
            raise PathContractError(
                "PATH_WRITER_BYPASS",
                str(path),
                f"unsupported portable artifact lifecycle {lifecycle!r}",
            )
        normalized = (
            self.validate(payload)
            if lifecycle == "derived_active"
            else _normalize_historical_payload(payload, pointer="$")
        )
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target

    def validate(self, payload: Any) -> Any:
        return _normalize_payload(payload, pointer="$")


def write_active_artifact(
    family_id: str,
    path: Path,
    payload: Any,
    *,
    repository_root: Path | None = None,
    context: Any = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Persist one registered formal artifact without importing the registry eagerly."""
    from .active_artifacts import DEFAULT_ACTIVE_ARTIFACT_REGISTRY

    return DEFAULT_ACTIVE_ARTIFACT_REGISTRY.write_json(
        family_id,
        path,
        payload,
        root=repository_root,
        context=context,
        environ=environ,
    )


def write_portable_export(path: Path, payload: Any) -> Path:
    """Write a non-resumable historical export outside the formal artifact graph."""
    repository_root = project_artifact_repository_root(path)
    if repository_root is not None:
        from .active_artifacts import DEFAULT_ACTIVE_ARTIFACT_REGISTRY

        classification = DEFAULT_ACTIVE_ARTIFACT_REGISTRY.classify_path(
            repository_root,
            path,
        )
        if classification in {"active", "unknown_owned"}:
            raise PathContractError(
                "PATH_WRITER_BYPASS",
                str(path),
                "historical exporter cannot target a registered active artifact boundary",
            )
    return PortableArtifactWriter().write_json(
        path,
        payload,
        lifecycle="derived_historical",
    )


def project_artifact_repository_root(path: Path) -> Path | None:
    """Return the verifier root owning an ``impl/projects`` registry."""
    target = Path(path).resolve(strict=False)
    for candidate in (target, *target.parents):
        projects = candidate / "impl" / "projects"
        if projects.is_dir() and target.is_relative_to(candidate):
            return candidate
    return None


def resolve_logical_refs_in_payload(value: Any, resolver: PathResolver) -> Any:
    """Hydrate persisted logical references for an opaque runtime payload.

    This is intentionally opt-in.  Formal schemas keep ``LogicalPathRef``
    structured; captured business payloads may call this at their consumer
    boundary when the original runtime API expects a physical string.
    """
    if isinstance(value, Mapping):
        if _is_logical_path_ref(value):
            reference = LogicalPathRef.from_mapping(value)
            return str(
                reference.resolve(
                    resolver,
                    expected_type="any",
                    must_exist=False,
                ).physical
            )
        return {
            key: resolve_logical_refs_in_payload(item, resolver)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [resolve_logical_refs_in_payload(item, resolver) for item in value]
    if isinstance(value, tuple):
        return tuple(resolve_logical_refs_in_payload(item, resolver) for item in value)
    return value


def _normalize_historical_payload(value: Any, *, pointer: str) -> Any:
    if isinstance(value, LogicalPathRef):
        return dict(value.to_mapping())
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PathContractError(
                    "PATH_SCHEMA_BYPASS",
                    pointer,
                    "artifact object keys must be strings",
                )
            result[key] = _normalize_historical_payload(
                item,
                pointer=f"{pointer}.{key}",
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            _normalize_historical_payload(item, pointer=f"{pointer}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise PathContractError(
        "PATH_SCHEMA_BYPASS",
        pointer,
        f"unsupported artifact value type {type(value).__name__}",
    )


def _normalize_payload(value: Any, *, pointer: str, field_name: str = "") -> Any:
    if isinstance(value, LogicalPathRef):
        return dict(value.to_mapping())
    if isinstance(value, Mapping):
        if _is_logical_path_ref(value):
            try:
                return dict(LogicalPathRef.from_mapping(value, field_path=pointer).to_mapping())
            except PathContractError:
                raise
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PathContractError("PATH_SCHEMA_BYPASS", pointer, "artifact object keys must be strings")
            result[key] = _normalize_payload(item, pointer=f"{pointer}.{key}", field_name=key)
        return result
    if isinstance(value, (list, tuple)):
        return [
            _normalize_payload(item, pointer=f"{pointer}[{index}]", field_name=field_name)
            for index, item in enumerate(value)
        ]
    if isinstance(value, Path):
        raise PathContractError("PATH_SCHEMA_BYPASS", pointer, "Path objects must be converted to LogicalPathRef")
    if isinstance(value, str):
        if _is_absolute_path(value) and (
            _PATH_FIELD.search(field_name)
            or (_is_machine_absolute_path(value) and _is_standalone_path(value))
        ):
            raise PathContractError("PATH_SCHEMA_BYPASS", pointer, "physical absolute path is forbidden")
        if value and _PATH_FIELD.search(field_name) and _looks_like_path(value):
            raise PathContractError(
                "PATH_SCHEMA_BYPASS",
                pointer,
                "active artifact path fields must use LogicalPathRef",
            )
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise PathContractError(
        "PATH_SCHEMA_BYPASS",
        pointer,
        f"unsupported artifact value type {type(value).__name__}",
    )


def redact_forbidden_paths(value: Any, *, field_name: str = "") -> Any:
    """把路径契约会拒绝的内容换成占位符，供「必须落档但不能带本机路径」的记录类产物使用。

    只隐去契约真会拒绝的部分（用同一套谓词，不另写一份口径，否则两边迟早跑偏）：
    路径字段里的绝对路径、以及任何位置的独立机器绝对路径。相对引用（turn1/records/run）
    和普通字符串原样保留。
    """
    if isinstance(value, Mapping):
        return {
            str(key): redact_forbidden_paths(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_forbidden_paths(item, field_name=field_name) for item in value]
    if isinstance(value, str):
        text = _MACHINE_PATH_TOKEN.sub("<绝对路径已隐去>", value)
        if _is_absolute_path(text) and (
            _PATH_FIELD.search(field_name)
            or (_is_machine_absolute_path(text) and _is_standalone_path(text))
        ):
            return "<绝对路径已隐去>"
        return text
    return value


def _is_logical_path_ref(value: Mapping[str, Any]) -> bool:
    return "location_scope" in value or (
        set(value) >= {"location_scope", "location"}
    )


def _is_absolute_path(value: str) -> bool:
    text = value.strip()
    return bool(
        text.startswith(("/", "~/", "file://", "\\\\"))
        or _WINDOWS_ABSOLUTE.match(text)
    )


def _is_machine_absolute_path(value: str) -> bool:
    text = value.strip()
    return bool(
        text.startswith(("/Users/", "/home/", "/tmp/", "/private/", "/var/", "/opt/", "/srv/", "/work/", "~/", "file://", "\\\\"))
        or _WINDOWS_ABSOLUTE.match(text)
    )


def _is_standalone_path(value: str) -> bool:
    return bool(value.strip()) and not any(character.isspace() for character in value.strip())


def _looks_like_path(value: str) -> bool:
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return False
    return bool(
        "/" in text
        or "\\" in text
        or text.endswith((".py", ".json", ".yaml", ".yml", ".md", ".txt"))
    )
