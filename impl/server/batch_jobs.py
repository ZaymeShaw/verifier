from __future__ import annotations

import threading
import os
import subprocess
import sys
import logging
from pathlib import Path
from ..core.instances import INSTANCE_ENV
from ..core.tracing_retention import log_lock
import uuid
from typing import Any, Dict, Iterable

from ..core.config import get_runtime_config, resolve_batch_concurrency
from ..core import pipeline, run_store
from ..core.schema import to_dict
from ..core.table_view import build_case_pool_table_from_runs
from .service import case_event, case_event_from_compact, project_from

MAX_BATCH_EVENTS = get_runtime_config().execution.batch_event_history_limit


def _run_batch_job(job_id: str, project: str, cases: Iterable[Dict[str, Any]], concurrency: int, identities: list[dict]) -> None:
    def on_case_done(index: int, run: Dict[str, Any]) -> None:
        event = case_event(index, run, identities[index])
        # 先落盘再让状态接口看见；浏览器关闭也不影响已完成结果保存。
        run_store.STORE.save_run(project, job_id, identities[index], event["run"])

    try:
        result = pipeline.batch_run(project, list(cases), concurrency=concurrency, on_case_done=on_case_done, tracing_run_id=job_id)
        data = to_dict(result)
        summary = {key: value for key, value in data.items() if key not in ("runs", "table")}
        run_store.STORE.finish(project, job_id, summary=summary)
    except Exception as exc:
        run_store.STORE.finish(project, job_id, error=str(exc))
    finally:
        if os.environ.get(INSTANCE_ENV) and os.environ.get('VERIFIER_TRACING_ENABLED') == '1':
            try:
                completed = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / 'scripts/tracing.py'),
                                            'cleanup'], capture_output=True, text=True, timeout=90)
                if completed.returncode:
                    logging.getLogger(__name__).warning('tracing cleanup failed: %s', completed.stderr[-500:])
            except (OSError, subprocess.TimeoutExpired) as exc:
                logging.getLogger(__name__).warning('tracing cleanup failed: %s', type(exc).__name__)



def start_batch(data: Dict[str, Any]) -> Dict[str, Any]:
    from ..core.mock import parse_mock_case

    project = project_from(data)
    concurrency = resolve_batch_concurrency(data.get("concurrency"))
    cases = [to_dict(parse_mock_case(case, project_id=project)) for case in (data.get("cases") or [])]
    if cases:
        from ..core.materials_store import require_materials
        require_materials(project)
    job_id = uuid.uuid4().hex
    if os.environ.get(INSTANCE_ENV):
        with log_lock(exclusive=True):
            identities = run_store.STORE.start(project, job_id, cases, data.get("pool_indexes"))
    else:
        identities = run_store.STORE.start(project, job_id, cases, data.get("pool_indexes"))
    thread = threading.Thread(target=_run_batch_job, args=(job_id, project, cases, concurrency, identities), daemon=True)
    try:
        thread.start()
    except Exception as exc:
        run_store.STORE.finish(project, job_id, error=str(exc))
        raise
    return {"job_id": job_id, "status": "running", "total": len(cases), "done": 0, "requests": identities}


def batch_status(data: Dict[str, Any]) -> Dict[str, Any] | None:
    workspace = run_store.STORE.load(project_from(data))
    batch = workspace["batch"]
    if not batch or batch["job_id"] != data.get("job_id"):
        return None
    runs_by_key = {run["request_key"]: run for run in workspace["runs"]}
    runs = [runs_by_key[i["request_key"]] for i in batch["bindings"] if i["request_key"] in runs_by_key]
    events = [case_event_from_compact(run["request_index"], run,
              {k: run[k] for k in ("job_id", "request_index", "request_key", "request_case_id")})
              for run in runs[-MAX_BATCH_EVENTS:]]
    response = {key: value for key, value in batch.items() if key not in ("summary", "bindings")}
    response.update(events=events, identities=batch["bindings"])
    if batch["status"] == "completed":
        response["result"] = {**(batch["summary"] or {}), "runs": runs,
                              "table": to_dict(build_case_pool_table_from_runs(workspace["project_id"], runs))}
    return response
