"""Protocol checks and a real loopback HTTP workflow; no external model calls."""
import asyncio
from contextlib import contextmanager
import copy
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

import httpx
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from openpyxl import load_workbook
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT.parent
spec = importlib.util.spec_from_file_location("jev_llm_server", ROOT / "server.py")
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)


def request_body():
    return {"model": "requested-model", "state": {"message": "你好", "flag": False}, "questions": {
        "自定义分类": {"type": "choice", "instructions": {"rule": "按标准判断"},
                       "criteria": {"甲": ["条件甲"], "乙": None}},
        "review": {"type": "noul", "criteria": {"true": "需要复核", "false": "无需复核"}},
        "quality": {"type": "score", "criteria": ["差", {"description": "好"}]},
    }}


def answers():
    return {"自定义分类": {"type": "choice", "choice": "甲", "confidence": .6,
                       "probabilities": {"甲": .7, "乙": .3}},
            "review": {"type": "noul", "noul": .8},
            "quality": {"type": "score", "score": .75, "confidence": .6,
                        "probabilities": {"0": .25, "1": .75}}}


def completion(result=None):
    return {"id": "chat-test", "object": "chat.completion", "created": 1,
            "model": "actual-model", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps({"answers": result or answers()}, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168}}


def settings(timeout=2, enable_thinking=False):
    return server.Settings("127.0.0.1", 8040, "service-secret", "https://upstream.invalid/v1", "upstream-secret", timeout, enable_thinking)


