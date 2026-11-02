"""过程六轴在 axis loop 里的程序部分（spec/alg/axis_loop.md §12.2，判法 spec/alg/process-axes.md）。

侦探、6 个本应、6 个实际的 checks.py / synth.py 都调这里：判法与 llm_probe 现方案同一份（逐段搬自
eval_axes/adapters/trace_analysis.py、process_common.py、process_expected.py），只换了接入方式——
不分批（材料大用目录 + read_material 按需读），跨批 same_as 取消，引文核对被拒就打回重交。
全部确定性、不调模型、不读写外部状态；输入只有校验 / 合成视图里声明过的材料。
"""
from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from typing import Any

from impl.projects.llm_probe_loop.business_trace.dossier import expand_content
from impl.projects.llm_probe_loop.business_trace.links import AXIS_LINK_TYPES, LINK_TYPES, TYPE_AXES
from impl.projects.llm_probe_loop.business_trace.materials import material_view, model_material

PROCESS_AXES = ("intent_understanding", "planning_routing", "tool_execution",
                "context_memory", "knowledge_data", "model_capability")
UNCLASSIFIED = "unclassified"
MET, NOT_MET, UNCHECKABLE, NOT_APPLICABLE = "达到", "没达到", "无法核", "不适用"
QUOTED = (MET, NOT_MET, NOT_APPLICABLE)  # 必须引原文的取值；只有无法核可以不引
UPSTREAM, UNRESOLVED = "上游:", "未定位:"
TRACE = "case.trace"
ANALYSIS = "result.trace_analysis"

# ---- 侦探：合并可疑环节、按轴整理材料 --------------------------------------------------------

