"""过程六轴的判定单元：一条义务 × 一个环节实例（spec/alg/process-axes.md §3–§6）。

程序负责：按类型枚举本轴环节、给每个环节配上适用义务、能由机器事实判定的义务直接判、
校验评测模型的输出覆盖每一对（义务, 环节）恰好一次、只标注不改偏差、按 Agg 汇总。
评测模型负责：读两端原文与出处，对其余每一对给出 pass/fail/insufficient_evidence/not_applicable/contract_missing。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from impl.core.structured_output import StructuredOutputSpec, enforce_output
from impl.projects.llm_probe.business_trace.materials import model_material
from impl.projects.llm_probe.business_trace.links import AXIS_LINK_TYPES, LIMITS, LINK_TYPES, build_links
from ..llm import axis_llm
from ..types import AxisSummary, RunOutcome, ScenarioAxis, raise_for_error_payload

PROCESS_TOOL_CALL_LIMIT = 3

from .process_protocol import (OUTCOMES, UNIT_OUTCOME_PRIORITY, Problem, PROTOCOL_PROMPT, EVIDENCE_GUIDE, JUDGING_GUIDE,
                               composition, issues_for, validate_units)
# 义务出处（§4）：agno=第 1 层通用语义，义务文本本身就是出处；trace=须指出 trace 中的规则原文；
# case=须指出场景描述/业务期望；project=用户确认过的项目声明。
SOURCES = ("agno", "trace", "case", "project")
# 引用里允许出现的非案卷编号：场景材料、项目声明。
CASE_REF = "case"
PROJECT_REF_PREFIX = "project:"
ABSENT_OBLIGATION = "link_absent"


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    link_type: str
    situation: str
    duty: str
    source: str = "agno"
    # 适用的环节编号前缀；空 = 兜底义务：本类型里没有任何限定前缀的内置义务覆盖的环节（含表外环节）。
    applies_to: tuple[str, ...] = ()
    label: str = ""
    # 能由机器事实直接判定时给出 (outcome, observed)；返回 None 交评测模型。
    program: Callable[[Mapping[str, Any]], tuple[str, str] | None] | None = None

    def matches(self, link: Mapping[str, Any]) -> bool:
        return (link["link_type"] == self.link_type and bool(self.applies_to)
                and any(link["link_id"].startswith(prefix) for prefix in self.applies_to))


@dataclass(frozen=True)
class AxisSpec:
    question: str
    excludes: str
    obligations: tuple[Obligation, ...]
    # 需求说明：本轴写给整理员的，业务语言、不含案卷结构等实现细节。
    requires: str = ""


def verbatim_arrival(link: Mapping[str, Any]) -> tuple[str, str] | None:
    """传递环节：上游产出原文出现在下游输入里，即原义到达；其余情形（改写、压缩、缺失）要读语义。"""
    if (link.get("facts") or {}).get("contains") is True:
        return "pass", "程序比对：上游产出原文完整出现在下游输入中"
    return None



def _axis_links(axis_id: str, dossier: Mapping[str, Any], structure: Mapping[str, Any]) -> list[dict[str, Any]]:
    """程序环节 + 分析轴补出的本轴表外环节（地图是先验，不是边界）。"""
    links = build_links(dossier, axis_id=axis_id)["links"]
    types = AXIS_LINK_TYPES[axis_id]
    for item in structure.get("suspects") or []:
        if item.get("off_map") and item.get("link_type") in types:
            links.append({"link_id": item["link_id"], "link_type": item["link_type"], "turn": "",
                          "input": [{"ref": ref, "field": ""} for ref in item.get("input_refs") or []],
                          "output": [{"ref": ref, "field": ""} for ref in item.get("output_refs") or []],
                          "facts": {}, "basis": "分析轴补出的表外环节：" + "；".join(item.get("why") or [])})
    return links


def _absent_obligation(axis_id: str) -> Obligation:
    types = "/".join(AXIS_LINK_TYPES[axis_id])
    return Obligation(ABSENT_OBLIGATION, types, f"程序没有列出本轴类型（{types}）的任何环节",
                      "确认本轮确实不需要这类环节（not_applicable，引用正面证据）；本应发生但未发生时引用上游问题判 input_invalid，指不出则 insufficient_evidence；"
                      "若这类环节发生了却没有记录，insufficient_evidence 并写明缺什么",
                      label="本轴环节是否发生")


def project_obligations(entry: Mapping[str, Any] | None, axis_id: str) -> tuple[Obligation, ...]:
    """场景条目 process_obligations：trace 里读不到、又需要判的约定，每条经用户确认。"""
    types = AXIS_LINK_TYPES[axis_id]
    out = []
    for item in (entry or {}).get("process_obligations") or []:
        if item["link_type"] not in LINK_TYPES:
            raise ValueError(f"process_obligations.{item['id']}.link_type {item['link_type']!r} 不是环节类型 {list(LINK_TYPES)}")
        if item["link_type"] not in types:
            continue
        out.append(Obligation(f"{PROJECT_REF_PREFIX}{item['id']}", item["link_type"], item["situation"], item["duty"],
                              source="project", applies_to=tuple(item.get("applies_to") or ()),
                              label=f"项目声明（{item['confirmed']} 确认）：{item.get('label') or item['id']}"))
    return tuple(out)


def _scenario_entry(runtime: Any) -> Mapping[str, Any] | None:
    from impl.core.capability_store import load_capability_map

    entry = load_capability_map(runtime.spec.project_id).get(runtime.scenario_id)
    return entry if isinstance(entry, Mapping) else None


def pair_up(obligations: tuple[Obligation, ...], links: list[Mapping[str, Any]]
            ) -> tuple[dict[tuple[str, str], dict[str, Any]], list[tuple[str, str]]]:
    """每条链接配上适用义务；程序可判的先判，其余成为交评测模型的 pending。

    限定前缀的义务管它点名的环节；兜底义务管同类型里没被内置限定义务点名的环节。
    项目声明只增不减：它不会让兜底义务退出。
    """
    decided: dict[tuple[str, str], dict[str, Any]] = {}
    pending: list[tuple[str, str]] = []
    scoped = [ob for ob in obligations if ob.applies_to and ob.source != "project"]
    for link in links:
        claimed = any(ob.matches(link) for ob in scoped)
        for ob in obligations:
            if ob.link_type != link["link_type"]:
                continue
            if link.get("obligation_ids") and ob.obligation_id not in link["obligation_ids"]:
                continue
            if not link.get("obligation_ids") and not (ob.matches(link) if ob.applies_to else not claimed):
                continue
            verdict = ob.program(link) if ob.program else None
            if verdict is None:
                pending.append((ob.obligation_id, link["link_id"]))
                continue
            outcome, observed = verdict
            decided[(ob.obligation_id, link["link_id"])] = {
                "obligation_id": ob.obligation_id, "link_id": link["link_id"], "outcome": outcome,
                "expected": ob.duty, "observed": observed, "source_refs": [],
                "evidence": {"input": [e["ref"] for e in link["input"]], "output": [e["ref"] for e in link["output"]]},
                "missing": [], "judged_by": "program", "flags": [],
            }
    return decided, pending


def check_coverage(results: list[Mapping[str, Any]], pending: list[tuple[str, str]]) -> None:
    """结构校验：每一对恰好一次，不新增；缺证必须说缺什么。"""
    seen = [(r["obligation_id"], r["link_id"]) for r in results]
    duplicate = sorted({p for p in seen if seen.count(p) > 1})
    unknown = sorted(set(seen) - set(pending))
    absent = [p for p in pending if p not in set(seen)]
    if duplicate or unknown or absent:
        raise ValueError(f"results 必须恰好覆盖 pending：重复 {duplicate[:5]}，未知 {unknown[:5]}，遗漏 {absent[:5]}")
    for r in results:
        if r["outcome"] == "insufficient_evidence" and not r["missing"]:
            raise ValueError(f"{r['obligation_id']} @ {r['link_id']} 缺少 missing")


def validate_result_evidence(results, obligations, links, readable, *, require_refs=True):
    """An evaluator's unsupported claim is a format/protocol error, not business missing evidence."""
    for r in results:
        refs = r['source_refs'] + r['evidence']['input'] + r['evidence']['output']
        for p in r.get('problems', []):
            refs += p['source_refs'] + p['input_refs'] + p['output_refs']
        unknown = [ref for ref in refs if ref not in readable and not _special_ref(ref)]
        if unknown:
            raise ValueError(f'引用未交付正文：{unknown}')
        # 问题可跨单位引用判准；只有单位自己的出处必须是本单位的义务。
        for ref in r['source_refs']:
            if ref.startswith('obligation:') and ref.removeprefix('obligation:') != r['obligation_id']:
                raise ValueError('通用义务引用必须指向本单位的义务')
        if require_refs and r['outcome'] in {'pass', 'not_applicable', 'fail', 'input_invalid'} and not any(r['evidence'].values()):
            raise ValueError('结论没有 trace 引用')
        link = links.get(r['link_id'], {})
        if link.get('origin') == 'expectation_deduction' and not r.get('matched_link_id') and not r.get('discharged'):
            if r['outcome'] not in {'input_invalid', 'insufficient_evidence', 'contract_missing'} and r['obligation_id'] not in {'reference_resolution', 'ambiguity', 'constraints'}:
                raise ValueError('应发生而未发生的单位不能判正常或不适用')
        if r['outcome'] in {'pass', 'fail'} and obligations[r['obligation_id']].source in {'trace', 'case'} and not r['source_refs']:
            raise ValueError('结论缺少判准出处')


