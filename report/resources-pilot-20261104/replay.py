"""P2 前的提交点重放实验：过程六轴（实际）的引文规则改成"可以写到字段"，在当时那次请求上重放一步，看模型怎么引。

只改重放用的对话副本里引文规则那一句；工具定义照过程 loop 当时挂的（submit / recall / read_material / search_material）
重建；模型给的工具调用一律不执行（complete_step），只取 submit 的引用用资源组件核对。不改现有代码、配置、数据。

    python report/resources-pilot-20261104/replay.py <数据目录> <recheck.json> <输出目录> [--only N] [--workers K]

样本：带过程轴提交的请求全部重放；含"跨字段多处"引用的为实验组，其余为对照组。
同一 case 内串行；不同 case 之间可并行（--workers）。已有结果的请求跳过，可断点续跑。
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.getcwd())

from impl.core.axis_loop.loop import SUBMIT, _Base, submit_tool  # noqa: E402
from impl.core.axis_loop.reader import Reader  # noqa: E402
from impl.core.project_loader import load_project  # noqa: E402
from impl.core.resources import cite  # noqa: E402
from impl.projects.llm_probe_loop.eval_axes.llm import axis_llm  # noqa: E402
from impl.tools.protocol import build_agno_tools  # noqa: E402

_spec = importlib.util.spec_from_file_location("recheck", os.path.join(os.path.dirname(__file__), "recheck.py"))
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

OLD_RULE = "{ref: 记录编号, quote: 从该记录逐字摘出的短句}"
NEW_RULE = ("{ref: 出处, quote: 从出处逐字摘出的短句}。出处写记录编号（整条记录），或写到字段：记录编号/fields/字段名"
            "（如 turn1/records/observations/14/fields/output）；要证明的是某一端（请求里写了什么、返回了什么）时，写到那个字段")


OLD_SCHEMA = "原文所在记录的编号（records[].id），只写编号"
NEW_SCHEMA = "出处：记录编号（records[].id），或写到字段：记录编号/fields/字段名"
# 材料里每个字段自带的来源位置（记录编号后面再接一段），长得像字段地址；--variant noref 时从副本里去掉
FIELD_REF = re.compile(r'"ref": "turn\d+/records/(?:observations/\d+|trace)/[^"]+"(, )?')


def pick(rows):
    by_request = defaultdict(list)
    for r in rows:
        by_request[(r["run"], r["request"])].append(r["loose"]["verdict"])
    cross = sorted(k for k, v in by_request.items() if any(x.startswith("过：跨字段") for x in v))
    return cross, sorted(set(by_request) - set(cross))


def tools():
    dummy = type("Dummy", (), {"history": None, "call_id": lambda self, c: ""})()
    return build_agno_tools([submit_tool(list(rc.PROCESS)), _Base.recall_tool(dummy), *Reader(lambda: {}, 0).tools()])


def rewrite(messages, variant):
    """引文规则与提交格式里 ref 的说明一起改；noref 另把材料里字段自带的来源 ref 去掉。返回 (副本, 各项替换次数)。"""
    out, hits = [], {"rule": 0, "schema": 0, "field_ref": 0}
    for m in messages:
        m = dict(m)
        text = m.get("content")
        if isinstance(text, str):
            hits["rule"] += text.count(OLD_RULE)
            hits["schema"] += text.count(OLD_SCHEMA)
            text = text.replace(OLD_RULE, NEW_RULE).replace(OLD_SCHEMA, NEW_SCHEMA)
            if variant == "noref":
                text, n = FIELD_REF.subn("", text)
                hits["field_ref"] += n
            m["content"] = text
        out.append(m)
    return out, hits


def contexts(data, event, run, wanted):
    """recheck.main 同样的口径：每个想要的请求 → (那次请求的对话, 那时看到过的, 引用范围)。"""
    run_id = event["run"]["eval_axes"]["run_id"]
    table, scopes = rc.table_of(run), rc.strict_scopes(event)
    folder = f"{data}/calls/{run_id}"
    records = [json.load(open(f"{folder}/{f}")) for f in sorted(os.listdir(folder))]
    loop_seen, out = {}, {}
    for index, record in enumerate(records):
        stage = (record["response"].get("runtime") or {}).get("stage")
        here = rc.merge(loop_seen.setdefault(stage, {}), rc.seen_in(record["messages"]))
        if index in wanted:
            seen = {k: [rc.restore(v, table.get(k).body if table.get(k) else None, here) for v in vs] for k, vs in here.items()}
            old = [m for m in record["response"]["run_messages"] if m.get("role") == "assistant"][-1]
            out[index] = (record["messages"], seen, old, stage)
    return table, scopes, out


def judge(table, scopes, seen, reply):
    rows = []
    for t in reply.get("tool_calls") or []:
        if t["function"]["name"] != SUBMIT:
            continue
        try:
            args = json.loads(t["function"]["arguments"])
        except ValueError:
            rows.append({"task": None, "error": "submit 参数不是 JSON"})
            continue
        task = args.get("task_id")
        if task not in rc.PROCESS:
            continue
        for part in ("actual", "unexpected"):
            for item in (args.get("payload") or {}).get(part) or []:
                for q in item.get("quotes") or []:
                    ref, quote = str(q.get("ref") or ""), str(q.get("quote") or "")
                    rows.append({"task": task, "row": item.get("id"), "part": part, "ref": ref, "quote": quote,
                                 "field_level": "/fields/" in ref,
                                 "strict": rc.new_result(cite(table, rc.to_uri(ref), quote, seen=seen,
                                                              scope=scopes.get(task, set()), view=task)),
                                 "loose": rc.new_result(cite(table, rc.to_uri(ref), quote, seen=seen, view=task))})
    return rows


def run_case(data, event, run, jobs, out_dir, client, functions, variant):
    table, scopes, ctx = contexts(data, event, run, {i for _, i, _ in jobs})
    for run_id, index, group in jobs:
        path = f"{out_dir}/{run_id}-{index}.json"
        if os.path.exists(path):
            continue
        messages, seen, old, stage = ctx[index]
        sent, hits = rewrite(messages, variant)
        result = {"run": run_id, "request": index, "group": group, "case": event["case_id"], "variant": variant, "hits": hits}
        if not (hits["rule"] and hits["schema"]):
            result["error"] = "对话里没找到引文规则或提交格式的原句"
        else:
            try:
                step = client.complete_step(sent, functions, trace_id=f"resources-replay-{run_id}",
                                            stage=f"resources_replay/{stage}")
                result.update(reply=step.message, rows=judge(table, scopes, seen, step.message))
            except Exception as exc:  # 端点失败如实记下，不重试成别的模型
                result["error"] = f"{type(exc).__name__}: {exc}"
        result["old_rows"] = judge(table, scopes, seen, old)
        json.dump(result, open(path, "w"), ensure_ascii=False, indent=1)
        print(run_id, index, group, result.get("error") or f"{len(result['rows'])} 条引用", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data"), ap.add_argument("recheck"), ap.add_argument("out")
    ap.add_argument("--only", type=int, default=0, help="只跑前 N 个请求（试跑）")
    ap.add_argument("--variant", choices=("schema", "noref"), default="schema",
                    help="schema：改引文规则与提交格式；noref：再去掉材料里字段自带的来源 ref")
    ap.add_argument("--workers", type=int, default=1, help="并行的 case 数（case 内始终串行）")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cross, control = pick(json.load(open(a.recheck)))
    jobs = [(r, i, "cross") for r, i in cross] + [(r, i, "control") for r, i in control]
    if a.only:
        jobs = jobs[:a.only]
    runs, events = rc.load(a.data)
    by_run = {e["run"]["eval_axes"]["run_id"]: e for e in events}
    per_case = defaultdict(list)
    for job in jobs:
        per_case[job[0]].append(job)
    client, functions = axis_llm(load_project("llm_probe_loop"), role="judge"), tools()
    print(f"跨字段 {len(cross)} 个请求、对照 {len(control)} 个；本次跑 {len(jobs)} 个，{len(per_case)} 个 case", flush=True)
    with ThreadPoolExecutor(a.workers) as pool:
        futures = [pool.submit(run_case, a.data, by_run[r], runs[by_run[r]["case_id"]], js, a.out, client, functions, a.variant)
                   for r, js in per_case.items()]
        for f in futures:
            f.result()


if __name__ == "__main__":
    main()
