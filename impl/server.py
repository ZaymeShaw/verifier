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


def _compact_mapping(value):
    if isinstance(value, list):
        return [_compact_mapping(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _compact_mapping(item)
        for key, item in value.items()
        if key not in {"raw_text", "raw_response", "downstream_payload", "raw_sections", "raw_sse", "raw_cards", "raw_model_text", "frontend_view"}
    }


def _display_status(trace, judge, run):
    return (judge.get("overall_fulfillment") or {}).get("status") or judge.get("verdict") or trace.get("status") or ("error" if run.get("error") else "done")


def _short_value(value):
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    return text if len(text) <= 160 else text[:157] + "..."


def _gap_reason(prefix, gaps):
    gap = next((item for item in gaps if isinstance(item, dict)), None)
    if not gap:
        return ""
    raw_error_type = gap.get("error_type") or gap.get("requirement") or gap.get("status") or gap.get("type")
    expected = _short_value(gap.get("expected_fragment") or gap.get("expected"))
    actual = _short_value(gap.get("actual_fragment") or gap.get("actual"))
    # When gap has no identifying field AND no expected/actual, the bare
    # "wrong: gap" string carries no signal — return empty so callers can
    # fall back to richer sources like reasoning_summary.
    if not raw_error_type and not expected and not actual:
        return ""
    error_type = raw_error_type or "gap"
    detail = f"{prefix}: {error_type}"
    if expected or actual:
        detail += f"; expected={expected}; actual={actual}"
    return detail


def _judge_display_reason(trace, judge, run):
    if run.get("error") or trace.get("error"):
        return {"reason": run.get("error") or trace.get("error") or "", "reason_source": "execution_error", "reason_stage": "execution", "is_formal_attribution": False}

    for key, source in (("wrong", "judge_wrong"), ("missing", "judge_missing"), ("extra", "judge_extra")):
        reason = _gap_reason(key, judge.get(key) or [])
        if reason:
            return {"reason": reason, "reason_source": source, "reason_stage": "judge", "is_formal_attribution": True}

    if judge.get("reasoning_summary"):
        return {"reason": judge.get("reasoning_summary"), "reason_source": "judge_reasoning_summary", "reason_stage": "judge", "is_formal_attribution": True}

    derivation = judge.get("verdict_derivation") or {}
    if derivation.get("why_verdict"):
        return {"reason": derivation.get("why_verdict"), "reason_source": "judge_verdict_derivation", "reason_stage": "judge", "is_formal_attribution": True}

    primary = judge.get("primary_assessment") or {}
    if primary.get("reasoning"):
        return {"reason": primary.get("reasoning"), "reason_source": "judge_primary_assessment", "reason_stage": "judge", "is_formal_attribution": True}

    for item in judge.get("fulfillment_assessments") or []:
        if isinstance(item, dict) and item.get("downstream_impact"):
            return {"reason": item.get("downstream_impact"), "reason_source": "fulfillment_assessment", "reason_stage": "judge", "is_formal_attribution": True}

    return {"reason": "", "reason_source": "", "reason_stage": "", "is_formal_attribution": False}


def _display_reason(trace, judge, attribute, run):
    judge_reason = _judge_display_reason(trace, judge, run)
    if judge_reason.get("reason_stage") == "execution":
        return judge_reason

    analysis_quality = attribute.get("analysis_quality") or {}
    has_attribution = bool(attribute.get("expectation_attributions"))
    if attribute.get("root_cause_hypothesis") and (analysis_quality.get("passed") is True or has_attribution):
        return {"reason": attribute.get("root_cause_hypothesis"), "reason_source": "attribute_root_cause", "reason_stage": "attribute", "is_formal_attribution": True}

    if judge_reason.get("reason"):
        return judge_reason

    if attribute.get("incomplete_reason"):
        return {"reason": attribute.get("incomplete_reason"), "reason_source": "attribute_incomplete_reason", "reason_stage": "attribute", "is_formal_attribution": False}

    return {"reason": attribute.get("root_cause_hypothesis") or "", "reason_source": "attribute_root_cause" if attribute.get("root_cause_hypothesis") else "", "reason_stage": "attribute" if attribute.get("root_cause_hypothesis") else "", "is_formal_attribution": False}


def _summary_reason_text(attribute, display_reason):
    if attribute.get("incomplete_reason"):
        return attribute.get("incomplete_reason") or ""
    if attribute.get("root_cause_hypothesis"):
        return attribute.get("root_cause_hypothesis") or ""
    return display_reason.get("reason") or ""


def _compact_summaries(trace, judge, attribute, run, fulfillment_assessments, expectation_attributions):
    judge_reason = _judge_display_reason(trace, judge, run)
    display_reason = _display_reason(trace, judge, attribute, run)
    blocking_count = len([item for item in fulfillment_assessments if isinstance(item, dict) and item.get("blocking")])
    analysis_quality = attribute.get("analysis_quality") or {}
    has_attribution = bool(expectation_attributions)
    has_incomplete = bool(attribute.get("incomplete_reason"))
    is_formal = bool(analysis_quality.get("passed") is True or has_attribution or display_reason.get("is_formal_attribution")) and not has_incomplete
    judge_summary = {
        "status": _display_status(trace, judge, run),
        "fulfillment_status": (judge.get("overall_fulfillment") or {}).get("status") or "",
        "verdict": judge.get("verdict") or "",
        "score": judge.get("score"),
        "reason": judge_reason.get("reason") or "",
        "reason_source": judge_reason.get("reason_source") or "",
        "reason_stage": judge_reason.get("reason_stage") or "",
        "is_formal_attribution": bool(judge_reason.get("is_formal_attribution")),
        "assessment_count": len(fulfillment_assessments),
        "blocking_count": blocking_count,
    }
    attribution_summary = {
        "causal_category": attribute.get("causal_category") or attribute.get("primary_error_type") or attribute.get("failure_category") or "",
        "attribution_count": len(expectation_attributions),
        "probe_count": len(attribute.get("probe_results") or []),
        "summary_text": _summary_reason_text(attribute, display_reason),
        "is_complete": bool(is_formal),
        "is_formal_attribution": bool(is_formal),
    }
    return judge_summary, attribution_summary


def _compact_run(run):
    trace = run.get("trace") or {}
    judge = _compact_mapping(run.get("judge") or {})
    attribute = _compact_mapping(run.get("attribute") or {})
    frontend_view = dict(run.get("frontend_view") or {})
    frontend_view.pop("raw_sections", None)
    compact_trace = dict(trace)
    compact_trace.pop("raw_response", None)
    compact_trace["project_fields"] = _compact_mapping(compact_trace.get("project_fields") or {})
    fulfillment_assessments = list(judge.get("fulfillment_assessments") or [])
    expectation_attributions = list(attribute.get("expectation_attributions") or [])
    judge_summary, attribution_summary = _compact_summaries(compact_trace, judge, attribute, run, fulfillment_assessments, expectation_attributions)
    return {
        "case_id": run.get("case_id"),
        "execution_mode": run.get("execution_mode"),
        "output_source": run.get("output_source") or trace.get("project_fields", {}).get("output_source"),
        "status": _display_status(trace, judge, run),
        "trace_id": trace.get("trace_id"),
        "trace": compact_trace,
        "judge": judge,
        "attribute": attribute,
        "judge_summary": judge_summary,
        "attribution_summary": attribution_summary,
        "cluster": run.get("cluster"),
        "check": run.get("check"),
        "frontend_view": frontend_view,
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
    status = _display_status(trace, judge, run)
    judge_reason = _judge_display_reason(trace, judge, run)
    display_reason = _display_reason(trace, judge, attribute, run)
    return {
        "index": index,
        "case_id": run.get("case_id"),
        "status": status,
        "error": run.get("error") or trace.get("error") or "",
        **display_reason,
        "judge_reason": judge_reason.get("reason") or "",
        "judge_reason_source": judge_reason.get("reason_source") or "",
        "judge_reason_stage": judge_reason.get("reason_stage") or "",
        "run": _compact_run(run),
    }


def _run_batch_job(job_id, project, cases, expected_intent, concurrency):
    job = BATCH_JOBS[job_id]
    total = len(cases)

    def on_case_done(index, run):
        job["done"] += 1
        job["events"].append(_case_event(index, run))
        if len(job["events"]) > MAX_BATCH_EVENTS:
            job["events"] = job["events"][-MAX_BATCH_EVENTS:]

    try:
        job["status"] = "running"
        job["result"] = pipeline.batch_run(project, cases, expected_intent=expected_intent, concurrency=concurrency, on_case_done=on_case_done)
        job["compact_result"] = _compact_batch_result(job["result"])
        job["done"] = total
        job["status"] = "completed"
    except Exception as exc:
        job["error"] = str(exc)
        job["status"] = "failed"



class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        frontend_aliases = {"/index.html", "/live.html", "/summary.html"}
        if path in frontend_aliases:
            return str(ROOT / "frontend" / path.lstrip("/"))
        if path.startswith("/frontend/"):
            return str(ROOT / path.lstrip("/"))
        return super().translate_path(path)

    def end_headers(self):
        if self.path.startswith("/frontend/") or self.path in {"/index.html", "/live.html", "/summary.html"}:
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
                result = pipeline.live_run(project, data.get("input") or {})
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
                result = pipeline.run_chain(project, data.get("input") or {}, expected_intent=data.get("expected_intent"))
            elif self.path == "/api/batch_run":
                concurrency = max(1, min(int(data.get("concurrency") or 4), 8))
                result = pipeline.batch_run(project, data.get("cases") or data.get("inputs") or [], expected_intent=data.get("expected_intent"), concurrency=concurrency)
            elif self.path == "/api/batch_start":
                concurrency = max(1, min(int(data.get("concurrency") or 4), 8))
                cases = data.get("cases") or data.get("inputs") or []
                job_id = uuid.uuid4().hex
                BATCH_JOBS[job_id] = {"job_id": job_id, "project_id": project, "status": "pending", "total": len(cases), "done": 0, "events": [], "result": None, "compact_result": None, "error": None}
                thread = threading.Thread(target=_run_batch_job, args=(job_id, project, cases, data.get("expected_intent"), concurrency), daemon=True)
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