def _special_ref(ref: str) -> bool:
    return ref == CASE_REF or ref.startswith((PROJECT_REF_PREFIX, 'obligation:', 'expectation:', 'design:'))


def annotate(results: list[dict[str, Any]], obligations: Mapping[str, Obligation],
             links: Mapping[str, Mapping[str, Any]], ids: set[str], scope_note: str, *, program_evidence: bool = False) -> set[str]:
    """v 校验：只查结构、只加标注，fail 永远保留。唯一改状态的情形：pass/not_applicable 没有引用或检查范围。"""
    unverified: set[str] = set()
    for r in results:
        flags = list(r.get("flags") or [])
        if r["judged_by"] == "program":
            r["flags"] = flags
            continue
        refs = r["source_refs"] + r["evidence"]["input"] + r["evidence"]["output"]
        unknown = [ref for ref in refs if ref not in ids and not _special_ref(ref)]
        if unknown:
            unverified.update(unknown)
            flags.append(f"引用未见本轴读取回执：{unknown}")
        ob = obligations[r["obligation_id"]]
        cited = r["evidence"]["input"] or r["evidence"]["output"]
        # 证据端点由程序给出时，本来就没有端点的单位（本轴无环节、未对接实际行使的应发生单位）无从引用，只靠检查范围。
        anchor = links.get(r.get("matched_link_id") or r["link_id"]) or {}
        no_endpoints = program_evidence and not (anchor.get("input") or anchor.get("output"))
        if r["outcome"] in {"pass", "not_applicable"} and ((not cited and not no_endpoints) or not scope_note.strip()):
            flags.append(f"{r['outcome']} 没有引用或检查范围 → insufficient_evidence")
            r["outcome"] = "insufficient_evidence"
            r["missing"] = r["missing"] or ["没有说明检查范围或正面证据"]
        if r["outcome"] == "fail" and not (r["evidence"]["input"] and r["evidence"]["output"]):
            flags.append("fail 未给出两端证据，需人工核对")
        if r["outcome"] in {"pass", "fail"} and ob.source in {"trace", "case"} and not r["source_refs"]:
            flags.append(f"{r['outcome']} 未指出义务出处（source={ob.source}）")
        link = links.get(r.get("matched_link_id") or r["link_id"])
        if link and link["link_type"] == "model_capability" and r["outcome"] in {"pass", "fail"}:
            own = {e["ref"] for e in link["input"]}
            outside = [ref for ref in r["source_refs"] if ref not in own and not _special_ref(ref)]
            if outside:
                flags.append(f"模型环节的出处不在该次调用的输入里：{outside}")
        r["flags"] = flags
    return unverified


