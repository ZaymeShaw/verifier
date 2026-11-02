"""视图：校验与合成代码的唯一输入，只读（spec/alg/axis_loop.md §7.1）。

只放白名单里的材料（按标准名给值：保留原结构，只应用元素筛选）、本次提交、本次调用参数、此前批次的调用、
分发出去的各份结果。
代码拿不到白名单以外的东西：依赖关系不能在代码里偷偷长出来（demand/axis_loop.md §3.4.3）。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class CallView:
    call_id: str
    tool: str
    category: str      # 信息源类别（knowledge / trace）；子 loop 调用为 "subloop"；其余为空
    args: Mapping[str, Any]
    batch: int
    text: str          # 模型看到的返回（序列化后）
    structured: Any    # 结构化结果（MCP structuredContent / 子 loop 被接受的结果）；没有为 None
    is_error: bool


@dataclass(frozen=True)
class TaskView:
    task_id: str
    own: Mapping[str, Any]                       # 本次提交里模型填的部分；分条交收尾时含全部已接受分项
    materials: Mapping[str, Any]                 # {标准名: 完整值}，只含白名单里出现的名字
    params: Mapping[str, Any] = field(default_factory=dict)   # 被调用的 loop：本次调用参数；分发：{tasks: 这个 loop 启用的任务}
    calls: Sequence[CallView] = ()               # 此前批次的调用
    stage: str = "final"                         # item：校验一个分项；final：收尾
    parts: Sequence[Mapping[str, Any]] = ()      # 仅有分发的轴的合成：[{id, result}]，各份被接受的结果

    def call(self, call_id: str) -> Optional[CallView]:
        return next((c for c in self.calls if c.call_id == call_id), None)
