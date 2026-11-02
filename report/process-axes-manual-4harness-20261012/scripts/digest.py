"""Per-case digest from extracted llm_trace DATA json (share_20261012).

usage: python3 -I digest.py <data dir> <out dir> [limit]
writes <out>/<case>/<harness>.md : user turns, model calls (say/CALL), tool results as the model saw them,
model's last text per turn (FINAL(model)) and the harness-delivered final_text (DELIVERED).
"""
import json, os, sys

DATA, OUT = sys.argv[1], sys.argv[2]
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 2500
HARNESSES = ["claude", "pi", "insurance_old", "insurance_harness"]


def case_key(cid):
    return cid.split("_")[-1]


def blocks(m):
    c = m.get("content")
    if isinstance(c, list):
        return c
    if isinstance(c, str) and c.startswith("[{"):
        try:
            import ast
            return ast.literal_eval(c)
        except Exception:
            return None
    return None


def text_of(c):
    if isinstance(c, str):
        return c
    if isinstance(c, dict):
        return text_of(c.get("content") if "content" in c else c.get("text", ""))
    if isinstance(c, list):
        return "\n".join(text_of(b.get("text") if b.get("type") == "text" else b.get("content")) for b in c if isinstance(b, dict))
    return ""


def tool_results(msgs):
    for m in msgs:
        if m.get("role") == "tool":
            yield m.get("tool_call_id"), m.get("text") or text_of(m.get("content"))
        bl = blocks(m) if m.get("role") == "user" else None
        for b in bl or []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                yield b.get("tool_use_id"), text_of(b.get("content"))


def user_texts(msgs):
    for m in msgs:
        if m.get("role") != "user" or m.get("tool_call_id"):
            continue
        bl = blocks(m)
        if bl:
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in bl):
                continue
            for b in bl:
                t = b.get("text", "") if isinstance(b, dict) else ""
                if t and not t.lstrip().startswith("<system-reminder>"):
                    yield t
        else:
            t = m.get("text") or ""
            if t and not t.lstrip().startswith("<system-reminder>"):
                yield t


def short(t, limit):
    return t[:limit].replace("\n", " ") + (f" …[+{len(t)-limit}]" if len(t) > limit else "")


def digest(case, limit):
    lines, seen_u, seen_tr, pending = [], [], set(), {}
    calls = case["calls"]
    last_text = None
    for i, c in enumerate(calls):
        if not c.get("tool_names"):
            lines.append(f"  #{c['seq']} (no-tools side call) out: {short(c.get('assistant') or '', 200)}")
            continue
        msgs = c.get("messages") or []
        for u in user_texts(msgs):
            if u not in seen_u:
                if last_text is not None:
                    lines.append(f"  FINAL(model): {last_text}")
                    last_text = None
                seen_u.append(u)
                lines.append(f"\n### USER[{len(seen_u)}]: {u.strip()[:800]}")
        for tid, t in tool_results(msgs):
            if tid in seen_tr:
                continue
            seen_tr.add(tid)
            lines.append(f"    <- {pending.get(tid, '?')} len={len(t)}: {short(t, limit)}")
        st = c.get("state")
        tag = f"#{c['seq']}" + (f" state={st}" if st and st != "succeeded" else "")
        txt = (c.get("assistant") or "").strip()
        tcs = c.get("tool_calls") or []
        if tcs:
            if txt:
                lines.append(f"  {tag} say: {short(txt, 400)}")
            for tc in tcs:
                name = tc.get("name", "").split("__")[-1].replace("insurance-tools_", "")
                pending[tc.get("id")] = name
                lines.append(f"  {tag} CALL {name}({str(tc.get('arguments', ''))[:400]})")
            last_text = None
        else:
            lines.append(f"  {tag} text-only reply ({len(txt)} chars)")
            last_text = txt
    if last_text is not None:
        lines.append(f"  FINAL(model): {last_text}")
    finals = [l[len("  FINAL(model): "):] for l in lines if l.startswith("  FINAL(model): ")]
    norm = lambda x: "".join((x or "").split())
    for t in case["overview"].get("turns", []):
        ft = t.get("final_text") or ""
        if any(norm(ft) == norm(f) for f in finals):
            lines.append(f"## DELIVERED turn{t['index']}: = FINAL(model)")
        else:
            lines.append(f"\n## DELIVERED turn{t['index']} (DIFFERS from model final): {ft}")
    return lines


def main():
    for h in HARNESSES:
        d = json.load(open(os.path.join(DATA, h + ".json")))
        for case in d["cases"]:
            if case.get("latest") is False:
                continue
            k = case_key(case["overview"]["case_id"])
            lines = [f"# {h} {k}  llm_calls={len(case['calls'])}"] + digest(case, LIMIT)
            os.makedirs(os.path.join(OUT, k), exist_ok=True)
            open(os.path.join(OUT, k, h + ".md"), "w").write("\n".join(lines) + "\n")


main()