@contextmanager
def api_client(handler, timeout=2, enable_thinking=False):
    upstream = AsyncOpenAI(api_key="upstream-secret", base_url="https://upstream.invalid/v1", max_retries=0,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        with TestClient(server.create_app(settings(timeout, enable_thinking), client=upstream)) as client:
            yield client
    finally:
        asyncio.run(upstream.close())


HEADERS = {"Authorization": "Bearer service-secret"}


def test_generic_protocol_and_fresh_call_each_time():
    calls = []

    def upstream(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer upstream-secret"
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["model"] == "requested-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["enable_thinking"] is False
        assert "extra_body" not in payload
        assert "tools" not in payload
        assert json.loads(payload["messages"][1]["content"]) == {"state": request_body()["state"]}
        rules = json.loads(payload["messages"][0]["content"].split("\n", len(server.SYSTEM.splitlines()))[-1])
        assert rules["questions"] == request_body()["questions"]
        assert set(rules["output_schema"]["properties"]["answers"]["properties"]) == set(request_body()["questions"])
        return httpx.Response(200, json=completion())

    with api_client(upstream) as client:
        for _ in range(2):
            response = client.post("/v1/systemone", json=request_body(), headers=HEADERS)
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["model"] == "actual-model"
            assert data["usage"] == {"input_tokens": 123, "output_tokens": 45}
            assert data["answers"]["quality"]["legend"] == {"0": "差", "1": {"description": "好"}}
            assert data["answers"]["review"]["noul"] == .8
            assert response.headers["x-jev-score-source"] == "llm-self-report"
            assert response.headers["cache-control"] == "no-store"
    assert len(calls) == 2


def test_thinking_enabled_reaches_wire():
    calls = []

    def upstream(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["enable_thinking"] is True
        assert "extra_body" not in payload
        return httpx.Response(200, json=completion())

    with api_client(upstream, enable_thinking=True) as client:
        assert client.post("/v1/systemone", json=request_body(), headers=HEADERS).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("change", [
    lambda r: r.update(state={}),
    lambda r: r.update(state=True),
    lambda r: r.update(model=" "),
    lambda r: r.update(assets={}),
    lambda r: r["questions"].update(x={"type": "box"}),
    lambda r: r["questions"].update(x={"type": "choice", "criteria": {}}),
    lambda r: r["questions"].update(x={"type": "noul", "criteria": {"yes": "x"}}),
])
def test_invalid_input_never_reaches_upstream(change):
    def upstream(_):
        pytest.fail("Invalid input reached upstream")
    request = request_body()
    change(request)
    with api_client(upstream) as client:
        assert client.post("/v1/systemone", json=request, headers=HEADERS).status_code == 422


def test_auth_content_type_and_duplicate_keys():
    def upstream(_):
        pytest.fail("Invalid request reached upstream")
    with api_client(upstream) as client:
        assert client.post("/v1/systemone", json=request_body()).status_code == 401
        assert client.post("/v1/systemone", json=request_body(), headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.post("/v1/systemone", content="x", headers=HEADERS).status_code == 415
        for raw in ['{"model":"a","model":"b"}', '{"state":NaN}', 'not json']:
            assert client.post("/v1/systemone", content=raw, headers={**HEADERS, "Content-Type": "application/json"}).status_code == 422


@pytest.mark.parametrize("change", [
    lambda a: a.pop("review"),
    lambda a: a.update(extra={"type": "noul", "noul": 0}),
    lambda a: a["review"].update(noul=True),
    lambda a: a["review"].update(noul="0.8"),
    lambda a: a["review"].update(noul=1.1),
    lambda a: a["review"].update(noul=float("nan")),
    lambda a: a["自定义分类"].update(choice="unknown"),
    lambda a: a["自定义分类"].update(choice="乙"),
    lambda a: a["自定义分类"].update(confidence=-.1),
    lambda a: a["自定义分类"].pop("confidence"),
    lambda a: a["自定义分类"]["probabilities"].update(甲=.9),
    lambda a: a["自定义分类"]["probabilities"].pop("乙"),
    lambda a: a["自定义分类"]["probabilities"].update(甲=1.2, 乙=-.2),
    lambda a: a["quality"].update(score=.25),
    lambda a: a["quality"].update(type="noul"),
])
def test_invalid_answers_are_rejected_without_repair(change):
    value = answers()
    change(value)
    with pytest.raises(ValueError):
        server.normalize_response(completion(value), server.Request.model_validate(request_body()))


@pytest.mark.parametrize("change", [
    lambda b: b.pop("usage"),
    lambda b: b["usage"].update(prompt_tokens=True),
    lambda b: b["usage"].update(completion_tokens=-1),
    lambda b: b.update(model=""),
    lambda b: b["choices"][0].update(finish_reason="length"),
    lambda b: b["choices"][0]["message"].update(refusal="no"),
    lambda b: b["choices"][0]["message"].update(tool_calls=[{}]),
    lambda b: b["choices"][0]["message"].update(content='```json\n{}\n```'),
    lambda b: b["choices"][0]["message"].update(content='{"answers":{},"answers":{}}'),
])
def test_invalid_upstream_envelopes(change):
    body = completion()
    change(body)
    with pytest.raises(ValueError):
        server.normalize_response(body, server.Request.model_validate(request_body()))


@pytest.mark.parametrize("mode,status", [("http", 502), ("invalid", 502), ("text", 502), ("timeout", 504), ("connect", 502)])
def test_service_errors_are_sanitized_and_not_retried(mode, status):
    calls = []

    async def upstream(request):
        calls.append(request)
        if mode == "timeout":
            await asyncio.sleep(.2)
        if mode == "connect":
            raise httpx.ConnectError("upstream-secret", request=request)
        if mode == "http":
            return httpx.Response(401, json={"error": {"message": "upstream-secret"}})
        if mode == "text":
            return httpx.Response(200, text="upstream-secret")
        return httpx.Response(200, json={**completion(), "usage": None})

    with api_client(upstream, timeout=.05) as client:
        result = client.post("/v1/systemone", json=request_body(), headers=HEADERS)
    assert result.status_code == status, result.text
    assert "upstream-secret" not in result.text
    assert len(calls) == 1


def test_settings_are_local_and_do_not_interpolate(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SERVER_HOST=127.0.0.1\nSERVER_PORT=8040\nSERVER_API_KEY=service\n"
                   "LLM_BASE_URL=https://gateway.invalid/v1\nLLM_API_KEY=${literal}\nLLM_TIMEOUT_SECONDS=120\n")
    monkeypatch.setenv("LLM_API_KEY", "environment-must-not-win")
    assert server.load_settings(env).llm_api_key == "${literal}"
    assert server.load_settings(env).enable_thinking is False
    env.write_text(env.read_text() + "LLM_ENABLE_THINKING=true\n")
    assert server.load_settings(env).enable_thinking is True
    env.write_text(env.read_text().replace("LLM_ENABLE_THINKING=true", "LLM_ENABLE_THINKING=false"))
    assert server.load_settings(env).enable_thinking is False
    env.write_text(env.read_text().replace("LLM_API_KEY=${literal}\n", ""))
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        server.load_settings(env)


@pytest.mark.parametrize("line", ["SERVER_PORT=0", "LLM_TIMEOUT_SECONDS=nan",
    "LLM_TIMEOUT_SECONDS=0", "LLM_BASE_URL=https://user:secret@host/v1",
    "LLM_BASE_URL=https://host/v1/chat/completions", "SERVER_API_KEY=",
    "LLM_ENABLE_THINKING=", "LLM_ENABLE_THINKING=auto", "LLM_ENABLE_THINKING=1"])
def test_invalid_settings(tmp_path, line):
    cfg = {"SERVER_HOST": "127.0.0.1", "SERVER_PORT": "8040", "SERVER_API_KEY": "service",
           "LLM_BASE_URL": "https://host/v1", "LLM_API_KEY": "upstream", "LLM_TIMEOUT_SECONDS": "120"}
    k, v = line.split("=", 1)
    cfg[k] = v
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}={v}" for k, v in cfg.items()))
    with pytest.raises(ValueError):
        server.load_settings(env)


def test_existing_pipeline_over_real_http(tmp_path):
    """Run unchanged pipeline main, curl, adapter and SDK against a fake upstream."""
    calls = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, self.headers["Authorization"], raw))
            rules = json.loads(raw["messages"][0]["content"][len(server.SYSTEM) + 1:])
            questions = rules["questions"]
            opts = list(questions["classification"]["criteria"])
            result = {"classification": {"type": "choice", "choice": opts[0], "confidence": .8,
                "probabilities": {k: 1.0 if i == 0 else 0.0 for i, k in enumerate(opts)}},
                "needs_review": {"type": "noul", "noul": .25}}
            data = json.dumps(completion(result)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    # Keep the original scripts byte-for-byte, with only test-local .env/data.
    scripts = tmp_path / "scripts"
    folder = scripts / "verifier-jevcls"
    adapter = scripts / "jev-llm-server"
    adapter.mkdir(parents=True)
    folder.mkdir()
    shutil.copy2(SCRIPTS / "jev_build_requests.py", scripts)
    shutil.copy2(ROOT / "server.py", adapter)
    for name in ("pipeline.py", "verifier_excel_to_jev_state.py", "materials-map.json"):
        shutil.copy2(SCRIPTS / "verifier-jevcls" / name, folder)
    shutil.copytree(SCRIPTS / "verifier-jevcls/templates", folder / "templates")
    (folder / "materials.json").write_text(json.dumps([
        {"traceid": "trace-001", "messages": [{"role": "user", "content": "1+1?"}], "output": "2"},
        {"traceid": "trace-002", "messages": [{"role": "user", "content": "2+2?"}], "output": "4"},
    ]))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    (adapter / ".env").write_text(f"SERVER_HOST=127.0.0.1\nSERVER_PORT={port}\nSERVER_API_KEY=service-secret\n"
        f"LLM_BASE_URL=http://127.0.0.1:{upstream.server_port}/v1\nLLM_API_KEY=upstream-secret\nLLM_TIMEOUT_SECONDS=5\n")
    (folder / ".env").write_text(f"INPUT_PATH=\nOUTPUT_DIR=output\nMATERIALS_PATH=materials.json\n"
        f"MATERIALS_MAP_PATH=materials-map.json\nJEV_TEMPLATE_PATH=templates/answer-classification.json\n"
        f"JEV_API_URL=http://127.0.0.1:{port}/v1/systemone\nJEV_API_KEY=service-secret\n"
        "JEV_MODEL=requested-model\nJEV_TIMEOUT_SECONDS=10\n")
    process = subprocess.Popen([sys.executable, str(adapter / "server.py")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    break
            except OSError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError("Adapter failed to start")
                time.sleep(.05)
        run = subprocess.run([sys.executable, str(folder / "pipeline.py")], capture_output=True, text=True, timeout=20)
        assert run.returncode == 0, run.stdout + run.stderr
        rows = json.loads((folder / "output/classification-results.json").read_text())
        assert [r["id"] for r in rows] == ["trace-001", "trace-002"]
        assert all(r["success"] and r["model"] == "actual-model" and r["needs_review_score"] == .25 for r in rows)
        workbook = load_workbook(folder / "output/classification-results.xlsx", read_only=True)
        table = list(workbook.active.values)
        workbook.close()
        assert table[0] == ("traceid", "标签", "待复核分数", "T:回答正确概率")
        assert table[1][3] == 1
        assert len(table) == 3 and table[1][0] == "trace-001" and table[1][2] == .25
        assert len(calls) == 2
        assert all(path == "/v1/chat/completions" and key == "Bearer upstream-secret" for path, key, _ in calls)
        assert all(payload["enable_thinking"] is False for _, _, payload in calls)
        assert "trace-001" not in json.dumps(calls[0][2])
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)
