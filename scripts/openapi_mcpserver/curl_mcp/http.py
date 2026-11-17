"""Bounded JSON HTTP requests shared by authentication and business calls."""
import json
from typing import Any

import httpx2 as httpx

MAX_BODY = 1024 * 1024


class UpstreamFailure(Exception):
    """Only a fixed error category is exposed to MCP callers."""


async def request_json(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> Any:
    # Stream and bound responses; never expose auth URLs, headers or error bodies.
    async with client.stream(method, url, **kwargs) as response:
        if not 200 <= response.status_code < 300:
            raise UpstreamFailure("upstream_http_error")
        body = bytearray()
        async for part in response.aiter_bytes():
            body.extend(part)
            if len(body) > MAX_BODY:
                raise UpstreamFailure("response_too_large")
    try:
        return json.loads(body)
    except (ValueError, UnicodeError):
        raise UpstreamFailure("invalid_json_response") from None
