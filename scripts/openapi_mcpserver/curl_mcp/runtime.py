"""FastMCP handles protocol/schema. This transport binds HTTP and auth config."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx2 as httpx
from jsonschema import Draft202012Validator, ValidationError
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from .body import merge, resolve, render_text
from .config import Settings
from .auth import AuthHandlers, load_handlers
from .http import MAX_BODY, UpstreamFailure, request_json



def fill_defaults(value: Any, schema: dict) -> None:
    """JSON Schema default is descriptive; explicitly apply it before sending HTTP."""
    if isinstance(value, dict):
        for key, child in schema.get("properties", {}).items():
            if key not in value and "default" in child:
                value[key] = copy.deepcopy(child["default"])
            if key in value:
                fill_defaults(value[key], child)
    elif isinstance(value, list):
        for item in value:
            fill_defaults(item, schema.get("items", {}))




class Bridge(httpx.AsyncBaseTransport):
    def __init__(self, settings: Settings, spec: dict, client: httpx.AsyncClient, providers: AuthHandlers, env: dict[str, str]):
        self.env = dict(env)
        self.settings = settings
        self.client = client
        self.routes = {(method.upper(), path): op["operationId"] for path, item in spec["paths"].items()
                       for method, op in item.items() if method.lower() in {"get", "post", "put", "patch", "delete"}}
        self.schemas = {op["operationId"]: op["requestBody"]["content"]["application/json"]["schema"]
                        for item in spec["paths"].values() for method, op in item.items() if method == "post"}
        self.providers = providers

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            name = self.routes[(request.method, request.url.path)]
            op = self.settings.operations[name]
            async with asyncio.timeout(op.timeout_seconds):
                body = json.loads(request.content) if request.content else {}
                fill_defaults(body, self.schemas[name])
                Draft202012Validator(self.schemas[name]).validate(body)
                context = {
                    "session_id": str(uuid.uuid4()),
                    "trace_id": str(uuid.uuid4()),
                    "time_utc8": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
                }
                if op.auth is not None:
                    # This token lives only in this invocation, never in os.environ or .env.
                    context["token"] = await self.providers[name].token(self.client)
                merge(body, resolve(op.inject_body, context, self.env))
                headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
                headers.update({key: render_text(value, context, self.env) for key, value in op.headers.items()})
                if len(json.dumps(body).encode()) > MAX_BODY:
                    raise UpstreamFailure("request_too_large")
                # Only configured target + generated body/query + trusted headers leave this process.
                # Do not forward MCP transport auth or arbitrary incoming headers.
                target = httpx.URL(op.url)
                target = target.copy_merge_params(request.url.params)
                raw = await request_json(self.client, request.method, str(target), json=body, headers=headers)
                return httpx.Response(200, json=raw)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            category = "upstream_timeout"
        except UpstreamFailure as exc:
            category = str(exc)
        except Exception:
            category = "upstream_or_configuration_error"
        return httpx.Response(502, json={"error": category})


class InputValidation(Middleware):
    """Reject unknown arguments before OpenAPI conversion can silently drop them."""
    def __init__(self, schemas: dict[str, dict]):
        self.validators = {name: Draft202012Validator(schema) for name, schema in schemas.items()}

    async def on_call_tool(self, context, call_next):
        validator = self.validators.get(context.message.name)
        if validator is not None:
            try:
                validator.validate(context.message.arguments or {})
            except ValidationError:
                raise ToolError("invalid_tool_arguments: 参数不符合工具 schema") from None
        return await call_next(context)


class Runtime:
    def __init__(self, settings: Settings, spec: dict, transport: httpx.AsyncBaseTransport | None = None, *, env: dict[str, str]):
        # HTTP libraries can log token query strings. This standalone process keeps their
        # logs off; our errors contain only fixed categories.
        for name in ("httpx2", "httpcore2", "httpx", "httpcore"):
            logging.getLogger(name).disabled = True
            logging.getLogger(name).setLevel(logging.CRITICAL)
        # The outer asyncio deadline covers both token acquisition and the whole business response.
        providers = load_handlers(settings, env)
        self.upstream = httpx.AsyncClient(transport=transport, follow_redirects=False, trust_env=False, timeout=None)
        self.bridge = Bridge(settings, spec, self.upstream, providers, env)
        self.client = httpx.AsyncClient(base_url="http://openapi.invalid", transport=self.bridge)
        self.server = FastMCP.from_openapi(openapi_spec=spec, client=self.client, name=settings.name,
                                           validate_output=False, mask_error_details=True)
        self.server.add_middleware(InputValidation(self.bridge.schemas))

    async def aclose(self):
        self.bridge.providers.close()
        await self.client.aclose()
        await self.upstream.aclose()
