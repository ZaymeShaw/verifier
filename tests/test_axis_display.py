import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from impl.core import axis_display, instances
from impl.server import service
from impl.server.routes import router


TYPES = [{"type_id": "probe", "verdict_enum": [{"value": "problematic"}, {"value": "untested"}]}]
POLICY = {"axes": {"probe": {"attention_verdicts": ["problematic", "untested"]}}}


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(axis_display, "data_root", lambda: tmp_path)
    path = tmp_path / "demo" / "axis_display.json"
    path.parent.mkdir()
    return path


def test_optional_policy_does_not_load_registry(config_path):
    def unavailable():
        raise AssertionError("A project without a display policy needs no axis registry")

    assert axis_display.load_axis_display("demo", unavailable) == {"axes": {}}
    config_path.write_text('{"axes": {}}')
    assert axis_display.load_axis_display("demo", unavailable) == {"axes": {}}


def test_policy_reads_latest_file_and_keeps_projects_separate(config_path):
    config_path.write_text(json.dumps(POLICY))
    assert axis_display.load_axis_display("demo", lambda: TYPES) == POLICY
    assert axis_display.load_axis_display("another", lambda: TYPES) == {"axes": {}}
    config_path.write_text('{"axes": {}}')
    assert axis_display.load_axis_display("demo", lambda: TYPES) == {"axes": {}}


@pytest.mark.parametrize("value", [
    [], {}, {"axes": []}, {"axes": {}, "extra": True},
    {"axes": {"unknown": {"attention_verdicts": []}}},
    {"axes": {"probe": {}}},
    {"axes": {"probe": {"attention_verdicts": "problematic"}}},
    {"axes": {"probe": {"attention_verdicts": [None]}}},
    {"axes": {"probe": {"attention_verdicts": ["problematic", "problematic"]}}},
    {"axes": {"probe": {"attention_verdicts": ["failed"]}}},
])
def test_invalid_policy_is_not_treated_as_empty(config_path, value):
    config_path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="axis_display.json"):
        axis_display.load_axis_display("demo", lambda: TYPES)


def test_api_returns_policy_and_reports_errors(config_path, monkeypatch):
    monkeypatch.setattr(service, "_project_module", lambda *_: SimpleNamespace(describe_axis_types=lambda: TYPES))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        def post(project="demo"):
            return client.post("/api/axis_display", json={"project": project})

        assert post().json() == {"project_id": "demo", "axes": {}}
        config_path.write_text(json.dumps(POLICY))
        assert post().json() == {"project_id": "demo", **POLICY}
        assert post("another").json() == {"project_id": "another", "axes": {}}
        empty_list = {"axes": {"probe": {"attention_verdicts": []}}}
        config_path.write_text(json.dumps(empty_list))
        assert post().json() == {"project_id": "demo", **empty_list}
        config_path.write_text("{")
        response = post()
        assert response.status_code == 422 and "JSON" in response.json()["error"]
        assert post("../demo").status_code == 422
        config_path.unlink()
        config_path.mkdir()
        assert post().status_code == 500


def test_instance_policy_does_not_read_repository_or_another_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(instances, "ROOT", tmp_path)
    for identity, policy in [(None, POLICY), ("inst-0000000000000001", {"axes": {}})]:
        env = {"VERIFIER_INSTANCE_ID": identity} if identity else {}
        path = instances.data_root(environ=env) / "demo" / "axis_display.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(policy))
    monkeypatch.setenv("VERIFIER_INSTANCE_ID", "inst-0000000000000001")
    assert axis_display.load_axis_display("demo", lambda: TYPES) == {"axes": {}}
    monkeypatch.setenv("VERIFIER_INSTANCE_ID", "inst-0000000000000002")
    assert axis_display.load_axis_display("demo", lambda: TYPES) == {"axes": {}}


def test_project_default_policy_uses_declared_verdicts_without_loading_execution_code(monkeypatch):
    from impl.core.axis_loop import definitions
    from impl.projects.llm_probe_loop.eval_axes.registry import describe_axis_types

    monkeypatch.delenv("VERIFIER_INSTANCE_ID", raising=False)

    def forbidden(*_):
        raise AssertionError("Display metadata must not import execution code")

    monkeypatch.setattr(definitions, "_load_code", forbidden)
    policy = axis_display.load_axis_display("llm_probe_loop", describe_axis_types)
    assert policy["axes"]["truthfulness"]["attention_verdicts"] == ["has_refuted", "has_unverifiable"]
    assert policy["axes"]["fulfillment"]["attention_verdicts"] == ["not_fulfilled", "not_evaluable"]
    assert policy["axes"]["carryability"]["attention_verdicts"] == ["做不了", "做错了", "说不清"]
    process_axes = set(policy["axes"]) - {"truthfulness", "fulfillment", "carryability"}
    assert len(process_axes) == 6
    assert all(policy["axes"][axis]["attention_verdicts"] == ["problematic", "not_evaluable", "untested"] for axis in process_axes)
