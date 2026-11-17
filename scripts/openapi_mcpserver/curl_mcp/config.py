"""Small deployment configuration; OpenAPI remains the tool schema source."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, PrivateAttr, model_validator

from .body import references, text_references


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class CurlAuth(Strict):
    curl: str
    # JSON Pointer into the auth response; its value becomes invocation-local ${token}.
    token_path: str

    @model_validator(mode="after")
    def check(self):
        if not self.curl or not self.token_path.startswith("/") or re.search(r"~(?![01])", self.token_path):
            raise ValueError("curl and a JSON Pointer token_path are required")
        return self


class Operation(Strict):
    url: str
    # Required explicitly: null means intentional anonymous access.
    auth: CurlAuth | str | None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    inject_body: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check(self):
        if isinstance(self.auth, str):
            file, separator, function = self.auth.rpartition(":")
            if not separator or not file.endswith(".py") or not function.isidentifier():
                raise ValueError("auth must be a Python file:function")
        names = list(references(self.inject_body))
        seen = set()
        for header, value in self.headers.items():
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", header):
                raise ValueError("Invalid header name")
            if header.lower() in seen or header.lower() in {"host", "content-length", "connection", "transfer-encoding", "content-type", "accept-encoding"}:
                raise ValueError("Duplicate or reserved transport header")
            seen.add(header.lower())
            if "\r" in value or "\n" in value:
                raise ValueError("Invalid header value")
            names.extend(text_references(value))
        if "token" in names and self.auth is None:
            raise ValueError("${token} requires auth")
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Endpoint must be an HTTP(S) URL without userinfo or fragment")
        return self


class Settings(Strict):
    version: Literal[1] = 1
    name: str = "insurance-http-tools"
    openapi: str = "openapi.json"
    _project_dir: Path = PrivateAttr(default_factory=Path.cwd)
    operations: dict[str, Operation]


def validate_environment(settings: Settings, env: dict[str, str]) -> None:
    """Report all missing deployment variables before publishing any tools."""
    required = {name[4:] for op in settings.operations.values()
                for name in references(op.inject_body) if name.startswith("env.")}
    required.update(name[4:] for op in settings.operations.values() for value in op.headers.values()
                    for name in text_references(value) if name.startswith("env."))
    missing = sorted(name for name in required if not env.get(name, "").strip())
    if missing:
        raise ValueError("Missing environment variables: " + ", ".join(missing))


def load(path: Path) -> tuple[Settings, dict]:
    settings = Settings.model_validate(yaml.safe_load(path.read_text()))
    settings._project_dir = path.resolve().parent
    spec = json.loads((path.parent / settings.openapi).read_text())
    # Explicit v1 scope. Fail visibly instead of silently mis-routing unsupported shapes.
    for route, item in spec["paths"].items():
        if "{" in route or set(item) != {"post"}:
            raise ValueError("v1 supports literal paths with one JSON POST operation")
        operation = item["post"]
        if operation.get("parameters") or operation.get("callbacks"):
            raise ValueError("v1 supports JSON body inputs; parameters/callbacks need an adapter")
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        if '"$ref"' in json.dumps(schema):
            raise ValueError("v1 requires inline request schemas (resolve $ref first)")
        if schema.get("type") != "object":
            raise ValueError("v1 request body must be a JSON object")
    ids = [op["operationId"] for item in spec["paths"].values()
           for method, op in item.items() if method.lower() in {"get", "post", "put", "patch", "delete"}]
    if len(set(ids)) != len(ids) or set(ids) != set(settings.operations):
        raise ValueError("OpenAPI operationIds and configured operations must match exactly")
    return settings, spec
