"""显式点击才发起的轴语义聚类。标准/任务/结果均在后端，刷新只查询。"""
from __future__ import annotations

import threading
import time
import uuid

from ..core import axes_clustering, run_store
from . import service


def _project(data):
    return service._require_eval_axes_project(service.project_from(data))


def _selections(data):
    return sorted([{"pool_index": item["pool_index"], "request_key": item.get("request_key")}
                   for item in data["selections"]], key=lambda item: item["pool_index"])


def state(data):
    project = _project(data)
    selections = _selections(data)
    scope_error = None
    try:
        run_store.STORE.clustering_inputs(project, selections, axes_clustering.DEFAULT_CRITERIA)
    except run_store.WorkspaceConflict as exc:
        scope_error = str(exc)
    current = run_store.STORE.clustering_state(project, axes_clustering.DEFAULT_CRITERIA)
    current['scope_valid'] = scope_error is None
    current['scope_error'] = scope_error
    current["scope_matches"] = scope_error is None and current["selections"] == selections
    if not current["scope_matches"]:
        current["result"] = None
    current['batch'] = run_store.STORE.batch_progress(project)
    current['server_time'] = time.time()
    return current


def save_criteria(data):
    project = _project(data)
    run_store.STORE.save_clustering_criteria(project, data["criteria"], data["expected_version"], axes_clustering.DEFAULT_CRITERIA)
    return run_store.STORE.clustering_state(project, axes_clustering.DEFAULT_CRITERIA)


def _run(project, job_id, criteria, material):
    def progress(stage, detail, request_timeout_seconds=None):
        run_store.STORE.clustering_progress(project, job_id, stage, detail, request_timeout_seconds)

    try:
        progress('preparing', f'已整理 {len(material["refs"])} 条 reason，准备模型请求')
        result = axes_clustering.cluster_with_llm(project, criteria, material, on_progress=progress)
        progress('saving', '结构校验通过，正在保存聚类结果')
        run_store.STORE.finish_clustering(project, job_id, result=result)
    except Exception as exc:
        run_store.STORE.finish_clustering(project, job_id, error=str(exc))


def start(data):
    project = _project(data)
    selections = _selections(data)
    snapshot = run_store.STORE.clustering_inputs(project, selections, axes_clustering.DEFAULT_CRITERIA)
    types = service.eval_axes_types({"project": project})["types"]
    material = axes_clustering.build_material(snapshot["rows"], types)
    if not material["refs"]:
        raise ValueError("当前筛选没有可聚类的枚举结果；可以先单独保存标准")
    job_id = uuid.uuid4().hex
    saved = run_store.STORE.begin_clustering(project, data["criteria"], data["expected_version"],
                                           snapshot["data_revision"], selections, job_id, axes_clustering.DEFAULT_CRITERIA)
    thread = threading.Thread(target=_run, args=(project, job_id, saved["criteria"], material), daemon=True)
    try:
        thread.start()
    except Exception as exc:
        run_store.STORE.finish_clustering(project, job_id, error=str(exc))
        raise
    return {"job_id": job_id, "criteria": saved["criteria"], "criteria_version": saved["criteria_version"],
            "status": "running", "record_count": len(material["refs"])}
