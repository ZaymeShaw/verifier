import json
import re
import sys
import time
import urllib.request

BASE = "http://192.168.66.18:8045/v1"
KEY = "sk-antigravity"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.7-flash-medium"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 5
WAIT_RE = re.compile(r"Wait\s+(\d+)s")

payload = {
    "model": MODEL, "temperature": 0, "max_tokens": 64,
    "messages": [{"role": "user", "content": "Return exactly one JSON object with key ok and boolean true."}],
    "response_format": {"type": "json_object"},
}


def post():
    req = urllib.request.Request(
        f"{BASE}/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}, method="POST")
    for _ in range(8):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            b = e.read().decode(errors="replace")
            m = WAIT_RE.search(b)
            if m:
                time.sleep(int(m.group(1)) + 1)
                continue
            return {"_err": b[:120]}
        except Exception as e:
            return {"_err": str(e)[:120]}
    return {"_err": "giveup"}


clean = fenced = other = 0
for i in range(N):
    body = post()
    if "_err" in body:
        print(f"run{i}: transport err {body['_err']}")
        other += 1
        continue
    content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content")
    try:
        parsed = json.loads(content) if isinstance(content, str) else content
        strict_ok = isinstance(parsed, dict) and parsed.get("ok") is True
    except Exception:
        strict_ok = False
    has_fence = isinstance(content, str) and content.strip().startswith("```")
    print(f"run{i}: strict_json_loads={strict_ok} fenced={has_fence}  content={repr(content)[:60]}")
    if strict_ok:
        clean += 1
    elif has_fence:
        fenced += 1
    else:
        other += 1
    time.sleep(2)

print(f"\nconfig_check strict verdict: pass {clean}/{N}, fenced-fail {fenced}/{N}, other-fail {other}/{N}")
