"""真实页面 + 真实 SQLite/API，执行和归因替换为合成结果，不调用 LLM。"""
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from impl.core import materials_store, pipeline, run_store
from impl.core.run_store import LatestRunStore
from impl.server import service, tracing_reports
from impl.server.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_latest_workspace_browser_roundtrip(monkeypatch, tmp_path):
    cli = shutil.which("playwright-cli")
    if not cli:
        pytest.skip("browser regression requires playwright-cli")
    playwright = Path(cli).resolve().parent / "node_modules" / "playwright"
    if not playwright.exists():
        pytest.skip("playwright-cli installation has no Playwright library")
    monkeypatch.setattr(run_store, "STORE", LatestRunStore(tmp_path / "latest.sqlite3"))
    monkeypatch.setattr(materials_store, "require_materials", lambda _: None)
    monkeypatch.setattr(service, "projects", lambda: {"projects": ["client_search", "QA"]})
    monkeypatch.setattr(service, "list_case_pools", lambda _: {"pools": []})
    gate = threading.Event()
    fail_next = threading.Event()
    batch_number = 0

    def fake_batch(project, cases, *, concurrency, on_case_done, tracing_run_id=None):
        nonlocal batch_number
        batch_number += 1
        number = batch_number
        runs = []
        for i, case in enumerate(cases):
            if number == 1 and i == 1:
                assert gate.wait(60), "test did not release the first batch"
            tid = f"synthetic-{number}-{i}"
            run = {"case_id": case["id"], "trace": {"trace_id": tid, "project_id": project,
                   "case_id": case["id"], "input": case["live_request"], "normalized_request": {},
                   "status": "succeeded", "extracted_output": {"answer": tid}},
                   "judge": {"trace_id": tid, "project_id": project, "overall_fulfillment": {"status": "fulfilled"}},
                   "eval_axes": {"results": [{"type_id": "tool_execution", "axis_id": "tool_execution",
                      "status": "succeeded", "verdict": "sound", "summary": {"text": "synthetic", "items": [
                          {"key": "调用 @ χ:1", "value": "pass", "reason": tid}]}}]}}
            on_case_done(i, run)
            runs.append(run)
            if fail_next.is_set():
                fail_next.clear()
                raise RuntimeError("synthetic batch interruption")
        return {"project_id": project, "total": len(cases), "runs": runs, "cluster": None, "check": None}

    monkeypatch.setattr(pipeline, "batch_run", fake_batch)
    monkeypatch.setattr(pipeline, "attribute", lambda project, trace, judge, **kw:
                        {"trace_id": trace.trace_id, "project_id": project, "unresolved_reason": "synthetic attribution"})
    monkeypatch.setattr(pipeline, "frontend_view", lambda project, trace, judge, attr, *args:
                        {"project_info": {"project_id": project}, "attribute_panel": {"unresolved_reason": attr.unresolved_reason}})
    monkeypatch.setattr(tracing_reports, "render_report", lambda project: "<h1>Trace " + project + "</h1>")
    app = create_app()

    @app.post("/test/complete")
    def complete():
        gate.set()
        return {"ok": True}

    @app.post("/test/fail_next")
    def fail():
        fail_next.set()
        return {"ok": True}

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        result = subprocess.run(["node", str(ROOT / "tests" / "latest_run_browser.js")],
                                env={**os.environ, "LATEST_RUN_TEST_URL": f"http://127.0.0.1:{port}",
                                     "PLAYWRIGHT_MODULE": str(playwright)},
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "latest-workspace-browser: passed" in result.stdout
    finally:
        gate.set()
        server.should_exit = True
        thread.join(10)
        sock.close()
