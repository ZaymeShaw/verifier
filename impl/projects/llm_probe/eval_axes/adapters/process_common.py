"""过程六轴的轴定义与入口（spec/alg/process-axes.md）。

每个轴：评什么（需求 §1.1 的部件「输入 → 输出」）、本轴不判什么、子能力提纲；判法在 process_expected.py。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from impl.projects.llm_probe.business_trace.links import AXIS_LINK_TYPES, LINK_TYPES, build_links
from ..types import RunOutcome, ScenarioAxis

PROCESS_TOOL_CALL_LIMIT = 3


@dataclass(frozen=True)
class Subcapability:
    """一项子能力（spec/alg/process-axes.md §8）：本应清单的写作提纲，不是判定单位。"""
    name: str
    when: str   # 什么时候用到这项能力
    duty: str   # 用到时，做对必须成立什么


@dataclass(frozen=True)
class AxisSpec:
    question: str
    excludes: str
    subcapabilities: tuple[Subcapability, ...]
    # 需求说明：本轴写给整理员的，业务语言、不含案卷结构等实现细节。
    requires: str = ""


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


def project_subcapabilities(entry: Mapping[str, Any] | None, axis_id: str) -> tuple[Subcapability, ...]:
    """场景条目 process_obligations：trace 里读不到、又需要判的约定，每条经用户确认，作为本轴额外的子能力。"""
    types = AXIS_LINK_TYPES[axis_id]
    out = []
    for item in (entry or {}).get("process_obligations") or []:
        if item["link_type"] not in LINK_TYPES:
            raise ValueError(f"process_obligations.{item['id']}.link_type {item['link_type']!r} 不是环节类型 {list(LINK_TYPES)}")
        if item["link_type"] in types:
            out.append(Subcapability(f"项目声明（{item['confirmed']} 确认）：{item.get('label') or item['id']}",
                                     item["situation"], item["duty"]))
    return tuple(out)


def _scenario_entry(runtime: Any) -> Mapping[str, Any] | None:
    from impl.core.capability_store import load_capability_map

    entry = load_capability_map(runtime.spec.project_id).get(runtime.scenario_id)
    return entry if isinstance(entry, Mapping) else None


def run_process_axis(axis_id: str, inputs: Mapping[str, Any], axis: ScenarioAxis,
                     runtime: Any, spec: AxisSpec) -> RunOutcome:
    """一轴的入口。对话稿案卷（llmtracing）没有环节表与材料切分，本应 / 实际判法暂不支持，记评测运行错误。"""
    # 分析轴成功才会发动本轴（depend_on），案卷必然存在；没有案卷时分析轴已 failed，本轴 blocked。
    from .transcript_axes import is_transcript
    from .process_expected import run_expected_axis

    if is_transcript(inputs["trace_analysis"]["dossier"]):
        return RunOutcome(output={}, failed=True,
                          failure_reason="过程六轴暂不支持对话稿案卷（llmtracing）：没有环节表与输入 / 输出端材料切分")
    return run_expected_axis(axis_id, inputs, axis, runtime, spec)


PROCESS_SPECS: dict[str, AxisSpec] = {}


def axis_type(type_id: str, title: str, summary: str, spec: AxisSpec) -> Any:
    from ..types import AxisType, Dependency, ExecutionLimits, Input, Verdict

    if not spec.subcapabilities:
        raise ValueError(f"{type_id} 没有子能力提纲")
    PROCESS_SPECS[type_id] = spec
    return AxisType(
        type_id=type_id, title=title, summary=summary, verdict_scope="axis",
        verdict_enum=(Verdict("sound", "已核实范围内没问题；须同时查看组成与未覆盖范围"),
                      Verdict("problematic", "有归到本轴的问题"),
                      Verdict("not_evaluable", "有无法核的条目，或问题归因未定位"),
                      Verdict("untested", "输入全坏：本应用到，但每次输入都已被上游弄坏；须修上游"),
                      Verdict("not_applicable", "本次不需要这项能力")),
        depend_on=(Dependency("expectations"), Dependency("trace_analysis"),),
        trigger_when=None,
        inputs=(Input("trace_analysis", source="axis.trace_analysis.output",
                      fields=["verdict", "dossier", "coverage", "structure", "selections"]),
                Input("expectations", source="axis.expectations.output",
                      fields=("verdict", "expectations", "sources", "missing", "material_sha256", "sha256")),),
        output_fields=("assessment", "results", "issues", "unexpected", "evidence_refs", "missing_evidence",
                       "selection", "view"),
        scenario_fields=(),
        limits=ExecutionLimits(tool_calls=PROCESS_TOOL_CALL_LIMIT, seconds=1200),
        run=lambda inputs, axis, runtime: run_process_axis(type_id, inputs, axis, runtime, spec),
        verdict_path="assessment.verdict", requires_business_trace=True,
        implementation_files=(f"impl/projects/llm_probe/eval_axes/adapters/{type_id}.py",
                              "impl/projects/llm_probe/eval_axes/adapters/process_common.py",
                              "impl/projects/llm_probe/eval_axes/adapters/process_expected.py",
                              "impl/projects/llm_probe/eval_axes/adapters/expectations.py",
                              "impl/projects/llm_probe/business_trace/expectation_material.py",
                              "impl/projects/llm_probe/eval_axes/adapters/trace_analysis.py",
                              "impl/projects/llm_probe/business_trace/dossier.py",
                              "impl/projects/llm_probe/business_trace/materials.py",
                              "impl/projects/llm_probe/business_trace/links.py"),
    )
