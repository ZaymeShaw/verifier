import json
import re
import time

from openai import OpenAI

BASE_URL = "http://192.168.66.18:8045/v1"
API_KEY = "sk-antigravity"
MODEL = "gemini-3.7-flash-medium"
WAIT_RE = re.compile(r"Wait\s+(\d+)s")


def call_once(client, label, stream=False, **kwargs):
    started = time.monotonic()
    try:
        if stream:
            parts = []
            with client.chat.completions.create(
                model=kwargs.get("model", MODEL),
                messages=[{"role": "user", "content": "数到5"}],
                stream=True,
            ) as s:
                for chunk in s:
                    if chunk.choices and chunk.choices[0].delta.content:
                        parts.append(chunk.choices[0].delta.content)
            return {
                "case": label,
                "ok": True,
                "elapsed": round(time.monotonic() - started, 2),
                "reply": "".join(parts)[:120],
            }
        resp = client.chat.completions.create(
            model=kwargs.get("model", MODEL),
            messages=[{"role": "user", "content": "用一句话说你是谁"}],
            **{k: v for k, v in kwargs.items() if k != "model"},
        )
        msg = resp.choices[0].message
        return {
            "case": label,
            "ok": True,
            "elapsed": round(time.monotonic() - started, 2),
            "reply": (msg.content or "")[:120],
            "finish": resp.choices[0].finish_reason,
            "usage": resp.usage.model_dump() if resp.usage else None,
        }
    except Exception as exc:
        text = str(exc)
        wait = WAIT_RE.search(text)
        return {
            "case": label,
            "ok": False,
            "elapsed": round(time.monotonic() - started, 2),
            "retry_after": int(wait.group(1)) if wait else None,
            "error": f"{type(exc).__name__}: {text[:200]}",
        }


def run(label, max_attempts=8, **kwargs):
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=30, max_retries=0)
    stream = kwargs.pop("stream", False)
    for attempt in range(max_attempts):
        res = call_once(client, label, stream=stream, **kwargs)
        if res["ok"]:
            print(json.dumps({**res, "attempts": attempt + 1}, ensure_ascii=False), flush=True)
            return res
        # 撞限流就按上游给的 Wait Ns 退避；非限流错误（如模型不存在）直接返回
        if res.get("retry_after") is None:
            print(json.dumps({**res, "attempts": attempt + 1}, ensure_ascii=False), flush=True)
            return res
        nap = res["retry_after"] + 1
        print(
            json.dumps({"case": label, "rate_limited": True, "wait": nap, "attempt": attempt + 1}, ensure_ascii=False),
            flush=True,
        )
        time.sleep(nap)
    print(json.dumps({"case": label, "ok": False, "error": "gave up after retries"}, ensure_ascii=False), flush=True)
    return {"ok": False}


if __name__ == "__main__":
    ok = 0
    total = 0
    for label, kwargs in [
        ("default", {}),
        ("temperature0", {"temperature": 0}),
        ("json_mode", {"temperature": 0, "response_format": {"type": "json_object"}}),
        ("with_max_tokens", {"max_tokens": 64}),
        ("stream", {"stream": True}),
    ]:
        total += 1
        ok += 1 if run(label, **kwargs).get("ok") else 0
    print(f"\n通过 {ok}/{total}（wrong_model 为负向对照，故意不传）")
