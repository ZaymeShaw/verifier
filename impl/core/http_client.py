from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict
from urllib.parse import urljoin

from .schema import ProjectSpec


def call_project_api(spec: ProjectSpec, request: Dict[str, Any]) -> Any:
    api = spec.api
    base = str(api.get("base_url") or "").rstrip("/") + "/"
    endpoint = str(api.get("endpoint") or "").lstrip("/")
    method = str(api.get("method") or "POST").upper()
    headers = {"Content-Type": "application/json"}
    headers.update(dict(api.get("headers") or {}))
    url = urljoin(base, endpoint)
    body = json.dumps(request, ensure_ascii=False).encode("utf-8") if method != "GET" else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=float(api.get("timeout", 30))) as resp:
        text = resp.read().decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


def get_json(url: str, timeout: float = 10) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
