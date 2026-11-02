"""轮询 8021 上的批次，落盘 batch-status.json，并打印进度与本批过程轴提示是否还带读证流水。"""
import glob, json, statistics, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
job = (HERE / "job_id").read_text().strip()
req = urllib.request.Request("http://127.0.0.1:8021/api/batch_status",
                             data=json.dumps({"project": "llm_probe", "job_id": job}).encode(),
                             headers={"Content-Type": "application/json"})
data = json.load(urllib.request.urlopen(req, timeout=60))
(HERE / "batch-status.json").write_text(json.dumps(data, ensure_ascii=False))
print("status", data.get("status"), "done", data.get("done"), "/", data.get("total"), data.get("error") or "")
since = sys.argv[1] if len(sys.argv) > 1 else "2026-09-30T08:0"
calls = []
for f in glob.glob("impl/data/context_store/llm_probe/*insurance-real-*/judge-*.json"):
    j = json.load(open(f))
    if j["created_at"] < since:
        continue
    rt = (j.get("response") or {}).get("runtime") or {}
    stage = str(rt.get("stage") or "")
    audit = None
    if "process_" in stage:
        try:
            user = json.loads(next(m for m in j["messages"] if m.get("role") == "user")["content"])
            audit = "evidence_audit" in user["dossier_view"]["structure"]
        except Exception:
            pass
    calls.append((stage.replace("llm_probe_process_", "").replace("llm_probe_", ""), j.get("elapsed_ms", 0) / 1000,
                  len(rt.get("attempts") or []), audit))
by = {}
for stage, sec, att, _ in calls:
    by.setdefault(stage, []).append((sec, att))
for stage, rows in sorted(by.items()):
    print(f"  {stage:28s} n={len(rows):3d} 中位 {statistics.median(r[0] for r in rows):5.0f}s  最大 {max(r[0] for r in rows):5.0f}s  重试 {sum(r[1] > 1 for r in rows)}")
print("  过程轴提示带流水:", sum(1 for c in calls if c[3]), " 不带:", sum(1 for c in calls if c[3] is False))