def aggregate_verdict(results: list[Mapping[str, Any]]) -> tuple[str, str]:
    """Agg（§6）：契约缺失单列、不参与 sound；其余取第一个成立的。"""
    judged = [r["outcome"] for r in results if r["outcome"] != "contract_missing"]
    if "fail" in judged:
        return "problematic", "any_fail"
    if "insufficient_evidence" in judged:
        return "not_evaluable", "any_insufficient_evidence"
    if "pass" in judged:
        return "sound", "any_pass"
    if "input_invalid" in judged:
        return "untested", "only_input_invalid"
    if judged:
        return "not_applicable", "none_applicable"
    if results:
        return "not_evaluable", "only_contract_missing"
    return "not_evaluable", "no_results"


def _citations(r: Mapping[str, Any]) -> list[dict[str, str]]:
    return ([{"source": "出处", "ref": ref} for ref in r["source_refs"]]
            + [{"source": "输入端", "ref": ref} for ref in r["evidence"]["input"]]
            + [{"source": "输出端", "ref": ref} for ref in r["evidence"]["output"]]
            + [{"source": "缺口", "ref": "", "note": item} for item in r["missing"]]
            + [{"source": "标注", "ref": "", "note": item} for item in r.get("flags") or []])


def _outcome(results: list[dict[str, Any]], obligations: Mapping[str, Obligation], reason: str,
             scope_note: str, coverage: Mapping[str, Any], usage: dict[str, Any], *, axis_id: str) -> RunOutcome:
    discharged = [r for r in results if r.get('discharged')]
    results = [r for r in results if not r.get('discharged')]
    coverage = {**coverage, 'satisfied_actions': discharged} if isinstance(coverage, Mapping) else {'records': coverage, 'satisfied_actions': discharged}
    issues = issues_for(axis_id, results)
    from ...process_loop.expectation_projection import coalesce
    results = coalesce(results)
    parts = composition(results)
    labels = dict(zip(OUTCOMES, ("做到", "没做到", "缺证", "输入无效", "未发生", "缺判准")))
    composition_note = "；组成：" + "、".join(f"{labels[key]} {count}" for key, count in parts['counts'].items())
    verdict, rule = aggregate_verdict(results)
    if not results and discharged:
        verdict, rule = 'not_applicable', 'all_candidate_actions_satisfied'
    missing = list(dict.fromkeys(m for r in results for m in r["missing"]))
    contract_missing = [{"obligation_id": r["obligation_id"], "link_id": r["link_id"], "expected": r["expected"]}
                        for r in results if r["outcome"] == "contract_missing"]
    refs = {ref for r in results for ref in r["evidence"]["input"] + r["evidence"]["output"] + r["source_refs"]}
    return RunOutcome(
        output={
            "assessment": {"verdict": verdict, "reason": reason, "verdict_rule": rule, "scope_note": scope_note,
                           "gaps": missing, "contract_missing": contract_missing, "composition": parts},
            "results": results, "issues": issues,
            "obligations": [{"obligation_id": ob.obligation_id, "link_type": ob.link_type, "situation": ob.situation,
                             "duty": ob.duty, "source": ob.source, "label": ob.label or ob.obligation_id}
                            for ob in obligations.values()],
            "evidence_refs": sorted(ref for ref in refs if not _special_ref(ref)),
            "missing_evidence": missing, "coverage": coverage,
        },
        summary=AxisSummary(reason + composition_note, [
            {"key": f"{obligations[r['obligation_id']].label or r['obligation_id']} @ {r['link_id']}",
             "value": r["outcome"], "reason": f"应做到：{r['expected']}；实际：{r['observed']}",
             "citations": _citations(r), "upstream_issue_ids": r.get("upstream_issue_ids", []),
             "problem_ids": [p["problem_id"] for p in r.get("problems", [])]}
            for r in results
        ]),
        usage=usage,
    )


