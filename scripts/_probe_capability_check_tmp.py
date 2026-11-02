import json
import re
import time
import urllib.request

BASE = "http://192.168.66.18:8045/v1"
KEY = "sk-antigravity"
MODEL = "gemini-3.7-flash-medium"
WAIT_RE = re.compile(r"Wait\s+(\d+)s")
common = {"model": MODEL, "temperature": 0, "max_tokens": 64}

probes = {
    "json_mode": {**common,
        "messages": [{"role": "user", "content": "Return exactly one JSON object with key ok and boolean true."}],
        "response_format": {"type": "json_object"}},
    "tool_calls": {**common,
        "messages": [{"role": "user", "content": "Call the capability_probe tool once with ok=true."}],
        "tools": [{"type": "function", "function": {
            "name": "capability_probe", "description": "Validate tool calling support.",
            "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}}]},
    "reasoning": {**common,
        "messages": [{"role": "user", "content": "Return exactly one JSON object with key ok and boolean true."}],
        "response_format": {"type": "json_object"}, "reasoning_effort": "medium"},
}


def post(payload):
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    for _ in range(8):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            m = WAIT_RE.search(body)
            if m:
                time.sleep(int(m.group(1)) + 1)
                continue
            return {"_http_error": e.code, "_body": body[:200]}
        except Exception as e:
            return {"_error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"_error": "give up after rate-limit backoff"}


for cap, payload in probes.items():
    body = post(payload)
    if "_http_error" in body or "_error" in body:
        print(f"{cap:10s} -> transport fail: {body}")
        continue
    msg = ((body.get("choices") or [{}])[0]).get("message") or {}
    finish = (body.get("choices") or [{}])[0].get("finish_reason")
    content = msg.get("content")
    if cap in {"json_mode", "reasoning"}:
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
            passed = isinstance(parsed, dict) and parsed.get("ok") is True
        except Exception:
            parsed = None
            passed = False
        shown = repr(content)[:120]
    else:
        passed = bool(msg.get("tool_calls"))
        shown = repr(msg.get("tool_calls"))[:120]
    print(f"{cap:10s} -> pass={passed} finish={finish} out={shown}")
