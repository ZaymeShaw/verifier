"""过程六轴的判定单元：一条义务 × 一个环节实例（spec/alg/process-axes.md §3–§6）。

程序负责：按类型枚举本轴环节、给每个环节配上适用义务、能由机器事实判定的义务直接判、
校验评测模型的输出覆盖每一对（义务, 环节）恰好一次、只标注不改偏差、按 Agg 汇总。
评测模型负责：读两端原文与出处，对其余每一对给出 pass/fail/insufficient_evidence/not_applicable/contract_missing。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

from impl.core.materials_store import expand_material_uris
from impl.core.structured_output import StructuredOutputSpec, enforce_output
from impl.projects.llm_probe.business_trace.materials import model_material
from ...process_contract import criterion_text
from impl.projects.llm_probe.business_trace.links import AXIS_LINK_TYPES, LIMITS, LINK_TYPES, build_links
from ..llm import axis_llm
from ..types import AxisSummary, RunOutcome, ScenarioAxis, raise_for_error_payload

PROCESS_TOOL_CALL_LIMIT = 3

from .process_protocol import (OUTCOMES, Problem, PROTOCOL_PROMPT, composition, issues_for, validate_units)
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


@dataclass
class ExpectationCheck:
    expectation_id: str = field(metadata={'description': '当前结果 expectation_ids 中的一个 ID，每个 ID 恰好一项。'})
    outcome: Literal["pass", "fail", "insufficient_evidence", "input_invalid", "not_applicable", "contract_missing"]
    observed: str = field(metadata={'description': '核对该期望的完整陈述及适用条件，引用具体事实；条件不成立须说明依据。'})


@dataclass
class ResultGroup:
    obligation_id: str = field(metadata={'description': '照抄 pending 中待判的义务 ID。'})
    link_ids: list[str] = field(metadata={'description': '照抄 pending 的位置 ID；有问题或上游引用时只能有一个位置。不是证据编号。'})
    outcome: Literal["pass", "fail", "insufficient_evidence", "input_invalid", "not_applicable", "contract_missing"]
    expectation_ids: list[str] = field(metadata={'description': '本条核对的定格期望 ID，必须与 expectation_checks 一一对应。'})
    matched_link_id: str = field(metadata={"allow_empty": True, "description": "必填。普通运行单位填空字符串；应发生单位填匹配的实际事件，未定位也填空字符串。不得省略。"})
    expectation_checks: list[ExpectationCheck]
    observed: str
    source_refs: list[str] = field(metadata={'description': '已给出的判准引用：obligation:<义务ID>、expectation:<期望ID>、project:<项目义务ID>、case，或已完整读取的证据目录 ID；不能填 expectation_sources.id。'})
    input_refs: list[str] = field(metadata={'description': '实际读到的输入端证据 ID；使用给定目录中的编号，不拼接字段路径。'})
    output_refs: list[str] = field(metadata={'description': '实际读到的输出端证据 ID；模型行为只引用该次响应，问题引用须为本数组子集。'})
    missing: list[str]
    problems: list[Problem] = field(default_factory=list)
    upstream_issue_ids: list[str] = field(default_factory=list)
    origin: Literal["runtime_recall", "expectation_deduction"] = "runtime_recall"


@dataclass
class ProcessAssessment:
    reason: str
    scope_note: str
    results: list[ResultGroup]


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


_SYSTEM = """你是业务执行过程评测员。对 pending 中每一对 obligation_id（义务）和 link_id（一次行使），依据真实输入、适用要求、真实输出作判断。
单轴请求用 dimension 指定本次轴；共享会话用各份 briefing.axis 指定轴。各轴职责及合法 ID 见后文。最终答复有误不代表所有环节都有误。

