"""Per-case digest of the four harness traces from gateway llm_calls.

usage: python3 -I digest.py <root new-run dir> <out dir>
"""
import json
import os
import sys

ROOT, OUT = sys.argv[1], sys.argv[2]

SRC = {
    "claude": ("claude/dual_datasetA_full/claude/cases", lambda d: d),
    "pi": ("pi/triple_datasetA_full/pi/cases", lambda d: d[3:]),
    "insurance": ("insurance-rerun/dual_datasetA_full/insurance/cases", lambda d: d[4:]),
    "opencode": ("opencode/triple_datasetA_full/opencode/cases", None),
}


def text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for b in c:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    out.append(text_of(b.get("content")))
        return "\n".join(out)
    return ""


def tool_results(msgs):
    """yield (tool_call_id, text) from a request's messages, both protocols."""
    for m in msgs:
        if m.get("role") == "tool":
            yield m.get("tool_call_id"), text_of(m.get("content"))
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    yield b.get("tool_use_id"), text_of(b.get("content"))


def user_texts(msgs):
    for m in msgs:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            continue
        t = text_of(c)
        if t and "<system-reminder>" not in t[:30]:
            yield t
        elif t:
            # claude: real prompt is the last non-reminder text block
            for b in c if isinstance(c, list) else []:
                tt = b.get("text", "") if isinstance(b, dict) else ""
                if tt and not tt.startswith("<system-reminder>"):
                    yield tt


def summarize_result(t, limit):
    try:
        j = json.loads(t)
    except Exception:
        return t[:limit].replace("\n", " ")
    if not isinstance(j, dict):
        return t[:limit]
    if isinstance(j.get("result"), dict):
        r = j["result"]
        ex = r.get("execution") or {}
        parts = [f"status={ex.get('status')}"]
        for k, v in r.items():
            if k not in ("data", "facts", "field_descriptions", "execution"):
                parts.append(f"{k}={json.dumps(v, ensure_ascii=False)[:300]}")
        ex = {k: v for k, v in ex.items() if k != "status"}
        if ex:
            parts.append("execution=" + json.dumps(ex, ensure_ascii=False)[:600])
        for k, v in j.items():
            if k != "result":
                parts.append(f"{k}={json.dumps(v, ensure_ascii=False)[:300]}")
        data = r.get("data")
    else:
        parts = [f"ok={j.get('ok')} status={j.get('status')}"]
        for k in ("error", "message", "gaps", "limitations", "execution", "control"):
            if j.get(k):
                parts.append(f"{k}={json.dumps(j[k], ensure_ascii=False)[:400]}")
        if j.get("hint"):
            parts.append("hint=" + str(j["hint"])[:200])
        data = j.get("data")
    if data is not None:
        parts.append("data=" + json.dumps(drop_nulls(data), ensure_ascii=False))
    s = " ; ".join(parts)
    return s[:limit]


def drop_nulls(o):
    if isinstance(o, dict):
        return {k: drop_nulls(v) for k, v in o.items() if v is not None and k not in ("field_descriptions",)}
    if isinstance(o, list):
        return [drop_nulls(v) for v in o]
    return o


def load_calls(path):
    calls = []
    for line in open(path):
        r = json.loads(line)
        calls.append(r)
    calls.sort(key=lambda r: (r.get("ts") or r.get("started_at") or "", r.get("seq") or 0))
    return calls


def digest(calls, limit):
    lines = []
    seen_users = []
    seen_tr = set()
    pending = {}
    main = [c for c in calls if (c.get("request") or {}).get("tools")]
    for i, c in enumerate(main):
        req = c.get("request") or {}
        msgs = req.get("messages") or []
        for u in user_texts(msgs):
            if u not in seen_users:
                seen_users.append(u)
                lines.append(f"\n### USER[{len(seen_users)}]: {u.strip()[:600]}")
        for tid, t in tool_results(msgs):
            if tid in seen_tr:
                continue
            seen_tr.add(tid)
            lines.append(f"    <- {pending.get(tid,'?')} [{tid[-6:] if tid else ''}]: {summarize_result(t, limit)}")
        resp = (c.get("response") or {}).get("response") or {}
        ch = (resp.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        st = c.get("state")
        txt = (msg.get("content") or "").strip()
        tcs = msg.get("tool_calls") or []
        tag = f"#{i+1}" + (f" state={st}" if st and st != "succeeded" else "")
        if tcs:
            if txt:
                lines.append(f"  {tag} say: {txt[:300]}")
            for tc in tcs:
                fn = tc.get("function") or {}
                name = fn.get("name", "").split("__")[-1]
                pending[tc.get("id")] = name
                lines.append(f"  {tag} CALL {name}({fn.get('arguments','')[:400]}) [{(tc.get('id') or '')[-6:]}]")
        else:
            lines.append(f"  {tag} FINAL(model): {txt[:3000]}")
    return lines


def main():
    os.makedirs(OUT, exist_ok=True)
    for h, (rel, norm) in SRC.items():
        base = os.path.join(ROOT, rel)
        for d in sorted(os.listdir(base)):
            p = os.path.join(base, d)
            if not os.path.isdir(p) or not os.path.exists(os.path.join(p, "llm_calls.jsonl")):
                continue
            if norm is None:
                cid = json.load(open(os.path.join(p, "identity.json")))["case_id"]
            else:
                cid = norm(d)
            calls = load_calls(os.path.join(p, "llm_calls.jsonl"))
            lines = [f"# {h} {cid}  llm_calls={len(calls)}"]
            lines += digest(calls, 2500)
            if h == "insurance":
                cj = json.load(open(os.path.join(base, f"INS_{cid}.json")))
                for t in cj.get("turns", []):
                    lines.append(f"\n## DELIVERED turn{t['index']}: {t.get('final_text') or t.get('answer')}")
                lines.append(f"## native completeness={cj['response'].get('completeness')} gaps={cj['response'].get('gaps')} limitations={cj['response'].get('limitations')}")
            os.makedirs(os.path.join(OUT, cid), exist_ok=True)
            with open(os.path.join(OUT, cid, f"{h}.md"), "w") as f:
                f.write("\n".join(lines) + "\n")


main()
