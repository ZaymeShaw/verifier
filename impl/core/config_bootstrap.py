from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, MutableMapping

from .config_schema import ConfigError, EnvironmentRegistry


_DOTENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_INTERPOLATION = re.compile(r"\$\{|\$\(|\$[A-Za-z_]|`")


def parse_dotenv(path: Path) -> Dict[str, str]:
    """Parse the verifier's deliberately restricted, literal dotenv subset."""
    if not path.exists():
        return {}
    if not path.is_file():
        raise ConfigError(f"dotenv path is not a file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"dotenv must be UTF-8: {path}") from exc

    values: Dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        if not raw_line or raw_line.startswith("#"):
            continue
        if raw_line.startswith("export "):
            raise ConfigError(f"dotenv line {line_number}: export prefix is not supported")
        match = _DOTENV_LINE.fullmatch(raw_line)
        if match is None:
            raise ConfigError(f"dotenv line {line_number}: expected KEY=value without surrounding spaces")
        name, raw_value = match.groups()
        if name in values:
            raise ConfigError(f"dotenv line {line_number}: duplicate key {name}")
        if _INTERPOLATION.search(raw_value):
            raise ConfigError(f"dotenv line {line_number}: interpolation and command substitution are not supported")
        value = _parse_dotenv_value(raw_value, line_number)
        values[name] = value
    return values


def _parse_dotenv_value(raw_value: str, line_number: int) -> str:
    if raw_value.startswith('"'):
        if len(raw_value) < 2 or not raw_value.endswith('"'):
            raise ConfigError(f"dotenv line {line_number}: unterminated double-quoted value")
        inner = raw_value[1:-1]
        result: list[str] = []
        index = 0
        while index < len(inner):
            char = inner[index]
            if char != "\\":
                result.append(char)
                index += 1
                continue
            index += 1
            if index >= len(inner) or inner[index] not in {'"', "\\"}:
                raise ConfigError(
                    f"dotenv line {line_number}: only escaped quote and backslash are supported in quoted values"
                )
            result.append(inner[index])
            index += 1
        return "".join(result)
    if '"' in raw_value:
        raise ConfigError(f"dotenv line {line_number}: quotes must wrap the complete value")
    if "#" in raw_value:
        raise ConfigError(f"dotenv line {line_number}: inline comments are not supported; quote literal #")
    if raw_value != raw_value.strip():
        raise ConfigError(f"dotenv line {line_number}: quote values with leading or trailing spaces")
    return raw_value


def render_env_example(environment: EnvironmentRegistry) -> str:
    lines = [
        "# Generated from all registered verifier configuration domains. Do not add unregistered variables.",
        "# Copy required local values to .env; never commit .env.",
        "",
    ]
    for variable in environment.variables.values():
        lines.append(f"# {variable.description}")
        lines.append(
            f"# type={variable.type}; required={'true' if variable.required else 'false'}; "
            f"secret={'true' if variable.secret else 'false'}; bind={variable.bind}"
        )
        lines.append(f"{variable.name}=")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def bootstrap_dependency_environment(api_key: str, environ: MutableMapping[str, str]) -> None:
    """Populate dependency compatibility state without creating an input config source."""
    if api_key and not environ.get("OPENAI_API_KEY"):
        environ["OPENAI_API_KEY"] = api_key
