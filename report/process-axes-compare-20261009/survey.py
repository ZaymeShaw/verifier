"""只读盘点：把每个 case 的冻结案卷压成可人工核缺陷的证据清单（不调模型）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import experiment_io as io

sys.path.insert(0, str(io.ROOT))
sys.path.insert(0, str(io.HERE))

import doc_rebuild as D  # noqa: E402


def text(v, n=4000):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f"...<+{len(s)-n}>"


def value(row, name):
    info = (row.get("fields") or {}).get(name) or {}
    return info.get("value") if info.get("status") == "available" and "value" in info else None


def dump(tag):
    frozen = io.load_json(io.HERE / "frozen" / f"case_{tag}.json")
    out = []
    out.append(f"### {tag}  run={frozen['run_id']} desc={frozen.get('description')!r}")
    out.append(f"expectations={len(frozen['expectations'])} records={len(frozen['records'])}")
    dossier = D.build(frozen)
    rows = {r["id"]: r for r in dossier["records"]}
    out.append("\n## expectations")
    for e in frozen["expectations"]:
        out.append(f"- {e.get('expectation_id')}: {text(e.get('statement'), 400)} | cond={e.get('condition')}")
    out.append("\n## workflow definitions")
    for rid, row in rows.items():
        if row.get("kind") == "definitions":
            out.append(f"  [{rid}] {text(value(row, 'steps'), 2500)}")
    out.append("\n## tool calls (in order)")
    tools = sorted((r for r in dossier["records"] if r.get("kind") == "tool_calls" and "/tools/" in r["id"]),
                   key=lambda r: r["id"])
    for r in tools:
        out.append(f"  [{r['id']}] name={r.get('name')} args={text(value(r, 'arguments'), 700)}")
        out.append(f"      result={text(value(r, 'result'), 700)} err={text(value(r, 'error'), 300)}")
    out.append("\n## model calls")
    calls = sorted((r for r in dossier["records"] if r.get("kind") == "model_calls"), key=lambda r: r["id"])
    for r in calls:
        ex = value(r, "exact_request") or {}
        msgs = ex.get("messages") if isinstance(ex, dict) else None
        last_user = ""
        if isinstance(msgs, list):
            us = [m.get("content") for m in msgs if m.get("role") == "user"]
            last_user = text(us[-1], 800) if us else ""
        o = value(r, "output")
        out.append(f"  [{r['id']}] model={value(r,'model')} status={value(r,'status')}")
        out.append(f"      last_user={last_user}")
        out.append(f"      output={text(o, 1500)}")
    out.append("\n## delivered / gaps")
    for r in dossier["records"]:
        if r.get("kind") in ("delivered_output",):
            out.append(f"  [{r['id']}] {text(value(r, 'output'), 2500)}")
    for g in dossier.get("gaps") or []:
        out.append(f"  gap {g.get('id')}: {text(g, 500)}")
    out.append("\n## trace_analysis structure (recorded)")
    st = frozen.get("structure") or {}
    out.append("  workflow_steps=" + text(st.get("workflow_steps") or st.get("steps"), 2000))
    out.append("  suspects=" + text(st.get("suspects"), 3000))
    return "\n".join(out)


def main():
    io.init_secret_guard()
    tags = sys.argv[1:] or list(io.CASES)
    for tag in tags:
        body = dump(tag)
        io.save_text(io.HERE / "survey" / f"{tag}.txt", body, exclusive=False)
        print(f"=== {tag} -> survey/{tag}.txt ({len(body)} chars)")
    print("done")


if __name__ == "__main__":
    main()
