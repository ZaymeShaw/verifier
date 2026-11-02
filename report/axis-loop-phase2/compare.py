"""S8 对比：基线（llm_probe）vs axis loop 各轮，主结论对 gold、六轴逐轴、成本。用法：python compare.py r1-t [r2-tk]"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
GOLD = json.loads((HERE.parents[0] / "eval-main-axis/gold.json").read_text())
LOOP = {"做成了": "fulfilled", "做成": "fulfilled", "没做成": "not_fulfilled", "不确定": "not_evaluable", "做不了": "not_evaluable"}
PROCESS = ("intent_understanding", "planning_routing", "tool_execution", "context_memory", "knowledge_data", "model_capability")


def rows(name):
    return {json.loads(x)["id"]: json.loads(x) for x in (HERE / "runs" / f"{name}.jsonl").read_text().splitlines()}


def gold(case_id):
    g = GOLD.get(case_id[17:] + "-1020") or GOLD.get(case_id[17:])
    return g or {}


def verdict(row):
    if "judge_status" in row:
        return row["judge_status"] or "?"
    mv = (row.get("main_verdict") or {}).get("verdict")
    return LOOP.get(mv, f"失败:{row.get('status')}") if mv else f"失败:{row.get('status')}"


def main():
    names = sys.argv[1:]
    runs = {"base": rows("base"), **{n: rows(n) for n in names}}
    ids = sorted(runs["base"])
    hits = {n: 0 for n in runs}
    graded = 0
    print("| case | gold | " + " | ".join(runs) + " |")
    print("|---" * (2 + len(runs)) + "|")
    for i in ids:
        g = gold(i)
        accept = g.get("accept") or ([g["gold"]] if g.get("gold") else [])
        graded += bool(accept)
        cells = []
        for n, r in runs.items():
            v = verdict(r[i]) if i in r else "—"
            # 有待定项没达到（blocking 为空）：做成 / 没做成都算对（10-25 用户定）
            pending = ((r.get(i, {}).get("main_verdict") or {}).get("composition") or {}).get("pending_unmet")
            ok = v in accept or bool(pending and v in ("fulfilled", "not_fulfilled") and {"fulfilled", "not_fulfilled"} & set(accept))
            hits[n] += ok
            raw = (r.get(i, {}).get("main_verdict") or {}).get("verdict") if n != "base" else None
            cells.append(f"{raw or v}{' ✓' if ok else (' ✗' if accept else '')}")
        print(f"| {i[17:]} | {g.get('gold', '无')} | " + " | ".join(cells) + " |")
    print(f"\n主结论命中 gold（{graded} 条有 gold）：" + "，".join(f"{n} {hits[n]}" for n in runs))
    for n in names:
        same = sum(runs[n][i]["six"][a] == runs["base"][i]["six"].get(a) for i in ids if i in runs[n] for a in PROCESS)
        total = sum(1 for i in ids if i in runs[n]) * len(PROCESS)
        print(f"\n六轴逐轴与基线一致：{n} {same}/{total}")
        for a in PROCESS:
            dist = lambda rr: {v: sum(1 for i in ids if i in rr and rr[i]["six"].get(a) == v) for v in ("sound", "problematic", "not_evaluable")}
            print(f"  {a}: base {dist(runs['base'])} | {n} {dist(runs[n])}")
        secs = [runs[n][i]["seconds"] for i in ids if i in runs[n]]
        calls = [runs[n][i]["llm_calls"] or 0 for i in ids if i in runs[n]]
        print(f"  成本 {n}：平均 {sum(secs)/len(secs):.0f}s / 条，LLM 调用平均 {sum(calls)/len(calls):.1f} 次，最多 {max(calls)}")
    bs = [r["latency_s"] for r in runs["base"].values()]
    bc = [sum((r.get("axis_calls") or {}).values()) if isinstance(r.get("axis_calls"), dict) else 0 for r in runs["base"].values()]
    print(f"  成本 base：平均 {sum(bs)/len(bs):.0f}s / 条，轴调用记录平均 {sum(bc)/len(bc):.1f}")


if __name__ == "__main__":
    main()
