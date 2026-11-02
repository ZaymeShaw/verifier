"""实验 2：70 道多轮题没有业务运行记录，只用用户原话写需求。

每轮一份：本轮用户原话为 want，之前各轮的用户原话为 history（没有业务答复）。
整 case 一份：各轮用户原话都为 want（与现行投影同形，只是没有业务答复）。
目的：看哪些轮离开业务上一轮的答复写不出需求；看整 case 一份在改口类题上丢需求 / 互相矛盾有多常见。
用法：python exp2_user_only.py <输出目录> [case_id,...]
"""
import copy, hashlib, json, sys, time
from types import SimpleNamespace

ROOT = "/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-runC/verifier"
sys.path.insert(0, ROOT)
from impl.core.project_loader import load_project
from impl.projects.llm_probe.eval_axes.adapters import expectations

OUT = sys.argv[1]
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
project = load_project("llm_probe")
cases = json.load(open(f"{OUT}/multiturn_cases.json"))


def material(sources):
    body = {"sources": sources, "missing": []}
    body["sha256"] = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return body


def src(ref, side, turn, component, value):
    return dict(id=ref, side=side, turn=turn, component=component, value=value, scope="request", trace_refs=[])


def write(req, tag):
    runtime = SimpleNamespace(spec=project, trace_id=f"exp2:{tag}:{time.time():.0f}", ensure_time_left=lambda *_: None)
    try:
        return {"expectations": expectations.run({"requirements": copy.deepcopy(req)}, None, runtime).output["expectations"]}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


results = []
for case in cases:
    if ONLY and case["id"] not in ONLY:
        continue
    turns = case["turns"]
    whole = [src(f"t{n}.user", "want", f"t{n}", "user", text) for n, text in enumerate(turns, 1)]
    rec = {"case": case["id"], "src": case["src"], "turns": turns, "global": write(material(whole), f"{case['id']}:global"),
           "per_turn": {}}
    for n, text in enumerate(turns, 1):
        tid = f"t{n}"
        history = [src(f"{tid}.history.{i}", "history", tid, "history", {"role": "user", "content": prev})
                   for i, prev in enumerate(turns[:n - 1])]
        rec["per_turn"][tid] = write(material(history + [src(f"{tid}.user", "want", tid, "user", text)]), f"{case['id']}:{tid}")
    results.append(rec)
    json.dump(results, open(f"{OUT}/exp2_results.json", "w"), ensure_ascii=False, indent=1)
    print(case["id"], "global", len(rec["global"].get("expectations", [])),
          {t: len(v.get("expectations", [])) if "expectations" in v else v["error"][:60] for t, v in rec["per_turn"].items()}, flush=True)
print("done")
