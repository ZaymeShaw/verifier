import json
import re
import time
import urllib.request

BASE = "http://192.168.66.18:8045/v1"
KEY = "sk-antigravity"
MODEL = "gemini-3.8-flash-medium"
WAIT_RE = re.compile(r"Wait\s+(\d+)s")


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
            return {"_http": e.code, "_body": b[:220]}
        except Exception as e:
            return {"_err": str(e)[:220]}
    return {"_err": "giveup-after-backoff"}


def content_of(body):
    return (((body.get("choices") or [{}])[0]).get("message") or {}).get("content")


def reasoning_tokens(body):
    d = (body.get("usage") or {}).get("completion_tokens_details") or {}
    return d.get("reasoning_tokens")


def classify(body):
    c = content_of(body)
    if c is None:
        return {"strict": None, "fenced": None, "err": body.get("_http") or body.get("_body") or body.get("_err")}
    s = c.strip()
    fenced = s.startswith("```")
    try:
        p = json.loads(s)
        strict = isinstance(p, dict)
    except Exception:
        strict = False
    return {"strict": strict, "fenced": fenced, "sample": s[:60]}


JSON_PROMPT = "Return exactly one JSON object with key ok and boolean true. Output raw JSON only, no markdown code fences, no prose."

print(f"model={MODEL}  ts={time.strftime('%H:%M:%S')}", flush=True)

print("\n[1] WITH response_format=json_object", flush=True)
fw = pw = 0
for i in range(5):
    r = classify(post({"model": MODEL, "temperature": 0, "max_tokens": 64,
        "messages": [{"role": "user", "content": JSON_PROMPT}],
        "response_format": {"type": "json_object"}}))
    pw += 1 if r.get("strict") else 0
    fw += 1 if r.get("fenced") else 0
    print(f"  run{i}: {r}", flush=True); time.sleep(1)

print("\n[2] NO response_format (same prompt)", flush=True)
fn = pn = 0
for i in range(5):
    r = classify(post({"model": MODEL, "temperature": 0, "max_tokens": 64,
        "messages": [{"role": "user", "content": JSON_PROMPT}]}))
    pn += 1 if r.get("strict") else 0
    fn += 1 if r.get("fenced") else 0
    print(f"  run{i}: {r}", flush=True); time.sleep(1)

print(f"=> 围栏率 WITH={fw}/5  WITHOUT={fn}/5  strict WITH={pw}/5 WITHOUT={pn}/5", flush=True)

print("\n[3] invalid response_format.type=garbage (中转是否解析该字段)", flush=True)
b = post({"model": MODEL, "temperature": 0, "max_tokens": 32,
    "messages": [{"role": "user", "content": JSON_PROMPT}],
    "response_format": {"type": "totally_bogus_schema"}})
if "_http" in b:
    print(f"  -> HTTP {b['_http']} 中转有校验该字段: {b['_body'][:120]}", flush=True)
else:
    print(f"  -> 200，非法值被忽略/未转发: {repr(content_of(b))[:80]}", flush=True)

print("\n[4] response_format=json_schema strict (中转能否映射 Gemini responseSchema)", flush=True)
schema = {"name": "probe", "strict": True, "schema": {
    "type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
    "additionalProperties": False}}
for i in range(3):
    r = classify(post({"model": MODEL, "temperature": 0, "max_tokens": 64,
        "messages": [{"role": "user", "content": JSON_PROMPT}],
        "response_format": {"type": "json_schema", "json_schema": schema}}))
    print(f"  run{i}: {r}", flush=True); time.sleep(1)

print("\n[5] reasoning_effort 转发探测 (reasoning_tokens 是否随 effort 变化)", flush=True)
for eff in ["low", "high"]:
    b = post({"model": MODEL, "temperature": 0, "max_tokens": 200,
        "messages": [{"role": "user", "content": "What is 17*23? answer in one word."}],
        "reasoning_effort": eff})
    u = b.get("usage") or {}
    print(f"  effort={eff}: reasoning_tokens={reasoning_tokens(b)} completion={u.get('completion_tokens')} err={b.get('_http') or b.get('_err')}", flush=True)
    time.sleep(1)

print("\nDONE", flush=True)
