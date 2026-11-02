"""轴类型清单：来自轴定义存储（spec/alg/axis_loop.md §3），给资料页下拉、表格视图与场景校验用。

与 llm_probe 的 eval_axes.registry 同名同用法（service、table_view、capability 按项目名取这里）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from impl.core.axis_loop.definitions import AxisDef, Definitions, load

PROJECT = "llm_probe_loop"


@dataclass(frozen=True)
class AxisInfo:
    type_id: str
    title: str
    role: str
    axis: AxisDef

    @property
    def requires_business_trace(self) -> bool:
        """白名单读 trace 存档（case.trace）的轴。"""
        return any(m == "case.trace" or m.startswith("case.trace.") for m in self.axis.materials)

    def describe(self) -> dict[str, Any]:
        """与 llm_probe 的类型声明同形（资料页 / live 页按 type_id 取）：说明正文第一句当 summary；
        场景描述框：模型执行的轴都有（本轴描述槽位，spec/alg/axis_loop.md §2.5），程序执行的没有。"""
        a = self.axis
        summary = re.split(r"(?<=[。！？])", a.instruction.strip(), maxsplit=1)[0].strip()
        return {"type_id": self.type_id, "title": self.title, "summary": summary, "role": self.role,
                "executor": a.executor, "loop": a.loop,
                "verdict_scope": "item" if a.submit == "per_item" else "case",
                "verdict_enum": [{"value": v} for v in a.verdict_values],
                "depend_on": [{"type_id": d.axis, "optional": not d.hard} for d in a.depends],
                "trigger_when": {"axis": a.trigger.axis, "verdict_in": list(a.trigger.verdict_in)} if a.trigger else None,
                "inputs": [{"source": m} for m in a.materials],
                "scenario_fields": [{"name": "description", "required": False}] if not a.automatic else [],
                "requires_business_trace": self.requires_business_trace}


def definitions() -> Definitions:
    return load(PROJECT)


def axis_types() -> Mapping[str, AxisInfo]:
    return {key: AxisInfo(key, axis.title, axis.role, axis) for key, axis in definitions().axes.items()}


class _Lazy(Mapping):
    """AXIS_TYPES：每次读都按当前存储算（页面改了定义不用重启）。"""

    def __getitem__(self, key):
        return axis_types()[key]

    def __iter__(self):
        return iter(axis_types())

    def __len__(self):
        return len(axis_types())


AXIS_TYPES: Mapping[str, AxisInfo] = _Lazy()


def describe_axis_types() -> list[dict[str, Any]]:
    return [info.describe() for info in axis_types().values()]
