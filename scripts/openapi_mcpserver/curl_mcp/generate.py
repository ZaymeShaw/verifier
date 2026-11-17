"""Offline sample-to-schema conversion; never used during server startup."""
import argparse
import copy
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from .curl import parse_command
from .body import references, text_references
from .config import CurlAuth

from genson import SchemaBuilder
from jsonschema import Draft202012Validator


def parse_curl(command: str) -> tuple[str, dict]:
    args = parse_command(command)
    urls = [args.url]
    if args.url_query or args.data_urlencode:
        raise ValueError("Business imports support JSON POST bodies only")
    try:
        url = urlsplit(urls[0])
    except ValueError:
        raise ValueError("Invalid HTTP(S) URL") from None
    if (url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("URL must be HTTP(S) without credentials, query parameters, or fragment")
    if args.request is not None and args.request != "POST":
        raise ValueError("Only JSON POST requests are supported")
    for header in args.header:
        key, separator, value = header.partition(":")
        if not separator:
            raise ValueError("Headers must use name:value; header files are not supported")
        if key.strip().lower() == "content-type" and value.strip().lower().split(";", 1)[0] != "application/json":
            raise ValueError("Only application/json request bodies are supported")
    bodies = args.body or args.json
    if not bodies or len(bodies) != 1 or bodies[0].startswith("@"):
        raise ValueError("Provide one inline JSON body; repeated data flags and @file are not supported")
    try:
        body = json.loads(bodies[0], object_pairs_hook=unique_keys, parse_constant=reject_constant)
    except ValueError:
        raise ValueError("Body must be valid JSON with unique keys; variables and shell expressions are not expanded") from None
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    path = url.path or "/"
    if any(char in path for char in "{}[]") or any(char.isspace() for char in path) or "$" in path or "`" in path:
        raise ValueError("URL must contain a literal path, without templates or shell expressions")
    return urls[0], body


def reject_constant(value: str):
    raise ValueError("Non-finite numbers are not valid JSON")


def mark_for_review(schema: dict) -> None:
    """Observed presence isn't a required/default contract. Leave semantics for review."""
    schema["description"] = "待补充"
    schema.pop("required", None)
    if schema.get("type") == "null":
        # A lone null gives no evidence of the field's non-null type.
        schema.pop("type")
        schema["x-review"] = "样例只有 null，需确认字段类型及是否允许 null"
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        schema["additionalProperties"] = not bool(properties)
        for child in properties.values():
            mark_for_review(child)
    if schema.get("type") == "array":
        if not schema.get("items"):
            schema["x-review"] = "样例是空数组，需补充 items 类型"
        mark_for_review(schema.setdefault("items", {}))
    for child in schema.get("anyOf", []):
        mark_for_review(child)


def generate(command: str, name: str | None = None) -> dict:
    url, body = parse_curl(command)
    return generate_spec(url, body, name)


def generate_spec(url: str, body: dict, name: str | None = None) -> dict:
    path = urlsplit(url).path or "/"
    name = name or "post_" + (re.sub(r"[^A-Za-z0-9_]+", "_", path).strip("_") or "root")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", name):
        raise ValueError("Invalid operationId; use letters, digits, underscore, dot or hyphen")
    builder = SchemaBuilder(schema_uri=False)
    builder.add_object(body)
    schema = builder.to_schema()
    mark_for_review(schema)
    Draft202012Validator.check_schema(schema)
    return {
        "openapi": "3.1.0",
        "info": {"title": "待补充", "version": "0.1.0", "description": "待补充"},
        "servers": [{"url": "http://openapi.invalid"}],
        "x-review": [
            "仅从请求 body 推断结构；所有描述待补充",
            "未推断 required、default、enum、业务限制或响应结构，需人工确认",
            "未导入原地址、Header、Cookie、用户凭据及网络选项；请在运行配置中设置目标地址、鉴权和超时",
            "生成的请求类型为 application/json；原 cURL 未声明 Content-Type 时请确认接口契约",
            "工号、Token 等可信或敏感 body 字段应移出工具参数，交由运行配置注入",
        ],
        "paths": {path: {"post": {
            "operationId": name,
            "summary": "待补充",
            "description": "待补充",
            "requestBody": {"required": True, "content": {"application/json": {"schema": schema}}},
            "responses": {"200": {"description": "待补充"}},
        }}},
    }


def generate_project(curl_dir: Path, *, token_path: str | None = None) -> tuple[dict, dict]:
    if not curl_dir.is_dir():
        raise ValueError("Input must be a directory containing one cURL per .txt file")
    files = sorted(curl_dir.glob("*.txt"))
    if not files:
        raise ValueError("No .txt cURL samples found")
    if token_path is not None:
        CurlAuth(curl="check.txt", token_path=token_path)
    spec = None
    operations = {}
    for source in files:
        name = source.stem
        # Keep filenames identical to FastMCP tool names (no truncation or slug rewriting).
        if len(name) > 56 or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", name):
            raise ValueError(f"{source.name}: use a lowercase snake_case tool name, at most 56 characters")
        try:
            command = source.read_text(encoding="utf-8")
            url, body = parse_curl(command)
            body, injected = split_bindings(body)
            headers = {}
            for header in parse_command(command).header:
                key, _, value = header.partition(":")
                if text_references(value.strip()):
                    if key.strip().lower() in {k.lower() for k in headers}:
                        raise ValueError("Duplicate templated header")
                    headers[key.strip()] = value.strip()
            operation = {"url": url, "auth": "待填写"}
            if (curl_dir.parent / "auth_curls" / source.name).is_file():
                operation["auth"] = {"curl": f"auth_curls/{source.name}",
                                     "token_path": token_path or "待填写"}
            if headers:
                operation["headers"] = headers
            if injected:
                operation["inject_body"] = injected
            item = generate_spec(url, body, name)
            if injected and not body:
                item["paths"][urlsplit(url).path or "/"]["post"]["requestBody"]["content"]["application/json"]["schema"]["additionalProperties"] = False
        except ValueError as exc:
            raise ValueError(f"{source.name}: {exc}") from None
        path = next(iter(item["paths"]))
        if spec is None:
            spec = item
        else:
            if path in spec["paths"]:
                previous = spec["paths"][path]["post"]["operationId"]
                raise ValueError(f"Duplicate POST path in {previous}.txt and {source.name}; different hosts do not disambiguate tools")
            spec["paths"].update(item["paths"])
        operations[name] = operation
    return spec, {"version": 1, "name": curl_dir.parent.name,
                  "openapi": "openapi.draft.json", "operations": operations}


def split_bindings(body: dict) -> tuple[dict, dict]:
    """Only explicitly marked variables are hidden from model parameters."""
    arguments, injected = {}, {}
    for key, value in body.items():
        if isinstance(value, dict) and value:
            fields, bindings = split_bindings(value)
            if fields:
                arguments[key] = fields
            if bindings:
                injected[key] = bindings
        elif list(references(value)):
            injected[key] = value
        else:
            arguments[key] = value
    return arguments, injected


def write_drafts(output_dir: Path, spec: dict, config: dict, *, source_dir: Path | None = None) -> None:
    config = copy.deepcopy(config)
    if source_dir is not None:
        source_dir = source_dir.resolve()
        for operation in config["operations"].values():
            auth = operation.get("auth")
            if isinstance(auth, dict):
                source = (source_dir / auth["curl"]).resolve()
                if not source.is_file():
                    raise ValueError("Referenced auth cURL file does not exist")
                auth["curl"] = os.path.relpath(source, output_dir.resolve())
    outputs = {
        output_dir / "openapi.draft.json": json.dumps(spec, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        output_dir / "config.draft.yaml": (
            "# auth: {curl: auth_curls/name.txt, token_path: /access_token}, file.py:function, or null.\n"
            "# auth returns invocation-local ${token}; reference it explicitly in headers or inject_body.\n"
            "# Move trusted body fields from OpenAPI into inject_body before publishing tools.\n"
            + yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
        ),
    }
    for path in outputs:
        if path.exists() or path.is_symlink():
            raise ValueError(f"Refusing to overwrite {path}; choose a new --output-dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, encoded in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as target:
                created.append(path)
                target.write(encoded)
    except OSError:
        for path in created:
            path.unlink()
        raise


def unique_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description="curls/*.txt → matching OpenAPI and YAML drafts (offline)")
    parser.add_argument("curl_dir", type=Path, nargs="?", default=Path("curls"),
                        help="Directory with one Bash-style JSON POST cURL per tool_name.txt")
    parser.add_argument("--output-dir", type=Path, help="Draft destination; defaults to the parent of curls/")
    parser.add_argument("--token-path", help="Confirmed JSON Pointer for matching auth_curls files, e.g. /access_token")
    args = parser.parse_args()
    output = args.output_dir or args.curl_dir.resolve().parent
    try:
        spec, config = generate_project(args.curl_dir.resolve(), token_path=args.token_path)
        write_drafts(output, spec, config, source_dir=args.curl_dir.resolve().parent)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Generated {len(config['operations'])} tools:")
    print(output / "openapi.draft.json")
    print(output / "config.draft.yaml")
    print("Fill auth references and review schemas/inject_body before running server.py --check.")