【输入字段】
obligations 给出义务及适用情形；source=agno 表示通用义务本身是判准，使用 obligation:<obligation_id> 引用。
source=project 表示已确认的项目义务本身就是判准，可引用其 project:<id>；不用从 expectations 中虚构同一条期望。source=trace/case 还需要本案规则或场景要求，应引用 expectations 中对应要求。不能凭错误码、耗时或重复次数自行发明限制。
expectations 是定格期望；expectation_sources 给出原文及采集范围。来源 ID 与运行证据 ID 是不同命名空间。
单轴请求的 links.links 是本批待判环节，links.match_candidates 是应发生单位的真实候选事件；共享会话的 briefing.links 是本轴环节。候选存在不代表已经完成要求。
program_results 是程序已核对的单位，不再输出。facts 只描述机器可见关系，contains=false 可能只是表示不同。
单轴请求的 suspects_for_this_axis、共享会话的 briefing.suspects 都是待核实线索，不是判词，不限制检查范围。若提供 recorded_issues，只能引用其中已登记的问题。

【证据使用】
传递是否无损必须比较传递前后两端；合理压缩不等于改义。原始模型请求优先于重建消息；重建只能在已说明的范围内使用。
HTTP/span 成功不证明语义正确；落库结果不等于调用方实收；采集时定义不证明当次版本或模型已收到。
不可见不证明未发生。缺少与当前义务无关的端点不妨碍本项判定；缺少必要端点必须说明具体影响。
模型行为只对照本次调用自己的实际输入和完整输出；输入没包含的外部规则不能拿来判模型违约。
系统准入、容量、预算的拒绝先看规划策略，不自动当作工具执行故障。单次耗时只按该调用的适用时限判断，无判准填 contract_missing。

【判定范围】
忠实性须核对完整输出中的业务声明，包括前置说明、草稿、正文和结尾；保留对象、数值、单位、范围、否定和不确定性。后文正确不抵消前文错误。
规则里的能力、允许、建议、必须和禁止不能互换。条件不成立须解释依据，不能静默跳过；没有偏差证据不强行找错。
输入已证实无效的子能力按 input_invalid 及其上游问题处理；其他不依赖该坏输入的义务仍须判断，不能整轴免检。
reason 解释结论，scope_note 解释检查范围及证据限制。
""" + PROTOCOL_PROMPT

_MATERIAL_SYSTEM = _SYSTEM + """
【本次材料交付方式】
使用本次 schema 输出一个 JSON 对象，不调用工具，不输出 JSON 以外的说明。
本次没有取证工具。dossier_view 是已经交付的记录正文；shared_ref 指向同一视图 shared_contents 中的正文，递归展开后阅读。
record.id 是引用编号，fields 是该记录已交付字段。请从 reference_catalog 选择引用编号，不自行拼接 /result、/tool_args 等路径。
source_to_evidence 把期望来源 ID 映射为本批已交付的候选证据 ID；只有读到对应记录正文才能把它作为 source_refs/input_refs/output_refs。来源 ID 本身不自动等于证据 ID。
要定位具体字段，在 observed 中写 record.id、字段名及原文事实；input_refs/output_refs 仍填 catalog 中的记录 ID。
关联编号不证明关联对象正文已经交付。missing_endpoints 是未记录或不可用端点，gaps 是采集缺口；它们不等于业务未执行。
coverage_remaining 是本轴尚未覆盖的承诺期望 ID；coverage_required 本批必须核对，coverage_available 可在适用单位核对。不能用空泛总评代替逐项检查。
"""


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


def _expand(groups: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for group in groups:
        if (group.get("problems") or group.get("upstream_issue_ids")) and len(group["link_ids"]) != 1:
            raise ValueError("有问题或上游引用的单位必须按一次行使分开提交")
        for link_id in group["link_ids"]:
            out.append({"obligation_id": group["obligation_id"], "link_id": link_id, "outcome": group["outcome"],
                        "expectation_ids": list(group["expectation_ids"]),
                        "matched_link_id": group["matched_link_id"],
                        "expectation_checks": list(group["expectation_checks"]),
                        "observed": group["observed"],
                        "source_refs": list(group["source_refs"]),
                        "evidence": {"input": list(group["input_refs"]), "output": list(group["output_refs"])},
                        "missing": list(group["missing"]), "judged_by": "llm",
                        "problems": [dict(p) for p in group.get("problems", [])],
                        "upstream_issue_ids": list(group.get("upstream_issue_ids", [])),
                        "origin": group.get("origin", "runtime_recall")})
    return out


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


def validate_result_evidence(results, obligations, links, readable):
    """An evaluator's unsupported claim is a format/protocol error, not business missing evidence."""
    for r in results:
        refs = r['source_refs'] + r['evidence']['input'] + r['evidence']['output']
        for p in r.get('problems', []):
            refs += p['source_refs'] + p['input_refs'] + p['output_refs']
        unknown = [ref for ref in refs if ref not in readable and not _special_ref(ref)]
        if unknown:
            raise ValueError(f'引用未交付正文：{unknown}')
        for ref in refs:
            if ref.startswith('obligation:') and ref.removeprefix('obligation:') != r['obligation_id']:
                raise ValueError('通用义务引用必须指向本单位的义务')
        if r['outcome'] in {'pass', 'not_applicable', 'fail', 'input_invalid'} and not any(r['evidence'].values()):
            raise ValueError('结论没有 trace 引用')
        link = links.get(r['link_id'], {})
        if link.get('origin') == 'expectation_deduction' and not r.get('matched_link_id'):
            if r['outcome'] not in {'input_invalid', 'insufficient_evidence', 'contract_missing'} and r['obligation_id'] not in {'reference_resolution', 'ambiguity', 'constraints'}:
                raise ValueError('应发生而未发生的单位不能判正常或不适用')
        if r['outcome'] in {'pass', 'fail'} and obligations[r['obligation_id']].source in {'trace', 'case'} and not r['source_refs']:
            raise ValueError('结论缺少判准出处')


