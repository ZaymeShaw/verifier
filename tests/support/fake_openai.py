"""本地假 OpenAI chat/completions 服务：让真实 agno Agent + OpenAILike 跑在脚本化回复上。

按请求里 system prompt 的关键字路由到不同脚本，嵌套 loop 的父子两层可各自按序回复。
一步 = str（纯文本回复）或 list[(tool_name, args)]（一批并行 tool 调用；args 为 str 时原样作为 arguments）。
请求带 stream=true 时按 SSE（chat.completion.chunk）回复，否则回 chat.completion。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Union

Step = Union[str, list]


class FakeOpenAI:
    def __init__(self, scripts: dict[str, list[Step]]) -> None:
        self.scripts = {key: list(steps) for key, steps in scripts.items()}
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        self._ids = 0
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                reply = server._reply(body)
                if body.get("stream"):
                    payload, content_type = _sse(reply).encode(), "text/event-stream"
                else:
                    payload, content_type = json.dumps(reply).encode(), "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: Any) -> None:
                pass

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._http.server_address[1]}/v1"

    def __enter__(self) -> "FakeOpenAI":
        self._no_proxy = os.environ.get("NO_PROXY")
        os.environ["NO_PROXY"] = ",".join(filter(None, [self._no_proxy, "127.0.0.1", "localhost"]))
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._http.shutdown()
        self._http.server_close()
        if self._no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = self._no_proxy

    def requests_for(self, key: str) -> list[dict]:
        return [r for r in self.requests if key in _system(r)]

    def _reply(self, body: dict) -> dict:
        with self._lock:
            self.requests.append(body)
            system = _system(body)
            keys = [key for key in self.scripts if key in system]
            if len(keys) != 1:
                raise AssertionError(f"system prompt 应恰好命中一个脚本，命中 {keys}")
            steps = self.scripts[keys[0]]
            if not steps:
                raise AssertionError(f"脚本 {keys[0]} 已用完，仍收到请求")
            step = steps.pop(0)
            message: dict[str, Any] = {"role": "assistant", "content": None}
            if isinstance(step, str):
                message["content"] = step
                finish = "stop"
            else:
                message["tool_calls"] = [self._tool_call(name, args) for name, args in step]
                finish = "tool_calls"
        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model", "fake"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    def _tool_call(self, name: str, args: dict) -> dict:
        self._ids += 1
        return {
            "id": f"call_{self._ids}",
            "type": "function",
            "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)},
        }


def _sse(reply: dict) -> str:
    """把一次完整回复拆成 OpenAI 流式 chunk：先内容 / 各 tool_call，再 finish_reason，最后 [DONE]。"""
    choice = reply["choices"][0]
    message = choice["message"]
    deltas = []
    if message.get("content") is not None:
        deltas.append({"role": "assistant", "content": message["content"]})
    for index, call in enumerate(message.get("tool_calls") or []):
        deltas.append({"tool_calls": [{"index": index, **call}]})
    chunks = [(delta, None) for delta in deltas] + [({}, choice["finish_reason"])]
    lines = []
    for delta, finish in chunks:
        chunk = {
            "id": reply["id"],
            "object": "chat.completion.chunk",
            "created": reply["created"],
            "model": reply["model"],
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        lines.append(f"data: {json.dumps(chunk)}\n\n")
    return "".join(lines) + "data: [DONE]\n\n"


def _system(body: dict) -> str:
    return "\n".join(str(m.get("content") or "") for m in body.get("messages", []) if m.get("role") == "system")
