"""Offline coverage audit of frozen traces. Never calls an LLM or business service.

Records input hashes and checks that comparison pointers resolve, original data is
preserved, and every current model call remains in the context axis check scope.
This measures evidence plumbing, not semantic judgment accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from impl.core.schema import normalize_run_trace
from impl.projects.llm_probe.business_trace.comparisons import build_comparison_index
from impl.projects.llm_probe.business_trace.dossier import build_dossier, dossier_ids, expand_content
from impl.projects.llm_probe.business_trace.reader import redact
from impl.projects.llm_probe.business_trace.links import build_links


def audit(path: Path, *, snapshot_only: bool) -> dict:
    raw = path.read_bytes()
    value = json.loads(raw)
    if snapshot_only:
        # A saved run.content is not an observed HTTP response. Leave delivery absent.
        trace = SimpleNamespace(turn_records=[], normalized_request={}, extracted_output={})
        snap = value
        snapshots = [snap]
    else:
        trace = normalize_run_trace(value)
        snap = trace.project_fields.get("business_trace")
        snapshots = [(t.get("project_fields") or {}).get("business_trace") for t in trace.turn_records] if trace.turn_records else [snap]
    data = build_dossier(trace, snap)
    index = build_comparison_index(data)
    known = dossier_ids(data)
    errors = []
    for source, original in zip(data["sources"], snapshots, strict=True):
        if original and "original_records" in source:
            if expand_content(source["original_records"], data["contents"]) != redact(original["records"]):
                errors.append(f"source changed: {source['id']}")
    refs = []
    for call in index["model_io"]:
        refs.extend([call["call_ref"], *call["input_message_refs"]])
        if call["output_message_ref"]:
            refs.append(call["output_message_ref"])
    for pair in index["tool_to_model_input"]:
        refs.extend(pair[k] for k in ("tool_ref", "message_ref", "call_ref"))
    for group in index["delivery_candidates"]:
        refs.append(group["request_response_ref"])
        for key in ("model_output_refs", "step_refs", "stored_output_refs", "delivered_output_refs", "state_refs"):
            refs.extend(group[key])
    errors.extend(f"unresolved: {ref}" for ref in refs if ref not in known)
    links = {link["link_id"] for link in build_links(data, axis_id="context_memory")["links"]}
    calls = [c for c in data["model_calls"] if c.get("scope") == "current"]
    errors.extend(f"uncovered call: {c['id']}" for c in calls if f"κ:input:{c['id']}" not in links)
    return {
        "path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(raw).hexdigest(),
        "turns": len(data["sources"]), "model_calls": len(calls),
        "tool_input_pairs": len(index["tool_to_model_input"]),
        "stored_outputs": sum(len(g["stored_output_refs"]) for g in index["delivery_candidates"]),
        "delivered_outputs": sum(len(g["delivered_output_refs"]) for g in index["delivery_candidates"]),
        "context_links": len(links), "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    samples = [(p, True) for p in sorted((ROOT / "report/business-trace-agno-20260913/snapshots").glob("snap-*.json"))]
    samples += [(p, False) for p in sorted((ROOT / "report/process-dossier-20260920/clean-traces").glob("*.json"))]
    if not samples:
        raise SystemExit("No frozen traces found; nothing was verified.")
    rows = [audit(p, snapshot_only=only) for p, only in samples]
    output = {"mode": "offline_evidence_audit", "semantic_accuracy_measured": False,
              "samples": len(rows), "passed": sum(not r["errors"] for r in rows),
              "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "rows"}, ensure_ascii=False))
    return 0 if output["passed"] == output["samples"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
