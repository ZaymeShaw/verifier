from __future__ import annotations

import argparse
import json
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core import case_pool, pipeline
from .core.project_loader import list_projects
from .core.schema import AttributeResult, CheckReport, ClusterSummary, JudgeResult, RunTrace, to_dict

ROOT = Path(__file__).resolve().parent
BATCH_JOBS = {}
MAX_BATCH_EVENTS = 200


def _compact_run(run):
    trace = run.get("trace") or {}
    judge = run.get("judge") or {}
    attribute = run.get("attribute") or {}
    compact_trace = dict(trace)
    compact_trace.pop("raw_response", None)
    return {
        "case_id": run.get("case_id"),
        "status": judge.get("verdict") or trace.get("status") or ("error" if run.get("error") else "done"),
        "trace_id": trace.get("trace_id"),
        "trace": compact_trace,
        "judge": judge,
        "attribute": attribute,
        "cluster": run.get("cluster"),
        "check": run.get("check"),
        "frontend_view": run.get("frontend_view"),
        "error": run.get("error"),
    }


def _compact_batch_result(batch_result):
    data = to_dict(batch_result)
    data["runs"] = [_compact_run(run) for run in data.get("runs", [])]
    return data


def _case_event(index, run):
    trace = run.get("trace") or {}
    judge = run.get("judge") or {}
    attribute = run.get("attribute") or {}
    status = judge.get("verdict") or trace.get("status") or ("error" if run.get("error") else "done")
    reason = run.get("error") or trace.get("error") or judge.get("reasoning_summary") or attribute.get("root_cause_hypothesis") or ""
    return {
        "index": index,
        "case_id": run.get("case_id"),
        "status": status,
        "error": run.get("error") or trace.get("error") or "",
        "reason": reason,
        "run": _compact_run(run),
    }


def _run_batch_job(job_id, project, cases, mock, expected_intent, concurrency):
    job = BATCH_JOBS[job_id]
    total = len(cases)

    def on_case_done(index, run):
        job["done"] += 1
        job["events"].append(_case_event(index, run))
        if len(job["events"]) > MAX_BATCH_EVENTS:
            job["events"] = job["events"][-MAX_BATCH_EVENTS:]

    try:
        job["status"] = "running"
        job["result"] = pipeline.batch_run(project, cases, mock=mock, expected_intent=expected_intent, concurrency=concurrency, on_case_done=on_case_done)
        job["compact_result"] = _compact_batch_result(job["result"])
        job["done"] = total
        job["status"] = "completed"
    except Exception as exc:
        job["error"] = str(exc)
        job["status"] = "failed"



class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith("/frontend/"):
            return str(ROOT / path.lstrip("/"))
        return super().translate_path(path)

    def end_headers(self):
        if self.path.startswith("/frontend/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def _send_json(self, data, status=200):
        body = json.dumps(to_dict(data), ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        size = int(self.headers.get("Content-Length") or 0)
        if not size:
            return {}
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})
        elif self.path == "/projects":
            self._send_json({"projects": list_projects()})
        elif self.path == "/" or self.path == "/frontend":
            self.send_response(302)
            self.send_header("Location", "/frontend/index.html")
            self.end_headers()
        else:
            super().do_GET()

    def do_POST(self):
        try:
            data = self._read_json()
            project = data.get("project") or data.get("project_id")
            if self.path == "/api/analysis":
                result = pipeline.analysis(project)
            elif self.path == "/api/live_run":
                result = pipeline.live_run(project, data.get("input") or {}, mock=bool(data.get("mock")))
            elif self.path == "/api/mock_cases":
                result = {"project_id": project, "cases": pipeline.mock_cases(project)}
            elif self.path == "/api/mock_datasets":
                result = {"project_id": project, "datasets": pipeline.mock_datasets(project)}
            elif self.path == "/api/case_pools":
                result = {"project_id": project, "pools": case_pool.list_case_pools(project)}
            elif self.path == "/api/case_pool/save":
                result = case_pool.save_case_pool(project, data.get("name") or "", data.get("cases") or [])
            elif self.path == "/api/case_pool/load":
                result = case_pool.load_case_pool(project, data.get("id") or "")
            elif self.path == "/api/case_pool/delete":
                result = case_pool.delete_case_pool(project, data.get("id") or "")
            elif self.path == "/api/judge":
                result = pipeline.judge(project, RunTrace(**data.get("trace")), data.get("expected_intent"))
            elif self.path == "/api/attribute":
                result = pipeline.attribute(project, RunTrace(**data.get("trace")), JudgeResult(**data.get("judge")))
            elif self.path == "/api/cluster":
                attributes = [AttributeResult(**item) for item in data.get("attributes", [])]
                result = pipeline.cluster(project, attributes)
            elif self.path == "/api/check":
                result = pipeline.check(
                    project,
                    RunTrace(**data["trace"]) if data.get("trace") else None,
                    JudgeResult(**data["judge"]) if data.get("judge") else None,
                    AttributeResult(**data["attribute"]) if data.get("attribute") else None,
                    ClusterSummary(**data["cluster"]) if data.get("cluster") else None,
                )
            elif self.path == "/api/run_chain":
                result = pipeline.run_chain(project, data.get("input") or {}, mock=bool(data.get("mock")), expected_intent=data.get("expected_intent"))
            elif self.path == "/api/batch_run":
                concurrency = max(1, min(int(data.get("concurrency") or 4), 8))
                result = pipeline.batch_run(project, data.get("cases") or data.get("inputs") or [], mock=bool(data.get("mock")), expected_intent=data.get("expected_intent"), concurrency=concurrency)
            elif self.path == "/api/batch_start":
                concurrency = max(1, min(int(data.get("concurrency") or 4), 8))
                cases = data.get("cases") or data.get("inputs") or []
                job_id = uuid.uuid4().hex
                BATCH_JOBS[job_id] = {"job_id": job_id, "project_id": project, "status": "pending", "total": len(cases), "done": 0, "events": [], "result": None, "compact_result": None, "error": None}
                thread = threading.Thread(target=_run_batch_job, args=(job_id, project, cases, bool(data.get("mock")), data.get("expected_intent"), concurrency), daemon=True)
                thread.start()
                result = {"job_id": job_id, "status": "pending", "total": len(cases), "done": 0}
            elif self.path == "/api/batch_status":
                job = BATCH_JOBS.get(data.get("job_id") or "")
                if not job:
                    self._send_json({"error": "batch job not found"}, 404)
                    return
                result = {key: to_dict(value) for key, value in job.items() if key not in ("result", "compact_result")}
                if job.get("status") == "completed":
                    result["result"] = job.get("compact_result")
            elif self.path == "/api/frontend_view":
                result = pipeline.frontend_view(
                    project,
                    RunTrace(**data["trace"]) if data.get("trace") else None,
                    JudgeResult(**data["judge"]) if data.get("judge") else None,
                    AttributeResult(**data["attribute"]) if data.get("attribute") else None,
                    ClusterSummary(**data["cluster"]) if data.get("cluster") else (pipeline.cluster(project, [AttributeResult(**item) for item in data.get("attributes", [])]) if data.get("attributes") else None),
                    CheckReport(**data["check"]) if data.get("check") else None,
                )
            else:
                self._send_json({"error": f"unknown endpoint {self.path}"}, 404)
                return
            self._send_json(result)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8020)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
