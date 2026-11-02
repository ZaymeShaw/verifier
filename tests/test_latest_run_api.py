import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from impl.core import materials_store, pipeline, run_store
from impl.core.run_store import LatestRunStore
from impl.server import service
from impl.server.routes import router


@pytest.fixture
def api(monkeypatch, tmp_path):
    store = LatestRunStore(tmp_path / "latest.sqlite3")
    monkeypatch.setattr(run_store, "STORE", store)
    monkeypatch.setattr(materials_store, "require_materials", lambda _: None)

    def fake_batch(project, cases, *, concurrency, on_case_done, tracing_run_id=None):
        runs = []
        for i, case in enumerate(cases):
            run = {"case_id": case["id"], "trace": {"trace_id": f"trace-{i}", "project_id": project,
                   "case_id": case["id"], "input": case["live_request"], "normalized_request": {},
                   "status": "succeeded", "extracted_output": {"answer": "saved"}},
                   "judge": {"trace_id": f"trace-{i}", "project_id": project, "overall_fulfillment": {"status": "fulfilled"}},
                   "eval_axes": {"probe": "saved axes"}}
            runs.append(run)
            on_case_done(i, run)
        return {"project_id": project, "total": len(cases), "runs": runs, "cluster": None, "check": None}

    monkeypatch.setattr(pipeline, "batch_run", fake_batch)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, store


def case(name="a"):
    return {"id": name, "project_id": "client_search", "scenario": "s", "intent": None,
            "live_request": {"user_text": "synthetic"}, "output": None, "reference": None}


def call(client, path, **payload):
    response = client.post(path, json={"project": "client_search", **payload})
    assert response.status_code == 200, response.text
    return response.json()


def await_done(client, started):
    for _ in range(100):
        status = call(client, "/api/batch_status", job_id=started["job_id"])
        if status["status"] not in ("running", "pending"):
            assert status["status"] == "completed", status.get("error")
            return status
        time.sleep(0.01)
    pytest.fail("fake batch did not finish")


def test_workspace_roundtrip_and_partial_rerun(api):
    client, store = api
    call(client, "/api/run_workspace/replace", cases=[case("a"), case("b")])
    first = call(client, "/api/batch_start", cases=[case("a"), case("b")], pool_indexes=[0, 1])
    status = await_done(client, first)
    assert len(status["result"]["runs"]) == 2
    assert len(status["result"]["table"]["rows"]) == 2
    assert status["events"][0]["request_key"] == status["events"][0]["run"]["request_key"]
    second = call(client, "/api/batch_start", cases=[case("b")], pool_indexes=[1])
    await_done(client, second)
    restored = call(client, "/api/run_workspace")
    assert [r["request_key"] for r in restored["runs"]] == [first["requests"][0]["request_key"], second["requests"][0]["request_key"]]
    assert restored["runs"][0]["eval_axes"] == {"probe": "saved axes"}
    assert restored["runs"][0]["trace"]["extracted_output"] == {"answer": "saved"}
    assert client.post("/api/batch_status", json={"project": "other", "job_id": second["job_id"]}).status_code == 404
    assert client.post("/api/batch_status", json={"project": "client_search", "job_id": first["job_id"]}).status_code == 404
    call(client, "/api/run_workspace/clear", keep_cases=True)
    cleared = call(client, "/api/run_workspace")
    # 公共 JSON 序列化省略空 runs / batch，页面按空集合处理。
    assert len(cleared["cases"]) == 2 and not cleared.get("runs") and cleared.get("batch") is None
    call(client, "/api/run_workspace/clear", keep_cases=False)
    assert not call(client, "/api/run_workspace").get("cases")


def test_workspace_preserves_mock_case_nulls_and_request_facts(api):
    client, _ = api
    original = {**case(), "live_request": {"user_text": "synthetic", "runtime_logs": [], "nested": {"value": None}}}
    saved = call(client, "/api/run_workspace/replace", cases=[original])
    restored = call(client, "/api/run_workspace")["cases"][0]["case"]
    assert restored == saved["cases"][0]["case"]
    assert restored["output"] is None and restored["reference"] is None and restored["intent"] is None
    assert restored["live_request"] == original["live_request"]


def test_failed_batch_keeps_completed_rows(api, monkeypatch):
    client, store = api
    def fail_after_first(project, cases, *, concurrency, on_case_done, tracing_run_id=None):
        on_case_done(0, {"trace": {"trace_id": "t", "project_id": project, "input": {}, "normalized_request": {}},
                         "error": "case failed"})
        raise RuntimeError("batch interrupted")
    monkeypatch.setattr(pipeline, "batch_run", fail_after_first)
    started = call(client, "/api/batch_start", cases=[case("a"), case("b")])
    for _ in range(100):
        state = call(client, "/api/batch_status", job_id=started["job_id"])
        if state["status"] == "failed":
            break
        time.sleep(0.01)
    assert state["status"] == "failed" and state["done"] == 1
    assert len(call(client, "/api/run_workspace")["runs"]) == 1
    assert call(client, "/api/run_workspace")["cases"][1]["status"] == "error"


def test_manual_attribute_is_saved_before_response(api, monkeypatch):
    client, store = api
    started = call(client, "/api/batch_start", cases=[case()])
    await_done(client, started)
    monkeypatch.setattr(pipeline, "attribute", lambda *args, **kwargs: {"unresolved_reason": "saved attribution"})
    monkeypatch.setattr(service, "frontend_view", lambda data: {"attribute_panel": data["attribute"]})
    monkeypatch.setattr(service, "build_trace_table_row_from_run", lambda run: {"id": "a", "attribution_summary": {"summary_text": "saved attribution"}})
    updated = call(client, "/api/run_workspace/attribute", request_key=started["requests"][0]["request_key"])
    reloaded = call(client, "/api/run_workspace")["runs"][0]
    assert reloaded["attribute"] == updated["attribute"]
    assert reloaded["frontend_view"]["attribute_panel"]["unresolved_reason"] == "saved attribution"
    assert reloaded["table_row"]["attribution_summary"]["summary_text"] == "saved attribution"
