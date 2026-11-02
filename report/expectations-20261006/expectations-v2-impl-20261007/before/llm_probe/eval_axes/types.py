"""扩展评估轴的核心对象（spec/adapter/axe-v4.md §1–§3、§6）。"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

VERDICT_SCOPE_AXIS = "axis"
VERDICT_SCOPE_ITEM = "item"
VERDICT_SCOPES = (VERDICT_SCOPE_AXIS, VERDICT_SCOPE_ITEM)

# evaluation=用户面评测维度；analysis=内部分析轴（被评测轴依赖时自动启用，不当独立维度配置/展示）
ROLE_EVALUATION = "evaluation"
ROLE_ANALYSIS = "analysis"
AXIS_ROLES = (ROLE_EVALUATION, ROLE_ANALYSIS)

STATUS_DISABLED = "disabled"
STATUS_BLOCKED = "blocked"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUSES = (
    STATUS_DISABLED,
    STATUS_BLOCKED,
    STATUS_NOT_APPLICABLE,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
)

# failed 的原因分三类，写在 error 开头，导出表里直接可筛：
# 运行环境（端点/限流/超时，重跑可能恢复）、轴实现（轴本身产不出合格结果，要改轴）、需补材料（需用户支持补采集/授权）。
FAILURE_ENVIRONMENT = "[运行环境]"
FAILURE_AXIS = "[轴实现]"
FAILURE_MATERIAL = "[需补材料]"
FAILURE_KINDS = (FAILURE_ENVIRONMENT, FAILURE_AXIS, FAILURE_MATERIAL)

SOURCE_SAMPLE = "sample"
SOURCE_AXIS = "axis"

EXPAND_PROMPT_LOAD = "prompt_load"
EXPAND_CATALOG = "catalog"
EXPAND_MODES = (EXPAND_PROMPT_LOAD, EXPAND_CATALOG)

TYPE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_SAMPLE_SOURCE = re.compile(r"^sample\.(trace|business_trace|requirements)$")
_AXIS_SOURCE = re.compile(r"^axis\.([a-z][a-z0-9_]*)\.output$")


@dataclass(frozen=True)
class Verdict:
    value: str
    description: str


@dataclass(frozen=True)
class Dependency:
    type_id: str
    optional: bool = False

    def __post_init__(self) -> None:
        if not TYPE_ID_PATTERN.fullmatch(self.type_id):
            raise ValueError(f"非法依赖类型: {self.type_id!r}")


@dataclass(frozen=True)
class Input:
    """一个输入槽位：adapter 收到的 inputs[name] 从哪来。

    source 只有两种形态：
    - ``sample.trace``：整份 RunTrace；
    - ``sample.business_trace``：同一 RunTrace 中固化的业务 Trace 快照；
    - ``axis.<type_id>.output``：上游轴 output 的**具名字段**（fields 必填），
      运行器只投影这些字段，不给整份结果，更不给 trace。
    """

    name: str
    source: str
    fields: tuple[str, ...] = ()
    required: bool = True

    def __post_init__(self) -> None:
        if _SAMPLE_SOURCE.fullmatch(self.source):
            if self.fields:
                raise ValueError(f"Input {self.name}: sample 来源不支持 fields 投影")
            return
        if _AXIS_SOURCE.fullmatch(self.source):
            if not self.fields:
                raise ValueError(
                    f"Input {self.name}: axis 来源必须声明 fields（只投影具名字段，不给整份 output）"
                )
            return
        raise ValueError(
            f"Input {self.name}: source 只能是 sample.trace、sample.business_trace、sample.requirements 或 axis.<type_id>.output，得到 {self.source!r}"
        )

    @property
    def kind(self) -> str:
        return SOURCE_SAMPLE if self.source.startswith("sample.") else SOURCE_AXIS

    @property
    def axis_ref(self) -> str:
        match = _AXIS_SOURCE.fullmatch(self.source)
        return match.group(1) if match else ""

    @property
    def sample_field(self) -> str:
        match = _SAMPLE_SOURCE.fullmatch(self.source)
        return match.group(1) if match else ""


@dataclass(frozen=True)
class When:
    """样本筛选条件。首版只有一种形态：上游轴（axis 级）的 verdict 落在集合内。"""

    axis: str
    verdict_in: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.verdict_in:
            raise ValueError("When.verdict_in 不能为空")


@dataclass(frozen=True)
class Field:
    """场景层可填的字段。首版只有 description。expand 决定资料引用怎么展开。"""

    name: str
    required: bool = True
    expand: str = EXPAND_PROMPT_LOAD

    def __post_init__(self) -> None:
        if self.expand not in EXPAND_MODES:
            raise ValueError(f"Field {self.name}: expand 只能是 {EXPAND_MODES}，得到 {self.expand!r}")


@dataclass(frozen=True)
class ExecutionLimits:
    """tool_calls 由现有 tool_call_limit 硬限（v4 D8）；seconds 是协作式墙钟上限：运行器把截止时刻
    交给 run()，adapter 在每次 LLM 调用之间查 runtime.ensure_time_left()，到点就停止开新的调用并报失败。
    不强杀线程——一次 LLM 调用最长受 llm.request_timeout_seconds 约束。
    llm_calls 由接入轮次预算的 ToolLoop 执行；其他 adapter 仍须自行落实声明的上限。"""

    llm_calls: Optional[int] = None
    tool_calls: Optional[int] = None
    seconds: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return {"llm_calls": self.llm_calls, "tool_calls": self.tool_calls, "seconds": self.seconds}


@dataclass(frozen=True)
class ScenarioAxis:
    """场景轴 = 预设 axes[] 里的一个框。"""

    type_id: str
    enabled: bool
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type_id, "enabled": self.enabled, "description": self.description}


@dataclass
class AxisRuntime:
    """运行器交给 run() 的环境：spec、本次试验标识、本轴截止时刻。LLM 调用统一挂在 trace_id 下。"""

    spec: Any
    run_id: str
    trace_id: str
    scenario_id: str
    case_id: str
    deadline: Optional[float] = None  # time.monotonic() 时刻；None = 不限
    # 本场景启用的全部轴 type_id；分析轴据此知道谁在消费它、该往哪些方向探测
    enabled_axes: tuple[str, ...] = ()

    expectation_projection: dict[str, Any] = field(default_factory=dict)

    process_issues: dict[str, Any] = field(default_factory=dict)

    def ensure_time_left(self, about: str = "") -> None:
        """adapter 在开下一次 LLM 调用前调用；超过本轴 seconds 上限即抛 AxisTimeout。"""
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise AxisTimeout("超出本轴时间上限，未再开始新的调用" + (f"（{about}）" if about else ""))


class AxisTimeout(RuntimeError):
    """协作式超时：由 AxisRuntime.ensure_time_left 抛出，运行器记为 failed。"""


class AxisRequestFailed(RuntimeError):
    """请求层失败：complete_json 对鉴权/限流/网络等请求错误返回 {"error", "raw_text"} 而不抛异常。

    由 adapter 经 raise_for_error_payload 抛出，运行器记为 failed 并在 usage 里带
    llm_error / llm_error_text；不进入格式重试 / salvage（那是模型输出格式错误的通道）。
    """

    def __init__(self, error: str, raw_text: str = "") -> None:
        super().__init__(error)
        self.error = error
        self.raw_text = raw_text


def raise_for_error_payload(raw: Any) -> None:
    """complete_json 请求层失败返回 error dict（不抛异常）；把它当模型输出会伪装成格式错误。"""
    if isinstance(raw, Mapping) and "error" in raw:
        raise AxisRequestFailed(str(raw["error"]), str(raw.get("raw_text") or ""))


@dataclass
class AxisSummary:
    """一次判定的解释：一句话 + 逐格 items（每格 = 谁、判成什么枚举值、为什么）。

    怎么产出由 adapter 的 run() 决定——两个内置轴都是从判结论的同一次模型调用里提取
    （轴1 复用 summary_from_fulfillment，轴2 复用 carrier_text），不另调模型。
    """

    text: str
    items: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "items": [dict(item) for item in self.items]}


@dataclass
class RunOutcome:
    """run() 的返回：方法专属 output + 解释 + 是否没跑成 + 实际消耗。"""

    output: dict[str, Any]
    summary: Optional[AxisSummary] = None
    failed: bool = False
    failure_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


RunFn = Callable[[Mapping[str, Any], ScenarioAxis, AxisRuntime], RunOutcome]


@dataclass(frozen=True)
class AxisType:
    type_id: str
    title: str
    summary: str
    verdict_scope: str
    verdict_enum: tuple[Verdict, ...]
    depend_on: tuple[Dependency | str, ...]
    trigger_when: Optional[When]
    inputs: tuple[Input, ...]
    output_fields: tuple[str, ...]
    scenario_fields: tuple[Field, ...]
    limits: ExecutionLimits
    run: RunFn
    requires_business_trace: bool = False
    role: str = ROLE_EVALUATION
    # axis 级：output 里的点路径，如 overall_fulfillment.status
    verdict_path: str = ""
    # item 级：output 里的列表字段路径，如 placements[].placement
    item_path: str = ""
    # 参与 implementation_fingerprint 的源码文件（相对仓库根）
    implementation_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not TYPE_ID_PATTERN.fullmatch(self.type_id):
            raise ValueError(f"type_id 必须是小写标识符，得到 {self.type_id!r}")
        if self.verdict_scope not in VERDICT_SCOPES:
            raise ValueError(f"{self.type_id}: verdict_scope 只能是 {VERDICT_SCOPES}")
        if self.role not in AXIS_ROLES:
            raise ValueError(f"{self.type_id}: role 只能是 {AXIS_ROLES}")
        if not self.verdict_enum:
            raise ValueError(f"{self.type_id}: verdict_enum 不能为空")
        values = [item.value for item in self.verdict_enum]
        if len(values) != len(set(values)):
            raise ValueError(f"{self.type_id}: verdict_enum 有重复值")
        if self.verdict_scope == VERDICT_SCOPE_AXIS and not self.verdict_path:
            raise ValueError(f"{self.type_id}: axis 级类型必须声明 verdict_path")
        if self.verdict_scope == VERDICT_SCOPE_ITEM and not self.item_path:
            raise ValueError(f"{self.type_id}: item 级类型必须声明 item_path")
        if self.verdict_scope == VERDICT_SCOPE_ITEM and self.verdict_path:
            raise ValueError(f"{self.type_id}: item 级类型没有轴级 verdict，不得声明 verdict_path")
        dependencies = tuple(d if isinstance(d, Dependency) else Dependency(d) for d in self.depend_on)
        object.__setattr__(self, "depend_on", dependencies)
        dependency_ids = [d.type_id for d in dependencies]
        optional_ids = {d.type_id for d in dependencies if d.optional}
        for slot in self.inputs:
            if slot.axis_ref in optional_ids and slot.required:
                raise ValueError(f"{self.type_id}: 可选上游的 Input {slot.name} 必须 required=False")
        if self.trigger_when is not None and self.trigger_when.axis in optional_ids:
            raise ValueError(f"{self.type_id}: trigger_when 不得引用可选上游")
        if self.type_id in dependency_ids:
            raise ValueError(f"{self.type_id}: 不能依赖自己")
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError(f"{self.type_id}: depend_on 有重复")
        if not self.output_fields:
            raise ValueError(f"{self.type_id}: output_fields 不能为空")
        if len(self.output_fields) != len(set(self.output_fields)):
            raise ValueError(f"{self.type_id}: output_fields 有重复")
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.type_id}: inputs 名称有重复")
        referenced = {item.axis_ref for item in self.inputs if item.kind == SOURCE_AXIS}
        if self.trigger_when is not None:
            referenced.add(self.trigger_when.axis)
        missing = sorted(referenced - set(dependency_ids))
        if missing:
            raise ValueError(
                f"{self.type_id}: trigger_when / inputs 引用了 {missing}，但未出现在 depend_on 里"
            )
        if self.verdict_scope == VERDICT_SCOPE_ITEM and not re.fullmatch(
            r"[a-z_][a-z0-9_]*\[\]\.[a-z_][a-z0-9_]*", self.item_path
        ):
            raise ValueError(
                f"{self.type_id}: item_path 形如 <列表字段>[].<值字段>，得到 {self.item_path!r}"
            )
        if self.verdict_scope == VERDICT_SCOPE_ITEM:
            list_field = self.item_path.split("[]", 1)[0]
            if list_field not in self.output_fields:
                raise ValueError(f"{self.type_id}: item_path 的列表字段 {list_field} 不在 output_fields 里")
        if self.verdict_scope == VERDICT_SCOPE_AXIS:
            head = self.verdict_path.split(".", 1)[0]
            if head not in self.output_fields:
                raise ValueError(f"{self.type_id}: verdict_path 的首字段 {head} 不在 output_fields 里")

    @property
    def verdict_values(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.verdict_enum)

    def verdict_description(self, value: Any) -> str:
        for item in self.verdict_enum:
            if item.value == value:
                return item.description
        return ""

    def describe(self) -> dict[str, Any]:
        """给前端只读展示和 /api/eval_axes/types 用的类型声明。"""
        return {
            "type_id": self.type_id,
            "title": self.title,
            "summary": self.summary,
            "verdict_scope": self.verdict_scope,
            "verdict_enum": [{"value": v.value, "description": v.description} for v in self.verdict_enum],
            "depend_on": [{"type_id": d.type_id, "optional": d.optional} for d in self.depend_on],
            "trigger_when": (
                {"axis": self.trigger_when.axis, "verdict_in": list(self.trigger_when.verdict_in)}
                if self.trigger_when is not None else None
            ),
            "inputs": [
                {"name": i.name, "source": i.source, "fields": list(i.fields), "required": i.required}
                for i in self.inputs
            ],
            "output_fields": list(self.output_fields),
            "scenario_fields": [
                {"name": f.name, "required": f.required, "expand": f.expand} for f in self.scenario_fields
            ],
            "limits": self.limits.as_dict(),
            "verdict_path": self.verdict_path,
            "item_path": self.item_path,
            "requires_business_trace": self.requires_business_trace,
        }


@dataclass
class AxisResult:
    run_id: str
    case_id: str
    scenario_id: str
    axis_id: str
    type_id: str
    verdict_scope: str
    status: str
    title: str = ""
    verdict: Optional[str] = None
    verdict_description: str = ""
    # {"text": 一句话, "items": [{"key", "value", "reason", ...}]}；succeeded 时由 adapter 提供，
    # 其余状态由运行器填"为什么没发 / 为什么失败"。
    summary: dict[str, Any] = field(default_factory=dict)
    trigger_decision: dict[str, Any] = field(default_factory=dict)
    inputs_used: dict[str, Any] = field(default_factory=dict)
    output: Optional[dict[str, Any]] = None
    usage: dict[str, Any] = field(default_factory=dict)
    config_fingerprint: str = ""
    implementation_fingerprint: str = ""
    execution_trace_ref: str = ""
    started_at: str = ""
    finished_at: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "scenario_id": self.scenario_id,
            "axis_id": self.axis_id,
            "type_id": self.type_id,
            "verdict_scope": self.verdict_scope,
            "status": self.status,
            "title": self.title,
            "verdict": self.verdict,
            "verdict_description": self.verdict_description,
            "summary": dict(self.summary),
            "trigger_decision": dict(self.trigger_decision),
            "inputs_used": dict(self.inputs_used),
            "output": self.output,
            "usage": dict(self.usage),
            "config_fingerprint": self.config_fingerprint,
            "implementation_fingerprint": self.implementation_fingerprint,
            "execution_trace_ref": self.execution_trace_ref,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }
