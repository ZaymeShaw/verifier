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

def _clean_refs(items: list[str]) -> list[str]:
    return [str(r or "").strip().removeprefix("trace://") for r in items]


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
        srefs = _clean_refs(item["source_refs"])
        entry = merged.get(item["link_id"])
        if entry is None:
            seed(item["link_id"], "analysis", item["why"], srefs, item["axes"])
            continue
        entry["named"] += item["axes"]
        if "analysis" not in entry["origin"]:
            entry["origin"].append("analysis")
        entry["why"].append(item["why"])
        entry["source_refs"] = list(dict.fromkeys(entry["source_refs"] + srefs))
    for item in discovered:
        out.append({"link_id": f"new:{len(out)}", "link_type": item["link_type"], "origin": ["analysis"],
                    "why": [item["why"]], "source_refs": _clean_refs(item["source_refs"]),
                    "input_refs": _clean_refs(item["input_refs"]), "output_refs": _clean_refs(item["output_refs"]), "off_map": True,
                    "named": list(item["axes"])})
    for entry in out:
        own = type_axes(entry["link_type"])
        named = set(entry.pop("named"))
        entry["axes"] = [a for a in PROCESS_AXES if a in own or a in named]
    return out


def type_axes(link_type: str) -> tuple[str, ...]:
    """环节类型对应的轴；归不了类的属于每个轴。"""
    return PROCESS_AXES if link_type == UNCLASSIFIED else TYPE_AXES[link_type]


