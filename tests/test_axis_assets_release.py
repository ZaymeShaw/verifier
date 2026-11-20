"""代码升级沿用实例数据：算法随代码更新，错误配置在覆盖结果前拒跑。"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from impl.core import capability_store, instances, materials_store, pipeline, run_store
from impl.core.axis_loop import definitions
from impl.core.axis_loop.validate import check_definitions
from impl.core.eval_axes import validate_eval_axes_cases
from impl.projects.llm_probe_loop.eval_axes.materials import registry
from impl.server import batch_jobs
from impl.server.routes import router

PROJECT = "llm_probe_loop"


@pytest.fixture
def release(tmp_path, monkeypatch):
    source = definitions.store_path(PROJECT).parent
    package = tmp_path / "impl/projects" / PROJECT / "eval_axes"
    package.mkdir(parents=True)
    shutil.copy2(source / definitions.STORE_NAME, package / definitions.STORE_NAME)
    shutil.copytree(source / definitions.CODE_DIR, package / definitions.CODE_DIR,
                    ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(definitions, "PROJECTS_DIR", tmp_path / "impl/projects")
    monkeypatch.setattr(capability_store, "ROOT", tmp_path / "impl")
    monkeypatch.setattr(instances, "ROOT", tmp_path)
    monkeypatch.setattr(instances, "_port_available", lambda _: True)
    instance = instances.resolve_instance(18031)
    monkeypatch.setenv(instances.INSTANCE_ENV, instance["id"])
    data = instances.data_root() / PROJECT
    data.mkdir(parents=True, exist_ok=True)
    (data / "capability_map.json").write_text(json.dumps({"s": {
        "capability": "实例自己的业务口径", "service": {"url": "http://instance.invalid/answer"},
        "axes": [{"type": "expectations", "enabled": True, "description": "实例自己的轴描述"}],
    }}, ensure_ascii=False), encoding="utf-8")
    return package, data, instance


def _case():
    return {"id": "c1", "project_id": PROJECT, "scenario": "display-name",
            "intent": None, "live_request": {"capability_ref": "s", "body": {}},
            "output": {"answer": "已有产出"}, "reference": None}


def test_code_upgrade_uses_complete_release_and_preserves_existing_instance(release):
    package, data, instance = release
    old = json.loads((package / definitions.STORE_NAME).read_text())
    old["axes"]["trace_analysis"]["materials"] = ["case.trace.{catalog, records, links, program_suspects, gaps}"]
    (data / definitions.STORE_NAME).write_text(json.dumps(old))
    stale_script = data / "axis_code/loops/expectations/dispatch.py"
    stale_script.parent.mkdir(parents=True)
    stale_script.write_text("raise AssertionError('must not execute stale instance code')\n")
    original_data = {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}

    current = definitions.load(PROJECT)
    assert check_definitions(current, registry()) == []
    assert current.axes["trace_analysis"].resources == ("case.trace.uris[]",)
    assert Path(current.loops["expectations"].dispatch.__code__.co_filename).is_relative_to(package)
    validate_eval_axes_cases(PROJECT, [_case()])

    # 模拟下一次拉取代码并沿用同端口：JSON 与脚本必须都取新版本。
    updated = json.loads((package / definitions.STORE_NAME).read_text())
    updated["axes"]["expectations"]["title"] = "updated-release"
    (package / definitions.STORE_NAME).write_text(json.dumps(updated))
    (package / "axis_code/loops/expectations/dispatch.py").write_text(
        "def dispatch(view):\n    return [{'id': 'updated-release', 'materials': ['case.requirements']}]\n")
    assert instances.resolve_instance(18031) == instance
    upgraded = definitions.load(PROJECT)
    assert upgraded.axes["expectations"].title == "updated-release"
    assert upgraded.loops["expectations"].dispatch(SimpleNamespace()) == [
        {"id": "updated-release", "materials": ["case.requirements"]}]
    assert {p: p.read_bytes() for p in data.rglob("*") if p.is_file()} == original_data


def test_missing_release_never_loads_instance_copy(release):
    package, data, _ = release
    shutil.copy2(package / definitions.STORE_NAME, data / definitions.STORE_NAME)
    shutil.copytree(package / definitions.CODE_DIR, data / definitions.CODE_DIR)
    (package / definitions.STORE_NAME).unlink()
    with pytest.raises(ValueError, match="没有轴定义存储"):
        definitions.load(PROJECT)


@pytest.mark.parametrize("fault", ["material", "script", "scenario"])
def test_bad_configuration_rejects_batch_before_erasing_results(release, monkeypatch, tmp_path, fault):
    package, data, _ = release
    if fault == "material":
        path = package / definitions.STORE_NAME
        raw = json.loads(path.read_text())
        raw["axes"]["trace_analysis"]["materials"] = ["case.trace.{catalog, records}"]
        path.write_text(json.dumps(raw))
        expected_error = "catalog"
    elif fault == "script":
        (package / "axis_code/fulfillment/synth.py").unlink()
        expected_error = "synth.py"
    else:
        path = data / "capability_map.json"
        raw = json.loads(path.read_text())
        raw["s"]["axes"] = [{"type": "fulfillment", "enabled": True}]
        path.write_text(json.dumps(raw))
        expected_error = "硬依赖"

    store = run_store.LatestRunStore(tmp_path / "latest.sqlite3")
    monkeypatch.setattr(run_store, "STORE", store)
    monkeypatch.setattr(materials_store, "require_materials", lambda _: None)
    identities = store.start(PROJECT, "previous", [_case()])
    store.save_run(PROJECT, "previous", identities[0], {"case_id": "c1", "saved_evidence": "keep"})
    store.finish(PROJECT, "previous", summary={"total": 1})
    before = store.load(PROJECT)

    def must_not_run(*args, **kwargs):
        pytest.fail("invalid evaluator must be rejected before starting work")

    monkeypatch.setattr(batch_jobs, "threading", SimpleNamespace(Thread=must_not_run))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/api/batch_start", json={"project": PROJECT, "cases": [_case()]})
    assert response.status_code == 422, response.text
    assert expected_error in response.json()["error"]
    after = store.load(PROJECT)
    assert after["cases"] == before["cases"]
    assert after["runs"] == before["runs"]
    assert after["batch"]["job_id"] == "previous"

    # CLI / 同步入口也在 worker 创建前失败。
    monkeypatch.setattr(pipeline, "ThreadPoolExecutor", must_not_run)
    with pytest.raises(ValueError, match=expected_error):
        pipeline.batch_run(PROJECT, [_case()])


def test_batch_checks_request_scenarios_once_and_allows_inline_capability(monkeypatch):
    from impl.projects.llm_probe_loop.eval_axes import validate
    checked = []
    monkeypatch.setattr(validate, "load_scenario_axes", checked.append)
    validate.validate_cases([_case(), _case(), {"live_request": {"capability_ref": "second"}},
                             {"live_request": {"capability": "内联能力口径"}}])
    assert checked == ["s", "second"]


@pytest.mark.parametrize("project_id", ["../llm_probe_loop", "/llm_probe_loop", ""])
def test_axis_package_path_rejects_invalid_project_id(project_id):
    with pytest.raises(ValueError, match="非法 project id"):
        definitions.store_path(project_id)
