"""llm_probe_loop 的内置材料（spec/alg/axis_loop.md §4.1）：标准名 → 取值函数，取自 RunTrace 与场景登记。

一个 case 用一个 Case 对象：trace、场景条目、各轴框的描述。取值函数不调模型、不连外部信息源（知识源目录除外：
要列 ES 的文档数与字段骨架，和现方案的查证首条消息一样）。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from impl.core.axis_loop.materials import Material, MaterialUnavailable, Registry
from impl.core.live_protocol import business_call_failure
from impl.projects.llm_probe_loop.business_trace.expectation_material import project_requirements

from .requirements import user_turns
from .sources import expand_sources, union_catalog

TEXT = {"type": "string"}
SOURCE = {"type": "object", "properties": {
    "id": TEXT, "side": TEXT, "turn": TEXT, "component": TEXT, "value": {}, "scope": TEXT,
    "trace_refs": {"type": "array", "items": TEXT}}}
MISSING = {"type": "object", "properties": {"turn": TEXT, "component": TEXT, "reason": TEXT}}


@dataclass(frozen=True)
class Case:
    trace: Any
    scenario_id: str
    scenario: Mapping[str, Any]            # 场景条目（capability_map 里的一条）
    notes: Mapping[str, str]               # 轴 id → 场景里这个轴框的描述（原文，含信息源引用）

    def requirements(self) -> dict:
        """需求侧材料：只有用户各轮原话与历史，看不到交付（spec/alg/expectations.md §2.1）。
        场景对需求轴的描述走本轴描述槽位（spec/alg/axis_loop.md §2.5），不在这里。"""
        return project_requirements(self.trace)


def _deliveries(trace: Any) -> list[dict[str, Any]]:
    turns = []
    for n, record in enumerate(getattr(trace, "turn_records", None) or [], 1):
        output = record.get("extracted_output") if isinstance(record, Mapping) else None
        text = (output or {}).get("output_text") if isinstance(output, Mapping) else None
        if isinstance(text, str):
            turns.append({"turn": f"t{n}", "output_text": text})
    if turns:
        return turns
    output = trace.extracted_output if isinstance(trace.extracted_output, Mapping) else {}
    return [{"turn": "t1", "output_text": str(output.get("output_text") or "")}]


def _trace(case: Case, _: Mapping) -> dict[str, Any]:
    """这一轮 trace 的存档整理成的案卷（spec/alg/axis_loop.md §12.2.1）：目录、记录正文、程序枚举的环节表、缺口。
    整轮没采到或一条记录都没有 → 取不到（case 记运行失败）；一轮里缺端点照常给，缺口列在 gaps 里。"""
    from impl.projects.llm_probe_loop.business_trace.dossier import build_catalog, build_dossier, record_body, render_catalog, render_value
    from impl.projects.llm_probe_loop.business_trace.links import build_links, program_suspects

    fields = case.trace.project_fields if isinstance(case.trace.project_fields, Mapping) else {}
    dossier = build_dossier(case.trace, fields.get("business_trace"))
    failed = [c for c in dossier["coverage"] if c.get("status") == "failed"]
    if failed or not dossier["records"]:
        why = "；".join(f"{g['id']}：{g.get('reason')} {g.get('errors') or ''}".strip() for g in dossier["gaps"]
                       if g["id"].endswith((".collection", ".empty"))) or "存档里没有过程记录"
        raise MaterialUnavailable(f"trace 采集失败：{why}")
    sources = [{"id": src["id"], "kind": "request_response", "turn": src["id"],
                "fields": {"request_and_response": {"status": "available",
                                                    "value": render_value(dossier, src["request_and_response"])}}}
               for src in dossier["sources"]]
    links = build_links(dossier)["links"]
    recorder = next((src["recorder"] for src in dossier["sources"] if src.get("recorder")), "Agno")
    return {"catalog": render_catalog(build_catalog(dossier)),
            "records": sources + [record_body(dossier, row) for row in dossier["records"]],
            "links": links, "program_suspects": program_suspects(links, recorder=recorder),
            "gaps": dossier["gaps"], "coverage": dossier["coverage"], "dossier": dossier}


def _evidence(case: Case, _: Mapping) -> dict[str, bool]:
    """场景配了哪类证据（spec/alg/fulfilled.md §2.1）：选用了知识源（任一框引用 es / mcp）、选用了 trace 源。"""
    from .sources import selected_categories

    return {"knowledge": "knowledge" in selected_categories(case.notes.values()),
            "trace": bool((case.scenario.get("business_trace") or {}).get("source"))}


def _business_status(case: Case, _: Mapping) -> dict[str, Any]:
    failure = business_call_failure(case.trace)
    return {"ok": not failure, "error": failure or ""}


def _axis_note(case: Case, context: Mapping) -> str:
    return expand_sources(case.notes.get(context.get("axis") or "") or "", material_catalog=True)[0]


def _knowledge(case: Case, _: Mapping) -> dict[str, Any]:
    catalog, outline = union_catalog(case.notes.values())
    keep = ("uri", "title", "description", "notes", "doc_count")
    return {"catalog": [{k: c.get(k) for k in keep if c.get(k)} for c in catalog], "es_outline": outline}


def registry() -> Registry:
    obj = lambda **props: {"type": "object", "properties": props}
    return Registry([
        Material("case.requirements", obj(sources={"type": "array", "items": SOURCE}, missing={"type": "array", "items": MISSING}),
                 "需求侧材料：各轮用户原话、各轮请求里的历史，每条标了属于哪一轮（turn=t1/t2…）；"
                 "看不到交付。按轮切由需求轴的分发脚本做", lambda case, _: case.requirements()),
        Material("case.user_turns", {"type": "array", "items": TEXT}, "用户各轮原话，按先后排列",
                 lambda case, _: user_turns(case.trace)),
        Material("case.deliveries", {"type": "array", "items": obj(turn=TEXT, output_text=TEXT)},
                 "被测系统各轮的交付文本", lambda case, _: _deliveries(case.trace)),
        Material("case.business_status", obj(ok={"type": "boolean"}, error=TEXT), "被测系统这次有没有正常返回",
                 _business_status),
        Material("scenario.knowledge", obj(catalog={"type": "array", "items": obj(uri=TEXT, title=TEXT, description=TEXT, notes=TEXT,
                                                                                    doc_count={"type": "integer"})},
                                          es_outline={"type": "array"}),
                 "场景选用的知识源目录（读法说明、ES 字段骨架）", _knowledge),
        Material("case.trace", obj(catalog=TEXT, records={"type": "array", "items": obj(id=TEXT, kind=TEXT, turn=TEXT, fields={"type": "object"})},
                                   links={"type": "array", "items": obj(link_id=TEXT, link_type=TEXT, turn=TEXT, input={"type": "array"},
                                                                         output={"type": "array"}, facts={"type": "object"})},
                                   program_suspects={"type": "array"}, gaps={"type": "array"}, coverage={"type": "array"},
                                   dossier={"type": "object"}),
                 "这一轮业务 trace 的存档整理成的案卷：catalog 目录、records 记录正文（按编号读）、links 程序枚举的环节表"
                 "（类型、输入端 / 输出端是哪些记录的哪些字段）、program_suspects 程序按事实标出的可疑环节、gaps 采集缺口；"
                 "dossier 是整理前的原始案卷（给程序用）。跑业务时采集、存档，评测只读存档", _trace),
        Material("scenario.evidence", obj(knowledge={"type": "boolean"}, trace={"type": "boolean"}),
                 "场景配了哪类证据：knowledge = 选用了知识源；trace = 选用了 trace 源", _evidence),
        Material("axis.note", TEXT, "场景对当前这个轴写的描述", _axis_note),
    ])
