"""通用问答被测目标：llm_probe 的 dashscope-qa / policy-clause-qa / hr-handbook-qa 三个预设调这里。

对外保持百炼（DashScope）text-generation 的请求与返回形状，预设只换地址；背后接哪个模型由 --backend 决定：
- pi（默认）：`pi -p --provider <p> --model <m>`，关工具、关会话；默认 agentrouter/deepseek-v4-flash。
- dashscope：原样转给百炼（需环境变量 BAILIAN_API_KEY）。

用法：python scripts/qa_target.py [--port 18090] [--backend pi|dashscope] [--model agentrouter/deepseek-v4-flash]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DASHSCOPE_URL = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
SYSTEM_PROMPT = '你是一个问答助手，直接回答用户的问题。'
TIMEOUT_SECONDS = 150


def ask_pi(messages: list[dict], model: str) -> str:
    provider, _, model_id = model.partition('/')
    # 单轮问答取最后一条用户消息；多轮按"角色：内容"拼成一段交给 pi。
    prompt = messages[-1]['content'] if len(messages) == 1 else '\n'.join(f"{m['role']}：{m['content']}" for m in messages)
    done = subprocess.run(
        ['pi', '-p', '--provider', provider, '--model', model_id, '--system-prompt', SYSTEM_PROMPT,
         '--no-tools', '--no-session', '--no-context-files', '--no-extensions', '--no-skills', '--no-prompt-templates', prompt],
        capture_output=True, text=True, timeout=TIMEOUT_SECONDS, cwd='/tmp')
    if done.returncode != 0 or not done.stdout.strip():
        raise RuntimeError(f'pi 退出码 {done.returncode}：{(done.stderr or done.stdout).strip()[:500]}')
    return done.stdout.strip()


def ask_dashscope(body: dict) -> tuple[int, bytes]:
    request = urllib.request.Request(DASHSCOPE_URL, data=json.dumps(body, ensure_ascii=False).encode(), method='POST', headers={
        'Authorization': 'Bearer ' + os.environ['BAILIAN_API_KEY'], 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Handler(BaseHTTPRequestHandler):
    backend = 'pi'
    model = 'agentrouter/deepseek-v4-flash'

    def _send(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self._send(200, json.dumps({'backend': self.backend, 'model': self.model if self.backend == 'pi' else 'dashscope'}).encode())

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if self.backend == 'dashscope':
            self._send(*ask_dashscope(body))
            return
        try:
            text = ask_pi(body['input']['messages'], self.model)
        except Exception as exc:  # 被测目标调用失败如实返回非 2xx，评测侧按业务调用失败处理
            self._send(502, json.dumps({'code': 'TargetError', 'message': str(exc)}, ensure_ascii=False).encode())
            return
        self._send(200, json.dumps({'request_id': uuid.uuid4().hex, 'output': {'choices': [
            {'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': text}}]}, 'usage': {}}, ensure_ascii=False).encode())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18090)
    parser.add_argument('--backend', choices=('pi', 'dashscope'), default='pi')
    parser.add_argument('--model', default='agentrouter/deepseek-v4-flash', help='pi 的 provider/model')
    args = parser.parse_args()
    Handler.backend, Handler.model = args.backend, args.model
    print(f'qa_target on 127.0.0.1:{args.port} backend={args.backend} model={args.model}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