def merge_suspects(program: list[dict[str, Any]], existing: list[dict[str, Any]], discovered: list[dict[str, Any]],
                   links: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """程序发现与两类模型发现物化为下游环节记录（同现方案 trace_analysis.merge_suspects）。
    给哪些轴：环节类型对应的轴，加侦探点名可能用得上的轴（偏召回，一条记录常是几个环节的证据）。"""
    merged: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []

    def seed(link_id: str, origin: str, why: str, source_refs: list[str], axes: list[str]) -> None:
        link = links[link_id]
        entry = {"link_id": link_id, "link_type": link["link_type"], "origin": [origin], "why": [why],
                 "source_refs": list(source_refs), "input_refs": [e["ref"] for e in link["input"]],
                 "output_refs": [e["ref"] for e in link["output"]], "off_map": False, "named": list(axes)}
        merged[link_id] = entry
        out.append(entry)

    for item in program:
        seed(item["link_id"], "program", item["why"], [], [])
    for item in existing:
        entry = merged.get(item["link_id"])
        if entry is None:
            seed(item["link_id"], "analysis", item["why"], item["source_refs"], item["axes"])
            continue
        entry["named"] += item["axes"]
        if "analysis" not in entry["origin"]:
            entry["origin"].append("analysis")
        entry["why"].append(item["why"])
        entry["source_refs"] = list(dict.fromkeys(entry["source_refs"] + item["source_refs"]))
    for item in discovered:
        out.append({"link_id": f"new:{len(out)}", "link_type": item["link_type"], "origin": ["analysis"],
                    "why": [item["why"]], "source_refs": list(item["source_refs"]),
                    "input_refs": list(item["input_refs"]), "output_refs": list(item["output_refs"]), "off_map": True,
                    "named": list(item["axes"])})
    for entry in out:
        own = PROCESS_AXES if entry["link_type"] == UNCLASSIFIED else TYPE_AXES[entry["link_type"]]
        named = set(entry.pop("named"))
        entry["axes"] = [a for a in PROCESS_AXES if a in own or a in named]
    return out


def axis_links(axis: str, links: list[Mapping[str, Any]], suspects: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """程序环节 + 侦探补出的本轴表外环节（同现方案 process_common._axis_links）。"""
    types = AXIS_LINK_TYPES[axis]
    out = [dict(link) for link in links if link["link_type"] in types]
    for item in suspects:
        if item.get("off_map") and axis in item["axes"]:
            out.append({"link_id": item["link_id"], "link_type": item["link_type"], "turn": "",
                        "input": [{"ref": ref, "field": ""} for ref in item["input_refs"]],
                        "output": [{"ref": ref, "field": ""} for ref in item["output_refs"]],
                        # 侦探的怀疑理由只给页面，不进任何轴的材料（只指路，不带看法）
                        "facts": {}, "basis": "侦探补出的表外环节"})
    return out


def input_view(dossier: Mapping[str, Any], links: list[Mapping[str, Any]]) -> dict[str, Any]:
    """本应只看的材料：本轴环节的记录，摘掉每条 link 声明的输出端字段（同现方案 process_expected.input_view）。"""
    drop = {(end["ref"], end.get("field", "")) for link in links for end in link.get("output") or []}
    keep = {(end["ref"], end.get("field", "")) for link in links for end in link.get("input") or []}
    view = copy.deepcopy(material_view(dossier, links, []))
    # 端点不写字段（侦探补的表外环节）指整条记录：输出端整条摘掉，除非它也是本轴的输入端
    hit = lambda ends, rid, name: (rid, name) in ends or (rid, "") in ends
    emptied = set()
    for rec in view.get("records") or []:
        fields = rec.get("fields") or {}
        gone = [n for n in fields if hit(drop, rec.get("id"), n) and not hit(keep, rec.get("id"), n)]
        for name in gone:
            fields.pop(name)
        if gone and not fields:
            emptied.add(rec.get("id"))
    view["records"] = [r for r in view.get("records") or [] if r.get("id") not in emptied]
    view["missing_endpoints"] = [m for m in view.get("missing_endpoints", []) if m.get("side") != "output"]
    view["reading_guide"] = "本应阶段只给输入端：记录里只有本轴读到的输入字段，输出端（返回、报错、模型产出、交付）没有给。"
    # 只留输入端记录里还引用到的共享正文与独立正文（输出端的正文不带过来）
    used = _tokens(view["records"])
    view["contents"] = {k: v for k, v in (view.get("contents") or {}).items() if k in used or not _is_output_only(k, links)}
    return model_material(view)


def _tokens(value: Any) -> set[str]:
    return set(re.findall(r"(?:shared|content)#\d+", json.dumps(value, ensure_ascii=False)))


def _is_output_only(ref: str, links: list[Mapping[str, Any]]) -> bool:
    ins = {e["ref"] for link in links for e in link.get("input") or []}
    outs = {e["ref"] for link in links for e in link.get("output") or []}
    return ref in outs and ref not in ins


def _unshare(value: Any, shared: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"shared_ref"}:
            return _unshare(shared.get(value["shared_ref"]), shared)
        return {k: _unshare(v, shared) for k, v in value.items()}
    if isinstance(value, list):
        return [_unshare(v, shared) for v in value]
    return value


def to_store(view: Mapping[str, Any]) -> dict[str, Any]:
    """材料视图 → 记录库（目录 + 按编号读的记录，共享正文还原进记录），给 read_material 用。"""
    shared = view.get("shared_contents") or {}
    records = []
    for rec in view.get("records") or []:
        records.append({**{k: v for k, v in rec.items() if k != "fields"},
                        "fields": {name: _unshare(info, shared) for name, info in (rec.get("fields") or {}).items()}})
    for ref, value in (view.get("contents") or {}).items():
        records.append({"id": ref, "kind": "content", "fields": {"value": {"status": "available", "value": _unshare(value, shared)}}})
    catalog = [{"id": r["id"], "kind": r.get("kind"), "turn": r.get("turn"), "fields": sorted(r["fields"]),
                "chars": len(json.dumps(r["fields"], ensure_ascii=False))} for r in records]
    meta = {k: view[k] for k in ("missing_endpoints", "input_limitations", "reading_guide") if k in view}
    return {"catalog": catalog, "records": records, **meta}


def analysis_result(trace: Mapping[str, Any], own: Mapping[str, Any]) -> dict[str, Any]:
    """侦探的程序填字段：合并后的可疑环节、全部环节（含表外）、每轴的 input / full 两份材料与指的记录。"""
    dossier, table = trace["dossier"], trace["links"]
    by_id = {link["link_id"]: link for link in table}
    suspects = merge_suspects(trace["program_suspects"], own["existing_link_suspects"], own["new_link_suspects"], by_id)
    views = []
    for axis in PROCESS_AXES:
        links = axis_links(axis, table, suspects)
        mine = [s for s in suspects if axis in s["axes"]]
        # 侦探给本轴某环节指的记录写进那个环节：核它时也要看（内容可能不在它自己的端点上）
        pointed: dict[str, set[str]] = {}
        for s in mine:
            pointed.setdefault(s["link_id"], set()).update(s["source_refs"])
        for link in links:
            if pointed.get(link["link_id"]):
                link["leads"] = sorted(pointed[link["link_id"]])
        # 侦探点名给本轴、但挂在别轴环节上的记录：本轴环节不带它，要单独放进实际材料
        own_ids = {link["link_id"] for link in links}
        borrowed = sorted({ref for s in mine if s["link_id"] not in own_ids for ref in s["source_refs"]})
        views.append({"axis": axis, "links": links, "leads": borrowed,
                      "input": to_store(input_view(dossier, links)),
                      "full": to_store(model_material(material_view(dossier, links, mine, extra_refs=borrowed)))})
    failed = [c for c in trace["coverage"] if c.get("status") not in ("succeeded",)]
    return {"verdict": "partial" if failed else "complete",
            "reason": f"{len(table)} 个程序环节、{sum(s['off_map'] for s in suspects)} 个表外环节、可疑 {len(suspects)} 个",
            "suspects": suspects, "views": views, "feeds": feeds(views)}


def feeds(views: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    """from 轴的输出端出现在 to 轴的本应材料里：写 to 的本应时会看到 from 的实际产出，本应分发据此排先后（axis_loop §12.2.2）。"""
    outs = {v["axis"]: {(e["ref"], e.get("field", "")) for link in v["links"] for e in link.get("output") or []} for v in views}
    out = []
    for to in views:
        seen = {(rec["id"], name) for rec in to["input"]["records"] for name in rec.get("fields") or {}}
        for frm in views:
            if frm is not to and any((ref, field) in seen or (not field and any(r == ref for r, _ in seen))
                                     for ref, field in outs[frm["axis"]]):
                out.append({"from": frm["axis"], "to": to["axis"]})
    return out


def check_analysis(trace: Mapping[str, Any], own: Mapping[str, Any], read_ids: set[str]) -> list[str]:
    """侦探交的：link_id 在环节表里；新环节类型合法、至少一端有已知记录；source_refs 不空且都读过。"""
    problems = []
    links = {link["link_id"] for link in trace["links"]}
    known = {r["id"] for r in trace["records"]}
    for item in own["existing_link_suspects"]:
        if item["link_id"] not in links:
            problems.append(f"existing_link_suspects：{item['link_id']} 不在环节表里")
    for item in own["new_link_suspects"]:
        if item["link_type"] not in (*LINK_TYPES, UNCLASSIFIED):
            problems.append(f"new_link_suspects：link_type {item['link_type']} 不是六类之一或 unclassified")
        ends = item["input_refs"] + item["output_refs"]
        if not ends or any(ref not in known for ref in ends):
            problems.append(f"new_link_suspects：至少一端要有记录，且编号都在案卷里：{ends}")
    for name in ("existing_link_suspects", "new_link_suspects"):
        for item in own[name]:
            unread = [ref for ref in item["source_refs"] if ref not in read_ids]
            if not item["source_refs"] or unread:
                problems.append(f"{name}：source_refs 不能空，且必须是此前用 read_material 读回过的编号（没读过：{unread}）")
    return problems


def process_rows(materials: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """兑现读的过程六轴逐条结果：{<轴>.<条目id>: 条目}；没开过程轴为空（spec/alg/fulfilled.md §2.1）。"""
    rows = {}
    for axis in PROCESS_AXES:
        for row in (materials.get(f"result.{axis}") or {}).get("results") or []:
            rows[f"{axis}.{row['id']}"] = row
    return rows


# ---- 本应 -----------------------------------------------------------------------------------

def link_turns(links: list[Mapping[str, Any]]) -> set[str]:
    found = {f"t{n}" for link in links for n in re.findall(r"turn(\d+)", json.dumps(link, ensure_ascii=False))}
    return found or {"t1"}


def check_expected(own: Mapping[str, Any], links: list[Mapping[str, Any]], expectation_ids: set[str]) -> list[str]:
    problems = []
    ids = [item["id"] for item in own["expected"]]
    if len(set(ids)) != len(ids):
        problems.append(f"本应清单的 id 不能重复：{ids}")
    turns = link_turns(links)
    stray = [item["id"] for item in own["expected"] if item["turn"] not in turns]
    if stray:
        problems.append(f"这些条目的 turn 不是本轴环节所在的轮 {sorted(turns)}：{stray}")
    unknown = [(item["id"], e) for item in own["expected"] for e in item["expectations"] if e not in expectation_ids]
    if unknown:
        problems.append(f"expectations 里的编号不在需求清单里：{unknown}")
    return problems


# ---- 实际（同现方案 process_expected：check_actual / settle / aggregate / issues_of） ------------

_QUOTE_MARKS = str.maketrans({"“": '"', "”": '"'})


def _squash(text: Any) -> str:
    return "".join(str(text).split()).translate(_QUOTE_MARKS)


def _leaves(value: Any):
    if isinstance(value, str):
        yield value
        try:
            parsed = json.loads(value)
        except ValueError:
            return
        if not isinstance(parsed, str):
            yield from _leaves(parsed)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)


def record_texts(store: Mapping[str, Any]) -> dict[str, list[str]]:
    """记录编号 → 该记录全部正文叶子（去空白），供逐字核对。"""
    return {r["id"]: [_squash(t) for t in _leaves(expand_content(r["fields"], {}))] for r in store["records"]}


def bad_quotes(row: Mapping[str, Any], texts: Mapping[str, list[str]]) -> list[dict[str, Any]]:
    out = []
    for q in row.get("quotes") or []:
        ref, quote = q.get("ref"), _squash(q.get("quote") or "")
        if ref not in texts:
            out.append({"row": row.get("id"), "ref": ref, "quote": q.get("quote"), "why": "记录编号不在材料里"})
        elif not quote or not any(quote in t for t in texts[ref]):
            out.append({"row": row.get("id"), "ref": ref, "quote": q.get("quote"), "why": "所引记录里找不到这段原文"})
    return out


def check_actual(own: Mapping[str, Any], expected: Mapping[str, Any], texts: Mapping[str, list[str]]) -> list[str]:
    problems: list[str] = []
    ids = [item["id"] for item in expected["expected"]]
    got = [row["id"] for row in own["actual"]]
    if sorted(got) != sorted(ids) or len(set(got)) != len(got):
        problems.append(f"actual 的 id 必须与本应清单一一对应：本应 {ids}，实际 {got}")
    failed = {row["id"] for row in own["actual"] if row["verdict"] == NOT_MET}
    unexpected = {row["id"] for row in own["unexpected"]}
    cited: set[str] = set()
    for problem in own["problems"]:
        stray = [i for i in problem["items"] if i not in failed and i not in unexpected]
        if stray:
            problems.append(f"问题「{problem['phenomenon'][:40]}」引用了不是没达到、也不是 unexpected 的 id：{stray}")
        cited |= set(problem["items"])
    orphan = sorted((failed | unexpected) - cited)
    if orphan:
        problems.append(f"这些没达到的条目或 unexpected 没有被任何 problem 引用：{orphan}")
    items = {item["id"]: item for item in expected["expected"]}
    for row in own["actual"]:
        # 必须独立查证：trace 证明不了"没做是错的"（spec/alg/process-axes.md §3.2；提交时打回，不由合成改判）
        if row["verdict"] == NOT_MET and items.get(row["id"], {}).get("needs_external") == "是":
            problems.append(f"{row['id']} 必须独立查证（needs_external=是）：trace 证明不了没做是错的，不能判没达到；"
                            "trace 里看得到做到了就判达到并引原文，看不出就判无法核")
        if row["verdict"] in QUOTED and not row.get("quotes"):
            problems.append(f"{row['id']} 判{row['verdict']}但没有引文" + ("（要引原文说明实际走的是哪条路）" if row["verdict"] == NOT_APPLICABLE else "（引不出原文就判无法核）"))
        problems += [json.dumps(b, ensure_ascii=False) for b in bad_quotes(row, texts)]
    for row in own["unexpected"]:
        if not row.get("quotes"):
            problems.append(f"unexpected {row['id']} 没有引文")
        problems += [json.dumps(b, ensure_ascii=False) for b in bad_quotes(row, texts)]
    return problems


def _kind(attribution: str) -> str:
    if attribution.startswith(UPSTREAM):
        return "upstream"
    if attribution.startswith(UNRESOLVED):
        return "unresolved"
    return "local"


def actual_result(axis: str, own: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    """程序填：轴级五值与组成、问题记录（同现方案 aggregate + issues_of）。模型交的逐条判断原样照搬：
    不能成立的（坏引文、必须独立查证却判没达到）已在 check_actual 打回（demand/axis_loop.md §3.3.7）。"""
    items = {item["id"]: item for item in expected["expected"]}
    rows = [dict(row) for row in own["actual"]]
    # 不适用：这一步这次没发生、也不需要（换了路办成）——移出逐条结果，不计入轴级与兑现（spec/alg/process-axes.md §3.2）
    skipped = [r for r in rows if r["verdict"] == NOT_APPLICABLE]
    rows = [r for r in rows if r["verdict"] != NOT_APPLICABLE]
    live = {r["id"] for r in rows if r["verdict"] == NOT_MET} | {r["id"] for r in own["unexpected"]}
    problems = [{**p, "items": [i for i in p["items"] if i in live]} for p in own["problems"]]
    problems = [p for p in problems if p["items"]]
    for k, p in enumerate(problems, 1):
        p["problem_id"] = f"{axis}-P{k}"
    verdicts = [r["verdict"] for r in rows]
    kinds = [_kind(p["attribution"]) for p in problems]
    counts = {MET: verdicts.count(MET), NOT_MET: verdicts.count(NOT_MET), UNCHECKABLE: verdicts.count(UNCHECKABLE),
              "意外": len(own["unexpected"]), "问题·本轴": kinds.count("local"), "问题·上游": kinds.count("upstream"),
              "问题·未定位": kinds.count("unresolved"), "未覆盖": len(expected.get("not_covered") or []),
              "不适用": len(skipped)}
    if "local" in kinds:
        verdict = "problematic"
    elif counts[UNCHECKABLE] or "unresolved" in kinds:
        verdict = "not_evaluable"
    elif counts[MET]:
        verdict = "sound"
    elif "upstream" in kinds:
        verdict = "untested"
    else:
        verdict = "not_applicable"
    rows_by_id = {r["id"]: r for r in rows}
    unexpected = {u["id"]: u for u in own["unexpected"]}
    issues = []
    for p in problems:
        found = [rows_by_id.get(i) or unexpected[i] for i in p["items"]]
        from_expected = [items[i] for i in p["items"] if i in items]
        quotes = [q for row in found for q in row.get("quotes") or []]
        issues.append({"problem_id": p["problem_id"], "phenomenon": p["phenomenon"],
                       "expected": "；".join(f"{e['statement']}（依据：{e['basis']}）" for e in from_expected)
                                   or "；".join("本应清单未覆盖：" + unexpected[i]["why"] for i in p["items"] if i in unexpected),
                       "observed": "；".join(row["observed"] for row in found),
                       "attribution": _kind(p["attribution"]), "attribution_detail": p["attribution"], "impact": p["impact"],
                       "origin": "expected" if from_expected else "unexpected",
                       "subcapability": sorted({e["subcapability"] for e in from_expected}),
                       "links": sorted({l for row in found for l in row.get("links") or []}),
                       "quotes": quotes, "output_refs": sorted({q["ref"] for q in quotes})})
    results = [{**items[r["id"]], **{k: v for k, v in r.items() if k != "id"}, "id": r["id"]} for r in rows]
    return {"verdict": verdict, "composition": {"counts": counts,
                                                "not_covered": list(expected.get("not_covered") or []),
                                                "not_applicable": [{**items[r["id"]], **{k: v for k, v in r.items() if k != "id"}, "id": r["id"]}
                                                                   for r in skipped]},
            "results": results, "issues": issues}
