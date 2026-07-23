from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict
from urllib.parse import urljoin

from .config_schema import ConfigError
from .schema import ProjectSpec


def call_project_api(spec: ProjectSpec, request: Dict[str, Any]) -> Any:
    api = spec.service("primary")
    missing = [
        name
        for name in ("base_url", "endpoint", "method", "timeout_seconds")
        if api.get(name) in (None, "")
    ]
    if missing:
        raise ConfigError(
            f"project {spec.project_id} primary service is missing configured fields: {', '.join(missing)}"
        )
    base = str(api["base_url"]).rstrip("/") + "/"
    endpoint = str(api["endpoint"]).lstrip("/")
    method = str(api["method"]).upper()
    headers = {"Content-Type": "application/json"}
    headers.update(dict(api.get("headers") or {}))
    url = urljoin(base, endpoint)
    body = json.dumps(request, ensure_ascii=False).encode("utf-8") if method != "GET" else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=float(api["timeout_seconds"])) as resp:
        text = resp.read().decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def get_json(url: str, *, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
