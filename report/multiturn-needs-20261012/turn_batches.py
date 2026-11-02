"""一批只放一轮：与线上 prepare_selections 同一套环节、同一条附带规则，唯一改动是先按轮分组再切批。"""
import json, re
from impl.projects.llm_probe.business_trace.materials import prepare_axis_materials
from impl.projects.llm_probe.business_trace.links import AXIS_LINK_TYPES
from impl.projects.llm_probe.eval_axes.adapters.process_common import _axis_links


def turn_no(text):
    found = [int(m) for m in re.findall(r"turn(\d+)", text)]
    return max(found) if found else None


def content_owners(dossier):
    """content#N → 引用它的记录所在轮次（同一正文可能被多轮记录引用）。"""
    owners = {}
    for rec in dossier.get("records") or []:
        t = turn_no(rec.get("id", ""))
        for token in set(re.findall(r"content#\d+", json.dumps(rec.get("fields") or {}, ensure_ascii=False))):
            owners.setdefault(token, set()).add(t)
    return owners


def link_turn(link, owners, case_turns):
    refs = [e["ref"] for e in (link.get("input") or []) + (link.get("output") or [])]
    found = [turn_no(str(link.get("turn") or ""))] + [turn_no(r) for r in refs]
    for r in refs:  # 只引用共享正文的表外环节：取正文最早出现的一轮
        if r.startswith("content#") and owners.get(r):
            found.append(min(t for t in owners[r] if t))
    found = [t for t in found if t]
    if found:
        return max(found)
    if len(case_turns) == 1:
        return case_turns[0]
    raise ValueError(f"环节算不出轮次：{link['link_id']}")


def turn_materials(axis_id, dossier, structure, selection):
    links = _axis_links(axis_id, dossier, structure)
    suspects = list(structure.get("suspects") or [])
    case_turns = sorted({turn_no(r.get("id", "")) for r in dossier.get("records") or []} - {None}) or [1]
    if not links:  # 与线上相同：没有环节时用占位环节，并附分析轴挑出的记录（这种批次不按轮切）
        links = [{"link_id": f"{axis_id}:none", "link_type": "/".join(AXIS_LINK_TYPES[axis_id]), "turn": "", "input": [],
                  "output": [], "facts": {}, "basis": "程序未列出本轴类型的环节"}]
        return [{**b, "turn": case_turns[-1]} for b in
                prepare_axis_materials(dossier, links, suspects, extra_refs=list(selection.get("refs") or []))]
    owners = content_owners(dossier)
    groups = {}
    for link in links:
        groups.setdefault(link_turn(link, owners, case_turns), []).append(link)
    return [{**b, "turn": t} for t in sorted(groups) for b in prepare_axis_materials(dossier, groups[t], suspects)]