def _special_ref(ref: str) -> bool:
    return ref == CASE_REF or ref.startswith(PROJECT_REF_PREFIX) or ref.startswith("obligation:") or ref.startswith("expectation:")


def annotate(results: list[dict[str, Any]], obligations: Mapping[str, Obligation],
             links: Mapping[str, Mapping[str, Any]], ids: set[str], scope_note: str) -> set[str]:
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
        if r["outcome"] in {"pass", "not_applicable"} and (not cited or not scope_note.strip()):
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
             scope_note: str, coverage: Mapping[str, Any], usage: dict[str, Any], *, axis_id: str, criterion: str = "") -> RunOutcome:
    issues = issues_for(axis_id, results)
    from ...process_loop.expectation_projection import coalesce
    results = coalesce(results)
    parts = composition(results)
    labels = dict(zip(OUTCOMES, ("做到", "没做到", "缺证", "输入无效", "未发生", "缺判准")))
    composition_note = "；组成：" + "、".join(f"{labels[key]} {count}" for key, count in parts['counts'].items())
    verdict, rule = aggregate_verdict(results)
    missing = list(dict.fromkeys(m for r in results for m in r["missing"]))
    contract_missing = [{"obligation_id": r["obligation_id"], "link_id": r["link_id"], "expected": r["expected"]}
                        for r in results if r["outcome"] == "contract_missing"]
    refs = {ref for r in results for ref in r["evidence"]["input"] + r["evidence"]["output"] + r["source_refs"]}
    return RunOutcome(
        output={
            "assessment": {"verdict": verdict, "reason": reason, "verdict_rule": rule, "scope_note": scope_note,
                           "gaps": missing, "contract_missing": contract_missing, "composition": parts, "criterion": criterion},
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

    if is_transcript(inputs["trace_analysis"]["dossier"]):
        return run_axis(axis_id, inputs, axis, runtime, spec)
    analysis = inputs["trace_analysis"]
    dossier = analysis["dossier"]
    coverage = analysis.get("coverage") or {}
    structure = analysis.get("structure") or {}
    selection = (analysis.get("selections") or {}).get(axis_id) or {}
    if "materials" in selection and not selection["materials"]:
        raise ValueError("分析轴未交付的环节材料")
    from ...process_loop.expectation_projection import prepare, required_units, contracts_for, bind_results, validate_contract_coverage, validate_dossier_expectations, CONSUMER_PROMPT
    expectations = inputs['expectations']
    client = axis_llm(runtime.spec, role="judge")
    if not runtime.expectation_projection:
        runtime.expectation_projection.update(prepare(expectations, client, runtime.trace_id))
    projection = runtime.expectation_projection
    required = required_units(axis_id, expectations, projection)
    runtime_links = _axis_links(axis_id, dossier, structure)
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
    active_batches = [i for i, b in enumerate(batches, 1)
                      if any(link['link_id'] == ident for link in b['links'] for _, ident in pending)]
    contract_ids = {c['expectation_id'] for c in projection['contracts'] if axis_id in c['axes']}
    if contract_ids and not active_batches:
        raise ValueError(f'{axis_id}: 本轴有承诺侧期望但没有可评测材料批次：{sorted(contract_ids)}')
    expectations_by_id = {e['expectation_id']: e for e in expectations['expectations']}
    sources_by_id = {s['id']: s for s in expectations['sources']}
    batch_reads = {i: {str(row['id']) for row in batches[i - 1]['view']['reads']} for i in active_batches}
    assignments: dict[int, list[str]] = {i: [] for i in active_batches}
    for ident in sorted(contract_ids):
        source_records = {str(ref) for sid in expectations_by_id[ident]['source_refs']
                          for ref in sources_by_id[sid].get('trace_refs', [])}
        choices = sorted(active_batches, key=lambda i: (-len(batch_reads[i] & source_records), len(assignments[i]), i))
        assignments[choices[0]].append(ident)
    output_spec = StructuredOutputSpec.from_dataclass(
        ProcessAssessment, required_nonempty=["reason", "scope_note"],
        description="pending 中每一对（obligation_id, link_id）恰好出现一次；fail 写两端证据；insufficient_evidence 必填 missing。",
    )
    llm_results, reasons, scopes, repaired, reads = [], [], [], [], []
    unverified: set[str] = set()
    batch_audit = []
    for number, batch in enumerate(batches, 1):
        batch_ids = {link["link_id"] for link in batch["links"]}
        batch_pending = [pair for pair in pending if pair[1] in batch_ids]
        if not batch_pending:
            continue
        view = batch["view"]
        batch_required = [u for u in required if u['link_id'] in batch_ids]
        if batch_required:
            turns = {u['turn'].replace('t', 'turn', 1) for u in batch_required}
            candidates = [l for l in runtime_links if l.get('turn') in turns or any(u['turn'] == 'case' for u in batch_required)]
            view = material_view(dossier, batch['links'] + candidates, list(structure.get('suspects') or []),
                                 extra_refs=list(selection.get('refs') or []))
        else:
            candidates = []
        pending_by_ob: dict[str, list[str]] = {}
        for ob_id, link_id in batch_pending:
            pending_by_ob.setdefault(ob_id, []).append(link_id)
        covered = {ident for result in llm_results for ident in result['expectation_ids']}
        remaining = sorted(contract_ids - covered)
        assigned = assignments[number]
        reference_catalog = {
            'records': [{'id': row['id'], 'fields': list(row.get('fields', {}))}
                        for row in model_material(view).get('records', [])],
            'readable_ids': sorted({str(row['id']) for row in view['reads']}),
            'gap_ids': [gap['id'] for gap in view.get('gaps', [])],
            'criterion_refs': ['case'] + ['obligation:' + ob for ob in pending_by_ob]
                             + ['expectation:' + e['expectation_id'] for e in contracts_for(axis_id, expectations, projection)],
        }
        readable_ids = set(reference_catalog['readable_ids'])
        source_to_evidence = {source['id']: [ref for ref in source.get('trace_refs', []) if ref in readable_ids]
                              for source in expectations['sources']}
        user = json.dumps({
            "expectations": contracts_for(axis_id, expectations, projection),
            "expectation_sources": expectations['sources'],
            "source_to_evidence": source_to_evidence,
            "expectation_units": [u for u in required if u['link_id'] in batch_ids],
            "coverage_remaining": remaining,
            "coverage_required": assigned,
            "coverage_available": remaining,
            "reference_catalog": reference_catalog,
            "dimension": axis_id, "dimension_question": spec.question, "dimension_excludes": spec.excludes,
            "scenario_criterion": criterion_text(expand_material_uris(axis.description)),
            "recorded_issues": list(getattr(runtime, "process_issues", {}).values()),
            "obligations": [{"obligation_id": ob.obligation_id, "link_type": ob.link_type, "situation": ob.situation,
                             "duty": ob.duty, "source": ob.source} for ob in obligations if ob.obligation_id in pending_by_ob],
            "pending": pending_by_ob,
            "program_results": [{k: r[k] for k in ("obligation_id", "link_id", "outcome", "observed")}
                                for r in decided.values() if r["link_id"] in batch_ids],
            "links": {"limits": LIMITS, "links": batch["links"], "match_candidates": candidates},
            "suspects_for_this_axis": selection.get("why") or [],
            "dossier_view": model_material(view),
        }, ensure_ascii=False, default=str)

        def ask(prompt: str) -> tuple[list[dict[str, Any]], str, str, list[str]]:
            runtime.ensure_time_left(axis_id)
            payload = client.complete_json(_MATERIAL_SYSTEM + CONSUMER_PROMPT, prompt, trace_id=runtime.trace_id,
                                          stage=f"llm_probe_process_{axis_id}_batch{number}", reasoning_effort="low",
                                          output_spec=output_spec)
            raise_for_error_payload(payload)
            if isinstance(payload, Mapping):
                payload = {k: v for k, v in payload.items() if k not in {"raw_model_response", "metrics", "_tool_call_log"}}
            enforce_output(payload, output_spec, caller=axis_id)
            results = _expand(payload["results"])
            check_coverage(results, batch_pending)
            for result in results:
                if by_link[result["link_id"]].get("origin") == "expectation_deduction":
                    result["origin"] = "expectation_deduction"
            bind_results(results, by_ob, expectations,
                         [u for u in required if u['link_id'] in batch_ids],
                         runtime_links={l['link_id']: l for l in runtime_links})
            validate_dossier_expectations(results, by_ob, expectations, by_link, dossier)
            validate_units(results, axis_id)
            validate_result_evidence(results, by_ob, by_link,
                {str(r["id"]) for r in view["reads"]} | {str(g["id"]) for g in view.get("gaps", [])})
            covered_here = {ident for result in results for ident in result['expectation_ids']}
            if set(assigned) - covered_here:
                raise ValueError(f'本批承诺侧期望未核对：{sorted(set(assigned) - covered_here)}；条件不成立也须说明，不能静默漏判')
            return results, payload["reason"], payload["scope_note"], []

        try:
            results, reason, scope_note, notes = ask(user)
        except ValueError as exc:
            # One format retry. A second invalid response remains a run error.
            results, reason, scope_note, notes = ask(
                user + "\n上次输出格式错误，请按原任务重新输出 JSON：" + str(exc))
        readable = {str(r["id"]) for r in view["reads"]} | {str(g["id"]) for g in view.get("gaps", [])}
        unverified.update(annotate(results, by_ob, by_link, readable, scope_note))
        for result in results:
            cited = result["source_refs"] + result["evidence"]["input"] + result["evidence"]["output"]
            unread = [ref for ref in cited if ref not in readable and not _special_ref(ref)]
            if unread and result["outcome"] in {"pass", "not_applicable"}:
                result["outcome"] = "insufficient_evidence"
                result["missing"] = result["missing"] or [f"正面结论引用未交付正文：{unread}"]

        llm_results.extend(results)
        reasons.append(reason)
        scopes.append(scope_note)
        repaired.extend(notes)
        reads.extend(view["reads"])
        batch_audit.append({"number": number, "link_ids": sorted(batch_ids), "chars": batch["chars"],
                            "prompt_chars": len(user), "oversize": batch["oversize"],
                            "missing_endpoints": view["missing_endpoints"]})
    check_coverage(llm_results, pending)
    validate_contract_coverage(llm_results, axis_id, projection)
    reason = "；".join(reasons) if reasons else "本轴全部义务由程序按机器事实判定"
    scope_note = "；".join(scopes) if scopes else "程序判定：" + "、".join(by_link)
    judged = {(r["obligation_id"], r["link_id"]): r for r in llm_results}
    judged.update(decided)
    ordered = [judged[(ob.obligation_id, link["link_id"])]
               for link in links for ob in obligations if (ob.obligation_id, link["link_id"]) in judged]
    for r in ordered:
        r.setdefault("flags", [])
    if repaired:
        scope_note = f"{scope_note}（程序修复输出结构：{'；'.join(repaired[:6])}）"
    outcome = _outcome(ordered, by_ob, reason, scope_note, coverage, {**client.usage(), "tool_calls": 0}, axis_id=axis_id, criterion=expand_material_uris(axis.description))
    why = selection.get("why") or []
    outcome.output["selection"] = {"refs": list(selection.get("refs") or []),
                                   "why": [why] if isinstance(why, str) else list(why)}
    outcome.output["view"] = {"chars": sum(b["chars"] for b in batch_audit),
                              "records": len({r["id"] for b in batches for r in b["view"]["records"]}),
                              "excluded": [], "unverified_refs": sorted(unverified), "repaired": repaired,
                              "batches": batch_audit,
                              "evidence_audit": {"reads": reads, "calls": 0, "budget": 0,
                                                 "delivery": "analysis_materials"}}

    return outcome


PROCESS_SPECS: dict[str, AxisSpec] = {}


def axis_type(type_id: str, title: str, summary: str, spec: AxisSpec) -> Any:
    from ..types import AxisType, Dependency, ExecutionLimits, Field, Input, Verdict

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
        scenario_fields=(Field("description", required=True, expand="prompt_load"),),
        limits=ExecutionLimits(tool_calls=PROCESS_TOOL_CALL_LIMIT, seconds=1200),
        run=lambda inputs, axis, runtime: run_process_axis(type_id, inputs, axis, runtime, spec),
        verdict_path="assessment.verdict", requires_business_trace=True,
        implementation_files=(f"impl/projects/llm_probe/eval_axes/adapters/{type_id}.py",
                              "impl/projects/llm_probe/eval_axes/adapters/process_common.py",
                              "impl/projects/llm_probe/eval_axes/adapters/process_protocol.py",
                              "impl/projects/llm_probe/process_loop/expectation_projection.py",
                              "impl/projects/llm_probe/eval_axes/adapters/expectations.py",
                              "impl/projects/llm_probe/business_trace/expectation_material.py",
                              "impl/projects/llm_probe/eval_axes/adapters/trace_analysis.py",
                              "impl/projects/llm_probe/business_trace/dossier.py",
                              "impl/projects/llm_probe/business_trace/materials.py",
                              "impl/projects/llm_probe/business_trace/links.py",
                              "impl/projects/llm_probe/business_trace/tools.py",
                              "impl/projects/llm_probe/eval_axes/adapters/transcript_axes.py",
                              "impl/projects/llm_probe/business_trace/providers/llmtracing_transcript.py"),
    )
