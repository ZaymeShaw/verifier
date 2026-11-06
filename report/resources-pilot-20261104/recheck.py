"""P1 离线复核（spec/alg/resources.md §7）：用资源组件重核过程六轴（实际）的全部引用，对比现有核对的结果。

只读：8037 运行记录（latest_runs.sqlite3 拷贝）、结果状态（batch_status 拷贝）、这 22 条 run 的调用记录拷贝。

    python report/resources-pilot-20261104/recheck.py <数据目录> <输出.json>

数据目录里要有 latest_runs_8037.sqlite3、status_8037.json、calls/<run_id>/*.json。
"""
import json
import os
import re
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.getcwd())

from impl.core.resources import ResourceTable, cite  # noqa: E402
from impl.core.schema.normalize import normalize_run_trace  # noqa: E402
from impl.projects.llm_probe_loop.business_trace.dossier import build_dossier  # noqa: E402
from impl.projects.llm_probe_loop.business_trace.providers import langfuse  # noqa: E402

PROCESS = ("intent_understanding", "planning_routing", "tool_execution", "context_memory", "knowledge_data", "model_capability")
READERS = ("read_material", "recall")
END_NAMES = {"input": "输入端", "output": "输出端"}
PLACEHOLDER = re.compile(r"〔同 (.+?) 里已给过的那段，(\d+) 字〕")  # axis_loop/reader.py 的去重占位


def to_uri(ref):
    """过程轴现在写的是裸记录编号（turn1/records/observations/15），这里转成资源地址。"""
    return ref if "://" in ref else f"trace://{ref.strip('/')}"


def role_label(role):
    if role is None:
        return None
    if role.part == "block":
        return "整块"
    if role.part == "attribute":
        return "属性"
    if not role.field:
        return "整块字段"
    return "+".join(END_NAMES[e] for e in role.ends) or "其他字段"


def load(data):
    db = sqlite3.connect(f"file:{data}/latest_runs_8037.sqlite3?mode=ro", uri=True)
    runs = {json.loads(c)["id"]: json.loads(r) for c, r in db.execute(
        "select case_json, run_json from current_cases where project='llm_probe_loop'")}
    status = json.load(open(f"{data}/status_8037.json"))
    return runs, status["events"]


def table_of(run):
    trace = normalize_run_trace(run["trace"])
    fields = trace.project_fields if isinstance(trace.project_fields, dict) else {}
    table = ResourceTable()
    langfuse.mount(build_dossier(trace, fields.get("business_trace")), table)
    return table


def strict_scopes(event):
    out = next(r["output"] for r in event["run"]["eval_axes"]["results"] if r["axis_id"] == "trace_analysis")
    return {v["axis"]: {f"trace://{rec['id']}" for rec in (v.get("full") or {}).get("records") or []} for v in out["views"]}


def records_in(value, found):
    """每条记录：工具返回里是 {id, content[, path]}（recall 的返回套在 result 里）；推送里内联的是平铺的记录 {id, fields, …}。"""
    if isinstance(value, dict):
        if isinstance(value.get("id"), str) and "error" not in value:
            if "content" in value:
                found.append(value)
            elif "fields" in value:
                found.append({"id": value["id"], "content": value})
        for v in value.values():
            records_in(v, found)
    elif isinstance(value, list):
        for v in value:
            records_in(v, found)
    return found


def nest(path, content):
    """按 path 读回的是记录里的一个节点：套回原位置，块内位置才与整条记录一致。"""
    for token in reversed([t for t in (path or "").split("/") if t]):
        content = {token: content}
    return content


def inline_materials(text):
    """推送里按【标准名】分段内联的材料，逐段解析 JSON。"""
    out = []
    for block in re.split(r"\n?【[^】\n]+】\n", text or "")[1:]:
        try:
            out.append(json.loads(block.split("\n【", 1)[0]))
        except ValueError:
            continue
    return out