def run_process_axis(axis_id: str, inputs: Mapping[str, Any], axis: ScenarioAxis,
                     runtime: Any, spec: AxisSpec) -> RunOutcome:
    # 分析轴成功才会发动本轴（depend_on），案卷必然存在；没有案卷时分析轴已 failed，本轴 blocked。
    from .transcript_axes import is_transcript, run_axis
    from .process_output import OUTPUT, UNIT_SYSTEM, UNIT_CONSUMER, build_units, validate_submission
    from ...business_trace.design_rules import dossier_blocks

    if is_transcript(inputs["trace_analysis"]["dossier"]):
        return run_axis(axis_id, inputs, axis, runtime, spec)
    analysis = inputs["trace_analysis"]
    dossier = analysis["dossier"]
    coverage = analysis.get("coverage") or {}
    structure = analysis.get("structure") or {}
    selection = (analysis.get("selections") or {}).get(axis_id) or {}
    if "materials" in selection and not selection["materials"]:
        raise ValueError("分析轴未交付的环节材料")
    from ...process_loop.expectation_projection import prepare, required_units, criteria_for, validate_dossier_expectations
    expectations = inputs['expectations']
    client = axis_llm(runtime.spec, role="judge")
    runtime_links = _axis_links(axis_id, dossier, structure)
    if not runtime.expectation_projection:
        # Only original tool declarations enter the pre-run data-needs projection.
        preparation_links = [dict(link_id=row['id'], link_type='planning_routing', turn=row.get('turn', ''),
                                  input=[{'ref': row['id'], 'field': 'definition'}], output=[])
                             for row in dossier.get('records', []) if row.get('kind') == 'definitions']
        tools = [b for b in dossier_blocks(dossier, preparation_links, 'planning_routing') if b['component'] == 'tools']
        runtime.expectation_projection.update(prepare(expectations, client, runtime.trace_id, tools=tools))
    projection = runtime.expectation_projection
    required = required_units(axis_id, expectations, projection)
    links = runtime_links + required
    obligations = spec.obligations + project_obligations(_scenario_entry(runtime), axis_id)
    if not links:
        absent = _absent_obligation(axis_id)
        obligations = (absent,)
        links = [{"link_id": f"{axis_id}:none", "link_type": absent.link_type, "turn": "", "input": [], "output": [],
                  "facts": {}, "basis": "程序未列出本轴类型的环节"}]
    by_ob = {ob.obligation_id: ob for ob in obligations}
    by_link = {link["link_id"]: link for link in links}
    decided, pending = pair_up(obligations, links)
    criteria = criteria_for(pending, by_link, by_ob)

    from ...business_trace.materials import prepare_axis_materials, material_view
    batches = list(selection.get('materials') or prepare_axis_materials(
        dossier, [l for l in links if l.get('origin') != 'expectation_deduction'],
        list(structure.get('suspects') or []), extra_refs=list(selection.get('refs') or [])))
    if required:
        batches += prepare_axis_materials(dossier, required, [], extra_refs=list(selection.get('refs') or []))
    scheduled = [(ob, link['link_id']) for batch in batches for link in batch['links']
                 for ob, ident in pending if ident == link['link_id']]
    if len(scheduled) != len(set(scheduled)) or set(scheduled) != set(pending):
        raise ValueError('发送前检查失败：材料批次与 pending 必须一一覆盖，不得重复或遗漏')
    expectations_by_id = {e['expectation_id']: e for e in expectations['expectations']}
    sources_by_id = {s['id']: s for s in expectations['sources']}
    output_spec = OUTPUT
    llm_results, reasons, scopes, reads = [], [], [], []
    unverified: set[str] = set()
    batch_audit, failures = [], []
    for number, batch in enumerate(batches, 1):
        batch_ids = {link["link_id"] for link in batch["links"]}
        batch_pending = [pair for pair in pending if pair[1] in batch_ids]
        if not batch_pending:
            continue
        view = batch["view"]
        batch_required = [u for u in required if u['link_id'] in batch_ids]
        if batch_required:
            turns = {u['turn'].replace('t', 'turn', 1) for u in batch_required}
            # 分析轴补出的表外环节没有轮次（turn 为空），同样是真实行使，可以对接。
            candidates = [l for l in runtime_links if l.get('turn') in turns or not l.get('turn')
                          or any(u['turn'] == 'case' for u in batch_required)]
            view = material_view(dossier, batch['links'] + candidates, list(structure.get('suspects') or []),
                                 extra_refs=list(selection.get('refs') or []))
        else:
            candidates = []
        original = dossier_blocks(dossier, batch['links'] + candidates, axis_id)
        # Dynamic design rules can only cite these complete, program-selected blocks.
        batch_units, batch_criteria, block_map = build_units(batch_pending, criteria, by_link, original)
        pending_ob_ids = {u["obligation_id"] for u in batch_units.values()}
        # 本批只交付挂到本批单位上的期望及其原文出处，不整轴灌入。
        cited = sorted({ref.removeprefix('expectation:') for pair in batch_pending for ref in criteria[pair]
                        if ref.startswith('expectation:')})
        batch_expectations = [expectations_by_id[ident] for ident in cited]
        batch_sources = [sources_by_id[s] for s in dict.fromkeys(r for e in batch_expectations for r in e['source_refs'])]
        reference_catalog = {
            'records': [{'id': row['id'], 'fields': list(row.get('fields', {}))}
                        for row in model_material(view).get('records', [])],
            'readable_ids': sorted({str(row['id']) for row in view['reads']}),
            'gap_ids': [gap['id'] for gap in view.get('gaps', [])],
        }
        readable_ids = set(reference_catalog['readable_ids'])
        source_to_evidence = {source['id']: [ref for ref in source.get('trace_refs', []) if ref in readable_ids]
                              for source in batch_sources}
        user = json.dumps({
            "expectations": batch_expectations,
            "expectation_sources": batch_sources,
            "source_to_evidence": source_to_evidence,
            "expectation_units": batch_required,
            "reference_catalog": reference_catalog,
            "dimension": axis_id, "dimension_question": spec.question, "dimension_excludes": spec.excludes,
            "recorded_issues": list(getattr(runtime, "process_issues", {}).values()),
            "obligations": [{"obligation_id": ob.obligation_id, "link_type": ob.link_type, "situation": ob.situation,
                             "duty": ob.duty, "source": ob.source} for ob in obligations if ob.obligation_id in pending_ob_ids],
            "units": {uid: {**u, "obligation": u['obligation_id'], "link": u['link_id']} for uid, u in batch_units.items()},
            "original_blocks": block_map,
            "criteria": batch_criteria,
            "program_results": [{k: r[k] for k in ("obligation_id", "link_id", "outcome", "observed")}
                                for r in decided.values() if r["link_id"] in batch_ids],
            "links": {"limits": LIMITS, "links": batch["links"], "match_candidates": candidates},
            "suspects_for_this_axis": selection.get("why") or [],
            "dossier_view": model_material(view),
        }, ensure_ascii=False, default=str)
        readable = {str(r["id"]) for r in view["reads"]} | {str(g["id"]) for g in view.get("gaps", [])}

        def ask(prompt: str) -> tuple[list[dict[str, Any]], str, str]:
            runtime.ensure_time_left(axis_id)
            payload = client.complete_json(UNIT_SYSTEM + UNIT_CONSUMER, prompt, trace_id=runtime.trace_id,
                                          stage=f"llm_probe_process_{axis_id}_batch{number}", reasoning_effort="low",
                                          output_spec=output_spec)
            raise_for_error_payload(payload)
            if isinstance(payload, Mapping):
                payload = {k: v for k, v in payload.items() if k not in {"raw_model_response", "metrics", "_tool_call_log"}}
            enforce_output(payload, output_spec, caller=axis_id)
            first_problem = len({p["problem_id"] for r in llm_results for p in r["problems"]}) + 1
            results = validate_submission(payload, batch_units, batch_criteria, by_link, readable,
                axis_id=axis_id, first_problem=first_problem, blocks=block_map, obligations=by_ob,
                expectations=expectations, required=batch_required,
                recorded_issues=list(getattr(runtime, 'process_issues', {}).values()))
            validate_dossier_expectations(results, by_ob, expectations, by_link, dossier)
            issues_for(axis_id, llm_results + results)
            return results, payload["reason"], payload["scope_note"]

        try:
            try:
                results, reason, scope_note = ask(user)
            except ValueError as exc:
                # One correction round with every rejection reason; a second invalid response is an evaluator error.
                results, reason, scope_note = ask(user + "\n上次输出未通过程序检查，请按原任务完整重新输出 JSON，并修正全部问题：\n" + str(exc))
        except ValueError as exc:
            failures.append(f"批次{number}（{len(batch_pending)} 个单位）：{exc}")
            continue
        unverified.update(annotate(results, by_ob, by_link, readable, scope_note, program_evidence=True))
        for result in results:
            cited_refs = result["source_refs"] + result["evidence"]["input"] + result["evidence"]["output"]
            unread = [ref for ref in cited_refs if ref not in readable and not _special_ref(ref)]
            if unread and result["outcome"] in {"pass", "not_applicable"}:
                result["outcome"] = "insufficient_evidence"
                result["missing"] = result["missing"] or [f"正面结论引用未交付正文：{unread}"]

        llm_results.extend(results)
        reasons.append(reason)
        scopes.append(scope_note)
        reads.extend(view["reads"])
        batch_audit.append({"number": number, "link_ids": sorted(batch_ids), "chars": batch["chars"],
                            "prompt_chars": len(user), "oversize": batch["oversize"],
                            "missing_endpoints": view["missing_endpoints"]})
    reason = "；".join(reasons) if reasons else "本轴全部义务由程序按机器事实判定"
    scope_note = "；".join(scopes) if scopes else "程序判定：" + "、".join(by_link)
    judged = {(r["obligation_id"], r["link_id"]): r for r in llm_results}
    judged.update(decided)
    ordered = [judged[(ob.obligation_id, link["link_id"])]
               for link in links for ob in obligations if (ob.obligation_id, link["link_id"]) in judged]
    for r in ordered:
        r.setdefault("flags", [])
    outcome = _outcome(ordered, by_ob, reason, scope_note, coverage, {**client.usage(), "tool_calls": 0}, axis_id=axis_id)
    why = selection.get("why") or []
    outcome.output["selection"] = {"refs": list(selection.get("refs") or []),
                                   "why": [why] if isinstance(why, str) else list(why)}
    outcome.output["view"] = {"chars": sum(b["chars"] for b in batch_audit),
                              "records": len({r["id"] for b in batches for r in b["view"]["records"]}),
                              "excluded": [], "unverified_refs": sorted(unverified),
                              "batches": batch_audit, "failed_batches": failures,
                              "expectations_sha256": expectations['sha256'],
                              "design_sha256": projection.get('design_sha256'),
                              "evidence_audit": {"reads": reads, "calls": 0, "budget": 0,
                                                 "delivery": "analysis_materials"}}
    if failures:
        # 评测器输出不合格是运行错误（process-axes.md §6），不进单位取值；已通过批次的结果与问题留作诊断。
        # 部分批次汇总出的 verdict 不是本轴结论，不能留给主判当作能力判断。
        outcome.output["assessment"].update(verdict=None, verdict_rule="evaluator_failed")
        outcome.failed = True
        outcome.failure_reason = f"评测器输出未通过校验，{len(failures)}/{len(batch_audit) + len(failures)} 个批次失败：" + "\n".join(failures)
        return outcome
    check_coverage(llm_results, pending)
    return outcome


