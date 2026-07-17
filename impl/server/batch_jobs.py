from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, Iterable

from ..core import pipeline
from ..core.schema import to_dict
from .service import case_event, compact_batch_result, project_from

MAX_BATCH_EVENTS = 200
BATCH_JOBS: Dict[str, Dict[str, Any]] = {}


def _run_batch_job(job_id: str, project: str, cases: Iterable[Dict[str, Any]], user_intent: str | None, concurrency: int) -> None:
    job = BATCH_JOBS[job_id]
    case_list = list(cases)
    total = len(case_list)

    def on_case_done(index: int, run: Dict[str, Any]) -> None:
        job["done"] += 1
        job["events"].append(case_event(index, run, job["identities"][index]))
        if len(job["events"]) > MAX_BATCH_EVENTS:
            job["events"] = job["events"][-MAX_BATCH_EVENTS:]

    try:
        job["status"] = "running"
        job["result"] = pipeline.batch_run(project, case_list, user_intent=user_intent, concurrency=concurrency, on_case_done=on_case_done)
        job["compact_result"] = compact_batch_result(job["result"], job["identities"])
        job["done"] = total
        job["status"] = "completed"
    except Exception as exc:
        job["error"] = str(exc)
        job["status"] = "failed"


def start_batch(data: Dict[str, Any]) -> Dict[str, Any]:
    from ..core.mock import parse_mock_case

    project = project_from(data)
    concurrency = max(1, min(int(data.get("concurrency") or 4), 8))
    raw_cases = data.get("cases") or []
    cases = [to_dict(parse_mock_case(case, project_id=project)) for case in raw_cases]
    job_id = uuid.uuid4().hex
    identities = [
        {
            "job_id": job_id,
            "request_index": index,
            "request_key": f"{job_id}:{index}",
            "request_case_id": str(case.get("id") or ""),
        }
        for index, case in enumerate(cases)
    ]
    BATCH_JOBS[job_id] = {
        "job_id": job_id,
        "project_id": project,
        "status": "pending",
        "total": len(cases),
        "done": 0,
        "events": [],
        "identities": identities,
        "result": None,
        "compact_result": None,
        "error": None,
    }
    thread = threading.Thread(target=_run_batch_job, args=(job_id, project, cases, data.get("user_intent"), concurrency), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "pending", "total": len(cases), "done": 0, "requests": identities}


def batch_status(data: Dict[str, Any]) -> Dict[str, Any] | None:
    job = BATCH_JOBS.get(data.get("job_id") or "")
    if not job:
        return None
    result = {key: to_dict(value) for key, value in job.items() if key not in ("result", "compact_result")}
    if job.get("status") == "completed":
        result["result"] = job.get("compact_result")
    return result