def seen_in(messages):
    """这份上下文里模型看到的记录：读工具的返回 + 推送里内联的材料。"""
    names = {t["id"]: t["function"]["name"] for m in messages for t in (m.get("tool_calls") or [])}
    values = []
    for m in messages:
        if m["role"] == "user" and isinstance(m.get("content"), str):
            values += inline_materials(m["content"])
        elif m["role"] == "tool" and names.get(m.get("tool_call_id")) in READERS:
            try:
                values.append(json.loads(m["content"]))
            except (TypeError, ValueError):
                continue
    seen = {}
    for value in values:
        for rec in records_in(value, []):
            seen.setdefault(f"trace://{rec['id']}", []).append(nest(rec.get("path"), rec["content"]))
    return seen


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def restore(version, canonical, seen):
    """去重是展示层做的（读工具把别处已给过的长段换成"〔同 X 里已给过的那段，N 字〕"，X = [材料 的 ]记录编号），
    还原也由这里（调用方）做：
    占位处在这一块正文的同一位置取原文，且这段原文确实在 X 看到的某份里出现过，才算看到过。"""
    if isinstance(version, str):
        m = PLACEHOLDER.fullmatch(version)
        if m and isinstance(canonical, str) and len(canonical) == int(m.group(2)) and any(
                canonical in strings(v) for v in seen.get(to_uri(m.group(1).split(" 的 ")[-1])) or []):
            return canonical
        return version
    if isinstance(version, dict):
        return {k: restore(v, canonical.get(k) if isinstance(canonical, dict) else None, seen) for k, v in version.items()}
    if isinstance(version, list):
        return [restore(v, canonical[i] if isinstance(canonical, list) and i < len(canonical) else None, seen)
                for i, v in enumerate(version)]
    return version


def merge(into, more):
    for key, versions in more.items():
        bucket = into.setdefault(key, [])
        bucket += [v for v in versions if v not in bucket]
    return into


def verdicts(calls):
    """submit 的 tool_call_id → ('accepted', set()) 或 ('rejected', {(ref, quote): why})。"""
    out = {}
    for messages in calls:
        for m in messages:
            if m["role"] != "tool" or m["tool_call_id"] in out:
                continue
            text = m.get("content") or ""
            if text.strip() == '{"accepted": true}':
                out[m["tool_call_id"]] = ("accepted", {})
            elif "被拒" in text:
                try:
                    reason = json.loads(text).get("reason", text)
                except ValueError:
                    reason = text
                named = {}
                for raw in re.findall(r'\{[^{}]*"why"[^{}]*\}', reason):
                    try:
                        item = json.loads(raw)
                    except ValueError:
                        continue
                    named[(item.get("ref"), item.get("quote"))] = item.get("why")
                out[m["tool_call_id"]] = ("rejected", named)
    return out


def old_result(verdict, ref, quote):
    if verdict is None:
        return "unknown"
    state, named = verdict
    if state == "accepted":
        return "pass"
    why = named.get((ref, quote))
    return f"reject:{why}" if why else "pass(所在提交因别的原因被拒)"


def new_result(r):
    """通过的按命中分三档：一处 / 同一字段里多处 / 跨字段多处（一条引用够不够要使用方判）。"""
    roles = [role_label(x) for x in r.roles]
    nodes = [x.node for x in r.regions]
    fields = sorted({"/".join(n.split("/")[:3]) for n in nodes})
    if not r.ok:
        verdict = r.reason
    elif len(nodes) == 1:
        verdict = "过：一处"
    elif len(fields) == 1:
        verdict = "过：同一字段多处"
    else:
        verdict = "过：跨字段多处（需使用方判）"
    return {"ok": r.ok, "reason": r.reason, "verdict": verdict, "roles": roles, "nodes": nodes, "fields": fields,
            "seen_only": any(x.seen_only for x in r.regions), "hint": r.hint}