def _collect(*checks: Callable[[], Any], into: list[str] | None = None) -> list[str]:
    errors = [] if into is None else into
    found = []
    for check in checks:
        try:
            check()
        except ValueError as exc:
            found.append(str(exc))
    errors.extend(found)
    return found


PROCESS_SPECS: dict[str, AxisSpec] = {}


def axis_type(type_id: str, title: str, summary: str, spec: AxisSpec) -> Any:
    from ..types import AxisType, Dependency, ExecutionLimits, Input, Verdict

    types = set(AXIS_LINK_TYPES[type_id])
    # 每个类型至少一条不限前缀的义务，表外环节才有义务可判。
    for link_type in types:
        if not any(ob.link_type == link_type and not ob.applies_to for ob in spec.obligations):
            raise ValueError(f"{type_id} 缺少覆盖 {link_type} 全部环节的通用义务")
    if any(ob.link_type not in types for ob in spec.obligations):
        raise ValueError(f"{type_id} 的义务类型超出本轴 π")
    PROCESS_SPECS[type_id] = spec
    return AxisType(
        type_id=type_id, title=title, summary=summary, verdict_scope="axis",
        verdict_enum=(Verdict("sound", "已核实范围内没问题；须同时查看组成与缺判准"),
                      Verdict("problematic", "至少一个环节违反义务"),
                      Verdict("not_evaluable", "至少一个环节缺证，或只剩契约缺失"),
                      Verdict("untested", "本应行使但没有输入有效的行使，须修上游并查看覆盖缺口"),
                      Verdict("not_applicable", "有正面证据证明本次不需要")),
        depend_on=(Dependency("expectations"), Dependency("trace_analysis"),),
        trigger_when=None,
        inputs=(Input("trace_analysis", source="axis.trace_analysis.output",
                      fields=["verdict", "dossier", "coverage", "structure", "selections"]),
                Input("expectations", source="axis.expectations.output",
                      fields=("verdict", "expectations", "sources", "missing", "material_sha256", "sha256")),),
        output_fields=("assessment", "results", "issues", "obligations", "evidence_refs", "missing_evidence",
                       "coverage", "selection", "view"),
        scenario_fields=(),
        limits=ExecutionLimits(tool_calls=PROCESS_TOOL_CALL_LIMIT, seconds=1200),
        run=lambda inputs, axis, runtime: run_process_axis(type_id, inputs, axis, runtime, spec),
        verdict_path="assessment.verdict", requires_business_trace=True,
        implementation_files=(f"impl/projects/llm_probe/eval_axes/adapters/{type_id}.py",
                              "impl/projects/llm_probe/eval_axes/adapters/process_common.py",
                              "impl/projects/llm_probe/eval_axes/adapters/process_protocol.py",
                              "impl/projects/llm_probe/eval_axes/adapters/process_output.py",
                              "impl/projects/llm_probe/process_loop/expectation_projection.py",
                              "impl/projects/llm_probe/eval_axes/adapters/expectations.py",
                              "impl/projects/llm_probe/business_trace/expectation_material.py",
                              "impl/projects/llm_probe/eval_axes/adapters/trace_analysis.py",
                              "impl/projects/llm_probe/business_trace/dossier.py",
                              "impl/projects/llm_probe/business_trace/design_rules.py",
                              "impl/projects/llm_probe/business_trace/materials.py",
                              "impl/projects/llm_probe/business_trace/links.py",
                              "impl/projects/llm_probe/business_trace/tools.py",
                              "impl/projects/llm_probe/eval_axes/adapters/transcript_axes.py",
                              "impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py"),
    )