def axis_links(axis: str, links: list[Mapping[str, Any]], suspects: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """本轴的环节：程序环节与侦探补出的表外环节同一规则，按环节类型归轴（demand/process_axes.md §1.1：
    一个事件属于几类部件就是几条环节）。侦探点名的 axes 是"用得上"，只决定判定材料，不让环节进别的轴。"""
    out = [dict(link) for link in links if link["link_type"] in AXIS_LINK_TYPES[axis]]
    for item in suspects:
        if item.get("off_map") and axis in type_axes(item["link_type"]):
            out.append({"link_id": item["link_id"], "link_type": item["link_type"], "turn": "",
                        "input": [{"ref": rec, "field": field} for r in item["input_refs"] for rec, field in (_uri_pair(r),)],
                        "output": [{"ref": rec, "field": field} for r in item["output_refs"] for rec, field in (_uri_pair(r),)],
                        # 侦探的怀疑理由只给页面，不进任何轴的材料（只指路，不带看法）
                        "facts": {}, "basis": "侦探补出的表外环节"})
    return out


def _expand_ends(
    rows: Mapping[str, Mapping[str, Any]], ends: list[Mapping[str, Any]], *, aliases: bool = True
) -> set[tuple[str, str]]:
    """端点展开到 (rid, field)：不写字段展开成该记录全部字段；aliases=True 时同记录同一底层 ref 的别名字段（如 result 与 output）一并算上。"""
    out: set[tuple[str, str]] = set()
    for end in ends:
        rid, field = end["ref"], end.get("field", "")
        row_fields = (rows.get(rid) or {}).get("fields") or {}
        if not field:
            out.add((rid, ""))
            out.update((rid, name) for name in row_fields)
            continue
        out.add((rid, field))
        src = (row_fields.get(field) or {}).get("ref") if aliases else None
        if src:
            out.update((rid, name) for name, info in row_fields.items() if info.get("ref") == src)
    return out


def input_view(dossier: Mapping[str, Any], links: list[Mapping[str, Any]]) -> dict[str, Any]:
    """本应只看的材料：除静态定义（definitions）外，只保留本轴环节显式声明在输入端的字段；空记录整条删掉。"""
    rows = {r["id"]: r for r in dossier.get("records") or []}
    keep = _expand_ends(rows, [end for link in links for end in link.get("input") or []], aliases=False)
    view = copy.deepcopy(material_view(dossier, links, []))
    kept_records = []
    for rec in view.get("records") or []:
        rid = rec.get("id")
        if rec.get("kind") == "definitions":
            kept_records.append(rec)
            continue
        fields = rec.get("fields") or {}
        if not fields:
            if (rid, "") in keep:
                kept_records.append(rec)
            continue
        gone = [n for n in fields if (rid, n) not in keep]
        if gone:
            gone_set = set(gone)
            for name, info in list(fields.items()):
                target = info.get("same_as") if isinstance(info, Mapping) else None
                if name not in gone_set and target in gone_set and target in fields:
                    fields[name] = dict(fields[target])
            for name in gone:
                fields.pop(name)
        if fields:
            kept_records.append(rec)
    view["records"] = kept_records
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


def _input_uris(dossier: Mapping[str, Any], view: Mapping[str, Any]) -> list[str]:
    """本应阶段开放的 MCP 资源 URI：按 input_view 保留下来的记录与字段拼模板 URI（防污染）。"""
    rows = {r["id"]: r for r in dossier.get("records") or []}
    sources = {s["id"] for s in dossier.get("sources") or []}
    uris: list[str] = []
    for rec in view.get("records") or []:
        rid = rec["id"]
        raw_fields = (rows.get(rid) or {}).get("fields") or {}
        fnames = [f for f in sorted(rec.get("fields") or {}) if f in raw_fields]
        if fnames:
            uris.extend(f"trace://{rid}/fields/{f}" for f in fnames)
        elif rid in rows and not raw_fields:
            uris.append(f"trace://{rid}")
    for ref in sorted(view.get("contents") or {}):
        if ref in sources:
            uris.append(f"trace://{ref}")
    return list(dict.fromkeys(uris))


def _full_uris(dossier: Mapping[str, Any], view: Mapping[str, Any]) -> list[str]:
    """实际阶段开放的 MCP 资源 URI：按 material_view 选中的字段出模板 URI，全字段或无字段记录出整块 URI（不带无关重字段）。"""
    rows = {r["id"]: r for r in dossier.get("records") or []}
    sources = {s["id"] for s in dossier.get("sources") or []}
    uris: list[str] = []
    for rec in view.get("records") or []:
        rid = rec["id"]
        row = rows.get(rid)
        if row is None:
            continue
        raw_fields = row.get("fields") or {}
        fnames = [f for f in sorted(rec.get("fields") or {}) if f in raw_fields]
        if not raw_fields or set(fnames) == set(raw_fields):
            uris.append(f"trace://{rid}")
        elif fnames:
            uris.extend(f"trace://{rid}/fields/{f}" for f in fnames)
    for ref in sorted(view.get("contents") or {}):
        if ref in sources:
            uris.append(f"trace://{ref}")
    return list(dict.fromkeys(uris))


def _view_meta(view: Mapping[str, Any], *, keep_guide: bool = False) -> dict[str, Any]:
    keys = ("missing_endpoints", "input_limitations", *(["reading_guide"] if keep_guide else []))
    return {k: view[k] for k in keys if view.get(k)}


def analysis_result(trace: Mapping[str, Any], own: Mapping[str, Any]) -> dict[str, Any]:
    """侦探的程序填字段：合并可疑环节、全部环节（含表外）、每轴的 input_uris / full_uris 与缺口元信息（不拷正文副本）。"""
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
        # 侦探点名给本轴、但挂在别轴环节上的记录：本轴环节不带它，单独记进 leads 并加入实际资源
        own_ids = {link["link_id"] for link in links}
        borrowed = sorted({ref for s in mine if s["link_id"] not in own_ids for ref in s["source_refs"]})
        in_v = input_view(dossier, links)
        full_v = model_material(material_view(dossier, links, mine, extra_refs=borrowed))
        views.append({
            "axis": axis, "links": links, "leads": borrowed,
            "input_uris": _input_uris(dossier, in_v),
            "full_uris": _full_uris(dossier, full_v),
            "input_meta": _view_meta(in_v, keep_guide=True),
            "full_meta": _view_meta(full_v, keep_guide=False),
        })
    failed = [c for c in trace["coverage"] if c.get("status") not in ("succeeded",)]
    return {"verdict": "partial" if failed else "complete",
            "reason": f"{len(table)} 个程序环节、{sum(s['off_map'] for s in suspects)} 个表外环节、可疑 {len(suspects)} 个",
            "suspects": suspects, "views": views, "feeds": feeds(views)}


def _uri_pair(uri: str) -> tuple[str, str]:
    raw = str(uri or "").strip().removeprefix("trace://")
    rec, sep, field = raw.rpartition("/fields/")
    return (rec, field) if sep and field else (raw, "")


def feeds(views: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    """from 轴的输出端出现在 to 轴的本应资源里：写 to 的本应时会看到 from 的实际产出，本应分发据此排先后（axis_loop §12.2.2）。"""
    outs = {v["axis"]: {(e["ref"], e.get("field", "")) for link in v["links"] for e in link.get("output") or []} for v in views}
    out = []
    for to in views:
        seen = {_uri_pair(u) for u in to.get("input_uris") or []}
        for frm in views:
            if frm is not to and any(
                (ref, field) in seen or (ref, "") in seen or (not field and any(r == ref for r, _ in seen))
                for ref, field in outs[frm["axis"]]
            ):
                out.append({"from": frm["axis"], "to": to["axis"]})
    return out


def check_analysis(trace: Mapping[str, Any], own: Mapping[str, Any], read_targets: set[tuple[str, str]]) -> list[str]:
    """侦探交的：link_id 在环节表里；新环节类型合法、至少一端有合法且已读的位置、两端不重叠；source_refs 不空、地址存在且都读过。"""
    problems: list[str] = []
    links = {link["link_id"] for link in trace["links"]}
    dossier = trace.get("dossier") or {}
    rows_by_id: dict[str, Mapping[str, Any]] = {
        r["id"]: r for r in (dossier.get("records") or trace.get("records") or [])
    }
    for s in dossier.get("sources") or []:
        rows_by_id.setdefault(s["id"], {"id": s["id"], "fields": {"request_and_response": {}}})
    rec_fields: dict[str, set[str]] = {rid: set((r.get("fields") or {}).keys()) for rid, r in rows_by_id.items()}

    def check_refs(label: str, refs: list[str], *, allow_empty: bool = False) -> None:
        if not refs:
            if not allow_empty:
                problems.append(f"{label} 不能为空")
            return
        bad_addr: list[str] = []
        unread: list[str] = []
        for raw in refs:
            rec, field = _uri_pair(raw)
            if not rec or rec not in rec_fields:
                bad_addr.append(f"{raw!r}（记录不存在；写记录编号，或 记录编号/fields/字段名）")
                continue
            if field and field not in rec_fields[rec]:
                bad_addr.append(
                    f"{raw!r}（记录 {rec} 的 fields 只有 {sorted(rec_fields[rec])}；"
                    f"指步骤本身属性如 name/kind/outcome 时写记录编号 {rec!r}）"
                )
                continue
            seen = ((rec, "") in read_targets or (bool(field) and (rec, field) in read_targets))
            if not seen:
                unread.append(raw)
        if bad_addr:
            problems.append(f"{label} 地址不合法：{'；'.join(bad_addr)}")
        if unread:
            problems.append(f"{label} 必须是已内联给出或此前用 read_material 读回过的位置（没读过：{unread}）")

    for item in own["existing_link_suspects"]:
        if item["link_id"] not in links:
            problems.append(f"existing_link_suspects：{item['link_id']} 不在环节表里")
        check_refs(f"existing_link_suspects({item['link_id']}).source_refs", item["source_refs"])
    for idx, item in enumerate(own["new_link_suspects"]):
        tag = f"new_link_suspects[{idx}]"
        if item["link_type"] not in (*LINK_TYPES, UNCLASSIFIED):
            problems.append(f"{tag}：link_type {item['link_type']} 不是六类之一或 unclassified")
        ends = list(item["input_refs"]) + list(item["output_refs"])
        if not ends:
            problems.append(f"{tag}：input_refs 与 output_refs 至少一端不能为空")
        else:
            check_refs(f"{tag}.input_refs", item["input_refs"], allow_empty=True)
            check_refs(f"{tag}.output_refs", item["output_refs"], allow_empty=True)
            in_ends = _expand_ends(
                rows_by_id, [{"ref": r, "field": f} for x in _clean_refs(item["input_refs"]) for r, f in (_uri_pair(x),)]
            )
            both = sorted(dict.fromkeys(
                raw for raw in _clean_refs(item["output_refs"])
                if _expand_ends(rows_by_id, [{"ref": _uri_pair(raw)[0], "field": _uri_pair(raw)[1]}]) & in_ends
            ))
            if both:
                problems.append(f"{tag}：同一个位置不能既是输入端又是输出端：{both}")
        check_refs(f"{tag}.source_refs", item["source_refs"])
    return problems


def process_trace(materials: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """兑现读的过程六轴逐条结果与意外问题：({<轴>.<id>: 条目}, {<轴>.<unexpected_id>: issue})；没开过程轴为空（spec/alg/fulfilled.md §2.1）。"""
    rows: dict[str, dict[str, Any]] = {}
    unexpected: dict[str, dict[str, Any]] = {}
    for axis in PROCESS_AXES:
        axis_out = materials.get(f"result.{axis}") or {}
        for row in axis_out.get("results") or []:
            rows[f"{axis}.{row['id']}"] = row
        for issue in axis_out.get("issues") or []:
            if issue.get("origin") == "unexpected":
                unexpected[f"{axis}.{issue['item_id']}"] = issue
    return rows, unexpected


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


# ---- 实际（spec/alg/process-axes.md §3.2–§5：逐条归因与受损期望、程序汇总问题记录与五值） --------

_QUOTE_MARKS = str.maketrans({"“": '"', "”": '"'})


_WHY = {"no_address": "出处不存在（写记录编号，或 记录编号/fields/字段名）",
        "out_of_scope": "这条记录不在本轴材料里",
        "not_found": "出处里找不到这段原文"}


def bad_quotes(row: Mapping[str, Any], resources: Any) -> list[dict[str, Any]]:
    """逐条按资源核（spec/alg/resources.md §10.6）：resources 是本任务可见的资源（TaskView.resources）。"""
    out = []
    for q in row.get("quotes") or []:
        ref, quote = str(q.get("ref") or ""), str(q.get("quote") or "")
        result = resources.cite(ref, quote) if quote.strip() else None
        if result is None or not result.ok:
            why = _WHY[result.reason] if result is not None else _WHY["not_found"]
            if result is not None and result.hint:
                why += f"；{result.hint}"
            out.append({"row": row.get("id"), "ref": ref, "quote": q.get("quote"), "why": why})
    return out


def _bad_attribution(axis: str, item_id: str, attribution: str) -> list[str]:
    if attribution == "本轴":
        return []
    if attribution.startswith(UPSTREAM):
        targets = [x.strip() for x in attribution[len(UPSTREAM):].split(",")]
        allowed = [a for a in PROCESS_AXES if a != axis]
        if not targets or any(t not in allowed for t in targets):
            return [f"{item_id} 的 attribution={attribution!r} 冒号后必须是其他过程轴英文名（逗号分隔，可选 {allowed}）"]
        return []
    if attribution.startswith(UNRESOLVED):
        targets = [x.strip() for x in attribution[len(UNRESOLVED):].split(",")]
        if not targets or any(t not in PROCESS_AXES for t in targets):
            return [f"{item_id} 的 attribution={attribution!r} 冒号后必须是过程六轴英文名（逗号分隔，可选 {list(PROCESS_AXES)}）"]
        return []
    return [f"{item_id} 的 attribution={attribution!r} 格式不合法（只能是 本轴 / 上游:<轴> / 未定位:<候选轴>）"]


def check_actual(axis: str, own: Mapping[str, Any], expected: Mapping[str, Any], expectations: Mapping[str, Any],
                 resources: Any) -> list[str]:
    problems: list[str] = []
    ids = [item["id"] for item in expected["expected"]]
    got = [row["id"] for row in own["actual"]]
    if sorted(got) != sorted(ids) or len(set(got)) != len(got):
        problems.append(f"actual 的 id 必须与本应清单一一对应：本应 {ids}，实际 {got}")
    u_ids = [row["id"] for row in own["unexpected"]]
    if len(set(u_ids)) != len(u_ids) or (set(u_ids) & set(ids)):
        problems.append(f"unexpected 的 id 不能重复，也不能与本应清单 id 重名：{u_ids}")
    expectation_ids = {e["expectation_id"] for e in expectations["expectations"]}
    items = {item["id"]: item for item in expected["expected"]}
    for row in own["actual"]:
        # 必须独立查证：trace 证明不了"没做是错的"（spec/alg/process-axes.md §3.2；提交时打回，不由合成改判）
        if row["verdict"] == NOT_MET and items.get(row["id"], {}).get("needs_external") == "是":
            problems.append(f"{row['id']} 必须独立查证（needs_external=是）：trace 证明不了没做是错的，不能判没达到；"
                            "trace 里看得到做到了就判达到并引原文，看不出就判无法核")
        if row["verdict"] == NOT_MET:
            if not row["attribution"]:
                problems.append(f"{row['id']} 判没达到时 attribution 必须填 本轴 / 上游:<轴> / 未定位:<候选轴>")
            else:
                problems += _bad_attribution(axis, row["id"], row["attribution"])
        else:
            if row["attribution"]:
                problems.append(f"{row['id']} 判{row['verdict']}时 attribution 必须填空字符串")
            if row["affected_expectations"]:
                problems.append(f"{row['id']} 判{row['verdict']}时 affected_expectations 必须为 []"
                                "（若确实伤及某条期望结果应判没达到；本应清单外的额外问题写进 unexpected）")
        unknown_exp = [e for e in row["affected_expectations"] if e not in expectation_ids]
        if unknown_exp:
            problems.append(f"{row['id']} 的 affected_expectations 含有不在需求清单里的编号：{unknown_exp}")
        if row["verdict"] in QUOTED and not row.get("quotes"):
            problems.append(f"{row['id']} 判{row['verdict']}但没有引文" + ("（要引原文说明实际走的是哪条路）" if row["verdict"] == NOT_APPLICABLE else "（引不出原文就判无法核）"))
        problems += [json.dumps(b, ensure_ascii=False) for b in bad_quotes(row, resources)]
    for row in own["unexpected"]:
        problems += _bad_attribution(axis, f"unexpected {row['id']}", row["attribution"])
        unknown_exp = [e for e in row["affected_expectations"] if e not in expectation_ids]
        if unknown_exp:
            problems.append(f"unexpected {row['id']} 的 affected_expectations 含有不在需求清单里的编号：{unknown_exp}")
        if not row.get("quotes"):
            problems.append(f"unexpected {row['id']} 没有引文")
        problems += [json.dumps(b, ensure_ascii=False) for b in bad_quotes(row, resources)]
    return problems


def _kind(attribution: str) -> str:
    if attribution.startswith(UPSTREAM):
        return "upstream"
    if attribution.startswith(UNRESOLVED):
        return "unresolved"
    return "local"


def actual_result(axis: str, own: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    """程序填：轴级五值与组成、问题记录（spec/alg/process-axes.md §4–§5）。模型交的逐条判断原样照搬：
    不能成立的（坏引文、必须独立查证却判没达到、归因与状态不符）已在 check_actual 打回（demand/axis_loop.md §3.3.7）。"""
    items = {item["id"]: item for item in expected["expected"]}
    rows = [dict(row) for row in own["actual"]]
    # 不适用：这一步这次没发生、也不需要（换了路办成）——移出逐条结果，不计入轴级与兑现（spec/alg/process-axes.md §3.2）
    skipped = [r for r in rows if r["verdict"] == NOT_APPLICABLE]
    rows = [r for r in rows if r["verdict"] != NOT_APPLICABLE]
    issues: list[dict[str, Any]] = []
    for r in rows:
        if r["verdict"] != NOT_MET:
            continue
        e = items[r["id"]]
        quotes = list(r.get("quotes") or [])
        issues.append({"problem_id": f"{axis}-P{len(issues) + 1}", "item_id": r["id"], "origin": "expected",
                       "expected": f"{e['statement']}（依据：{e['basis']}）", "observed": r["observed"],
                       "attribution": _kind(r["attribution"]), "attribution_detail": r["attribution"],
                       "affected_expectations": list(r["affected_expectations"]),
                       "subcapability": [e["subcapability"]], "links": sorted(set(r.get("links") or [])),
                       "quotes": quotes, "output_refs": sorted({q["ref"] for q in quotes})})
    for u in own["unexpected"]:
        quotes = list(u.get("quotes") or [])
        issues.append({"problem_id": f"{axis}-P{len(issues) + 1}", "item_id": u["id"], "origin": "unexpected",
                       "expected": "本应清单未覆盖", "observed": u["observed"],
                       "attribution": _kind(u["attribution"]), "attribution_detail": u["attribution"],
                       "affected_expectations": list(u["affected_expectations"]),
                       "subcapability": [], "links": [],
                       "quotes": quotes, "output_refs": sorted({q["ref"] for q in quotes})})
    verdicts = [r["verdict"] for r in rows]
    kinds = [i["attribution"] for i in issues]
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
    results = [{**items[r["id"]], **{k: v for k, v in r.items() if k != "id"}, "id": r["id"]} for r in rows]
    return {"verdict": verdict, "composition": {"counts": counts,
                                                "not_covered": list(expected.get("not_covered") or []),
                                                "not_applicable": [{**items[r["id"]], **{k: v for k, v in r.items() if k != "id"}, "id": r["id"]}
                                                                   for r in skipped]},
            "results": results, "issues": issues}