def main(data, out_path):
    runs, events = load(data)
    rows = []
    for event in events:
        run = runs[event["case_id"]]
        run_id = event["run"]["eval_axes"]["run_id"]
        table, scopes = table_of(run), strict_scopes(event)
        folder = f"{data}/calls/{run_id}"
        files = sorted(os.listdir(folder))
        records = [json.load(open(f"{folder}/{f}")) for f in files]
        decided = verdicts([r["messages"] for r in records])
        later = {}  # 每个任务最后一次 submit 的请求序号：之后没再交同一任务的，按 loop 已收下推断
        for index, record in enumerate(records):
            reply = [m for m in record["response"].get("run_messages", []) if m.get("role") == "assistant"][-1]
            for t in reply.get("tool_calls") or []:
                if t["function"]["name"] == "submit":
                    later[json.loads(t["function"]["arguments"]).get("task_id")] = index
        loop_seen = {}  # 同一个 loop 此前看到过的（被归档的也算看到过）
        for index, record in enumerate(records):
            stage = (record["response"].get("runtime") or {}).get("stage")
            here = merge(loop_seen.setdefault(stage, {}), seen_in(record["messages"]))
            reply = [m for m in record["response"].get("run_messages", []) if m.get("role") == "assistant"][-1]
            submits = [t for t in reply.get("tool_calls") or [] if t["function"]["name"] == "submit"]
            if not submits:
                continue
            seen = {k: [restore(v, table.get(k).body if table.get(k) else None, here) for v in vs] for k, vs in here.items()}
            for call in submits:
                args = json.loads(call["function"]["arguments"])
                task = args.get("task_id")
                if task not in PROCESS:
                    continue
                payload = args.get("payload") or {}
                for part in ("actual", "unexpected"):
                    for item in payload.get(part) or []:
                        for q in item.get("quotes") or []:
                            ref, quote = str(q.get("ref") or ""), str(q.get("quote") or "")
                            rows.append({
                                "case": event["case_id"], "run": run_id, "request": index, "task": task,
                                "row": item.get("id"), "part": part, "ref": ref, "quote": quote,
                                "old": old_result(decided.get(call["id"]) or (("accepted", {}) if later.get(task) == index else None), ref, quote),
                                "strict": new_result(cite(table, to_uri(ref), quote, seen=seen, scope=scopes.get(task, set()), view=task)),
                                "loose": new_result(cite(table, to_uri(ref), quote, seen=seen, scope=None, view=task)),
                                "mounted": len(table)})
    json.dump(rows, open(out_path, "w"), ensure_ascii=False, indent=1)
    summary(rows)


def summary(rows):
    print("引用总数", len(rows), "现规则：", dict(Counter(r["old"].split(":")[0] for r in rows)))
    for mode in ("strict", "loose"):
        print(f"\n== 新规则（{mode}）× 现规则")
        cross = Counter((r["old"] if r["old"].startswith("reject") else r["old"].split("(")[0], r[mode]["verdict"]) for r in rows)
        for (old, new), n in sorted(cross.items(), key=lambda x: (x[0][0], -x[1])):
            print(f"  {n:4d}  现={old:28s} 新={new}")
        ok = [r[mode] for r in rows if r[mode]["ok"]]
        print("  通过（一处）的角色：", dict(Counter(x["roles"][0] for x in ok if x["verdict"] == "过：一处")))
        print("  通过但区间只在看到的那份上（seen_only）：一处", sum(1 for x in ok if x["seen_only"] and x["verdict"] == "过：一处"),
              "，多处", sum(1 for x in ok if x["seen_only"] and x["verdict"] != "过：一处"))
        multi = [x for x in ok if x["verdict"] != "过：一处"]
        print("  跨字段多处：按角色组合", dict(Counter("+".join(x["roles"]) for x in multi if x["verdict"].startswith("过：跨")).most_common(8)))
        print("  多处：按字段组合", dict(Counter("+".join(x["fields"]) for x in multi).most_common(8)))


if __name__ == "__main__":
    main(*sys.argv[1:3])
