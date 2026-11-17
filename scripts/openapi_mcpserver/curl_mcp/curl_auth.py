"""Read a trusted authentication cURL once; fetch a fresh token for each invocation."""
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx2 as httpx

from .body import references, render_text, resolve, text_references
from .curl import parse_command
from .http import request_json


def validate_token(token):
    if (not isinstance(token, str) or not token or len(token) > 8192
            or any(ord(char) < 33 or ord(char) > 126 for char in token)):
        raise ValueError("Auth must return a nonempty token string")
    return token


def select_token(body, path):
    for part in path[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(body, list):
            if not key.isdecimal() or (len(key) > 1 and key.startswith("0")):
                raise ValueError("Invalid array index in token_path")
            body = body[int(key)]
        else:
            body = body[key]
    return validate_token(body)


@dataclass
class CurlToken:
    method: str
    url: str
    kwargs: dict
    token_path: str

    async def token(self, client):
        raw = await request_json(client, self.method, self.url, **self.kwargs)
        return select_token(raw, self.token_path)


def load_curl(project_dir: Path, filename: str, token_path: str, env: dict[str, str]) -> CurlToken:
    path = (project_dir / filename).resolve()
    # Trusted deployment configuration may reference a shared file relative to its YAML.
    args = parse_command(path.read_text())
    # Unlike an offline business sample, these options would affect a live request.
    if args.insecure or args.location or args.max_time or args.connect_timeout:
        raise ValueError("TLS bypass, redirects and cURL timeouts are unsupported; use the operation timeout")

    def text(value):
        if any(not name.startswith("env.") for name in text_references(value)):
            raise ValueError("Authentication cURL can reference only ${env.NAME}")
        return render_text(value, {}, env)

    def pairs(values):
        result = []
        for value in values:
            key, separator, item = value.partition("=")
            if not separator or not key or "${" in key or key.startswith("@"):
                raise ValueError("Use literal name=value for query/form parameters; @file is unsupported")
            result.append((key, text(item)))
        return result

    # Split query fields before substitution so &, = and non-ASCII credentials stay values.
    raw_url = urlsplit(args.url)
    query = [(key, text(value)) for key, value in parse_qsl(raw_url.query, keep_blank_values=True)]
    base = text(urlunsplit((raw_url.scheme, raw_url.netloc, raw_url.path, "", raw_url.fragment)))
    url = urlsplit(base)
    if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password or url.fragment:
        raise ValueError("Auth URL must be HTTP(S), without userinfo or fragment")
    query.extend(pairs(args.url_query))
    # copy_add_param preserves repeated keys and any query already supplied in an env URL.
    target = httpx.URL(base)
    for key, value in query:
        target = target.copy_add_param(key, value)
    headers = {"accept-encoding": "identity"}
    for header in args.header:
        key, separator, value = header.partition(":")
        key = key.strip().lower()
        if not separator or not key or key in headers or key in {"host", "content-length", "connection", "transfer-encoding"} or "${" in key:
            raise ValueError("Invalid, duplicate or reserved authentication header")
        headers[key] = text(value.strip())
    if args.cookie:
        if "=" not in args.cookie or args.cookie.startswith("@") or "cookie" in headers:
            raise ValueError("Use one inline Cookie header; cookie files are unsupported")
        headers["cookie"] = text(args.cookie)
    if args.user_agent:
        headers["user-agent"] = text(args.user_agent)
    kwargs = {"headers": headers}
    if args.user:
        user, separator, password = args.user.partition(":")
        if not separator or "authorization" in headers:
            raise ValueError("Basic auth requires user:password and no Authorization header")
        kwargs["auth"] = httpx.BasicAuth(text(user), text(password))
    bodies = args.json or args.body
    if bodies:
        if len(bodies) != 1 or bodies[0].startswith("@"):
            raise ValueError("Provide one inline body; @file and repeated data flags are unsupported")
        content_type = headers.get("content-type", "").split(";")[0].strip().lower()
        if args.json or content_type == "application/json":
            if content_type and content_type != "application/json":
                raise ValueError("Conflicting JSON Content-Type")
            data = json.loads(bodies[0])
            if any(not name.startswith("env.") for name in references(data)):
                raise ValueError("Authentication JSON can reference only ${env.NAME}")
            kwargs["json"] = resolve(data, {}, env)
        elif content_type in {"", "application/x-www-form-urlencoded"}:
            fields = [(key, text(value)) for key, value in parse_qsl(bodies[0], keep_blank_values=True, strict_parsing=True)]
            kwargs["content"] = str(httpx.QueryParams(fields)).encode()
            headers["content-type"] = "application/x-www-form-urlencoded"
        else:
            raise ValueError("Only JSON or form authentication bodies are supported")
    elif args.data_urlencode:
        if headers.get("content-type", "application/x-www-form-urlencoded") != "application/x-www-form-urlencoded":
            raise ValueError("Conflicting form Content-Type")
        kwargs["content"] = str(httpx.QueryParams(pairs(args.data_urlencode))).encode()
        headers["content-type"] = "application/x-www-form-urlencoded"
    method = args.request or ("POST" if bodies or args.data_urlencode else "GET")
    if method not in {"GET", "POST"} or (method == "GET" and (bodies or args.data_urlencode)):
        raise ValueError("Authentication supports GET without body or POST")
    return CurlToken(method, str(target), kwargs, token_path)
