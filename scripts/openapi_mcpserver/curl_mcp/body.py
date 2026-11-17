"""Resolve whole-value placeholders and merge configured fields into a JSON body."""
import re
from collections.abc import Iterator

from pydantic import JsonValue


def reference(value: str) -> str | None:
    if "${" not in value:
        return None
    match = re.fullmatch(r"\$\{(token|session_id|trace_id|time_utc8|env\.[A-Za-z_][A-Za-z0-9_]*)\}", value)
    if match is None:
        raise ValueError("Use a whole-value ${env.NAME}, ${token}, ${session_id}, ${trace_id} or ${time_utc8} placeholder")
    return match[1]


def references(value: JsonValue) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.startswith("/") or "${" in key:
                raise ValueError("inject_body requires literal field names and nested objects, not JSON pointers")
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)
    elif isinstance(value, str):
        name = reference(value)
        if name is not None:
            yield name


def resolve(value: JsonValue, context: dict[str, str], env: dict[str, str]) -> JsonValue:
    if isinstance(value, dict):
        return {key: resolve(child, context, env) for key, child in value.items()}
    if isinstance(value, list):
        return [resolve(child, context, env) for child in value]
    if isinstance(value, str):
        name = reference(value)
        if name is not None:
            if name.startswith("env."):
                result = env.get(name[4:])
                if result is None or not result.strip():
                    raise ValueError(f"Missing environment variable: {name[4:]}")
                return result
            return context[name]
    return value


def merge(body: dict, fields: dict) -> None:
    for key, value in fields.items():
        if isinstance(value, dict) and value:
            target = body.setdefault(key, {})
            if not isinstance(target, dict):
                raise ValueError("Cannot inject nested fields into a non-object")
            merge(target, value)
        else:
            # Scalars, arrays and explicit empty objects replace the field.
            body[key] = value


def text_references(value: str) -> list[str]:
    # Header text supports prefixes, e.g. Bearer ${token}; values are expanded once.
    parts = re.split(r"(\$\{[^}]*\})", value)
    names = []
    for part in parts:
        if "${" in part:
            names.append(reference(part))
    return names


def render_text(value: str, context: dict[str, str], env: dict[str, str]) -> str:
    text_references(value)
    return re.sub(r"\$\{[^}]*\}", lambda m: resolve(m[0], context, env), value)
