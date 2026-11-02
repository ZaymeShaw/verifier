import json
import re
import time

from openai import OpenAI

client = OpenAI(
    api_key="sk-antigravity", base_url="http://192.168.66.18:8045/v1", timeout=30, max_retries=0
)
MSG = [{"role": "user", "content": "今天天气不错。"}]
WAIT_RE = re.compile(r"Wait\s+(\d+)s")


def create(**kwargs):
    for _ in range(10):
        try:
            return client.chat.completions.create(model="gemini-3.7-flash-medium", **kwargs)
        except Exception as exc:
            m = WAIT_RE.search(str(exc))
            if not m:
                raise
            nap = int(m.group(1)) + 1
            print(f"  ...限流，退避 {nap}s")
            time.sleep(nap)
    raise RuntimeError("give up")


INSTR = "把上面这句话改写成 JSON，字段 mood。不要任何多余文本。"

# A: 强 JSON 指令 + response_format
r = create(messages=MSG + [{"role": "user", "content": INSTR}], response_format={"type": "json_object"})
print("A with_json:", repr(r.choices[0].message.content[:200]))

# B: 相同指令，不传 response_format → 对照参数是否有用
r2 = create(messages=MSG + [{"role": "user", "content": INSTR}])
print("B no_param :", repr(r2.choices[0].message.content[:200]))

# C: 无 JSON 指令 + response_format（模拟 judge 忘记说"输出 JSON"）
r3 = create(messages=MSG, response_format={"type": "json_object"})
print("C forced   :", repr(r3.choices[0].message.content[:200]))
