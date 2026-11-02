import json
import re
import time
import urllib.request

BASE = "http://192.168.66.18:8045/v1"
KEY = "sk-antigravity"
WAIT_RE = re.compile(r"Wait\s+(\d+)s")

WEAK = "Return exactly one JSON object with key ok and boolean true."
STRONG = WEAK + " Output raw JSON only, no markdown code fences, no prose."

CELLS = [
    ("3.7-medium WEAK  ", "gemini-3.7-flash-medium", WEAK),
    ("3.7-medium STRONG", "gemini-3.7-flash-medium", STRONG),
    ("3.8-medium WEAK  ", "gemini-3.8-flash-medium", WEAK),
    ("3.8-medium STRONG", "gemini-3.8-flash-medium", STRONG),
]


def post(payload, tries=14):
    req = urllib.request.Request(
        f"{BASE}/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}, method="POST")
    for _ in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            b = e.read().decode(errors="replace")
            m = WAIT_RE.search(b)
            if m:
                time.sleep(int(m.group(1)) + 1)
                continue
            return {"_http": e.code, "_body": b[:200]}
        except Exception as e:
            return {"_err": str(e)[:200]}
    return {"_err": "giveup"}


def verdict(body):
    c = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content")
    if c is None:
        return "ERR", None
    s = c.strip()
    if s.startswith("```"):
        return "FENCED", s
    try:
        p = json.loads(s)
        return ("PASS" if isinstance(p, dict) and set(p) == {"ok"} else "ODDJSON"), s
    except Exception:
        return "NOTJSON", s


N = 5
stats = {name: {"PASS": 0, "FENCED": 0, "NOTJSON": 0, "ODDJSON": 0, "ERR": 0} for name, _, _ in CELLS}
detail = {name: [] for name, _, _ in CELLS}

# 交错执行，抵消池子随时间漂移
for i in range(N):
    for name, model, prompt in CELLS:
        body = post({"model": model, "temperature": 0, "max_tokens": 64,
                     "messages": [{"role": "user", "content": prompt}],
                     "response_format": {"type": "json_object"}})
        v, s = verdict(body)
        stats[name][v] += 1
        detail[name].append(v if v != "PASS" else ("PASS" if not s.startswith("```") else "FENCED"))
        print(f"  round{i} {name} -> {v} :: {repr(s)[:46] if s else body}", flush=True)
        time.sleep(1)

print("\n===== 2x2 汇总 (均带 response_format=json_object) =====")
for name, _, _ in CELLS:
    st = stats[name]
    print(f"{name}: PASS={st['PASS']}/{N}  FENCED={st['FENCED']}/{N}  NOTJSON={st['NOTJSON']}  ERR={st['ERR']}")
