"""调用链路分析工具。

这些工具只从运行时 trace 中提取通用结构化信号。项目节点到源码、配置、
业务术语的解释应由项目 adapter / project.yaml / protocol extensions 提供，
不要在 core 中硬编码项目事实。
"""

from __future__ import annotations
from typing import Dict, List, Any

from .schema import ExecutionTraceEvent


_RUNTIME_SIGNAL_KEYS = {
    "intent",
    "raw_intent",
    "confidence",
    "slots",
    "entities",
    "label",
    "status",
    "code",
    "message",
}


def _event_dict(step: ExecutionTraceEvent | Dict[str, Any] | Any) -> Dict[str, Any]:
    if isinstance(step, dict):
        return step
    if isinstance(step, ExecutionTraceEvent):
        return step.__dict__
    return getattr(step, "__dict__", {}) or {}


def _collect_runtime_values(step_data: Dict[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for container_key in ("output", "outputs", "actual", "evidence"):
        payload = step_data.get(container_key)
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if key in _RUNTIME_SIGNAL_KEYS or key.startswith(("raw_", "mapped_", "actual_", "expected_")):
                values[key] = value
    return values


def analyze_execution_trace(trace: List[ExecutionTraceEvent]) -> Dict[str, Any]:
    """解析 execution_trace，返回通用链路信号。

    返回值只描述当前 trace 中已经存在的节点、状态、runtime value 和第一个失败点；
    不在 core 中推断项目专属源码位置或业务枚举含义。
    """
    if not trace:
        return {"error": "Empty trace", "first_failed_node": None}

    first_failed = None
    divergence_chain = []
    runtime_values: Dict[str, Any] = {}

    for step in trace:
        step_data = _event_dict(step)
        node_name = step_data.get("stage") or step_data.get("node") or "unknown"
        status = step_data.get("status", "unknown")

        divergence_chain.append({"node": node_name, "status": status})
        runtime_values.update(_collect_runtime_values(step_data))

        if not first_failed and status in {"failed", "diverged", "error"}:
            first_failed = {
                "name": node_name,
                "stage": step_data.get("stage", node_name),
                "status": status,
                "expected": step_data.get("expected") or (step_data.get("inputs") or {}).get("expected"),
                "actual": step_data.get("actual") or (step_data.get("outputs") or {}).get("actual"),
                "evidence": step_data.get("evidence", ""),
            }

    suggested_probes = []
    if first_failed:
        suggested_probes.append(f"检查节点 {first_failed['name']} 的输入、输出和本地实现证据。")
        if runtime_values:
            suggested_probes.append("复核 runtime_values 中实际值与 judge 期望值的差异。")

    return {
        "first_failed_node": first_failed,
        "divergence_chain": divergence_chain,
        "runtime_values": runtime_values,
        "suggested_probes": suggested_probes,
    }


def map_trace_node_to_source(node_name: str, project_type: str) -> Dict[str, Any]:
    """返回通用节点源码映射占位。

    Core 不维护项目节点到源码/配置的静态映射。调用方应优先使用项目 adapter
    暴露的 source_config_paths、ProjectSpec.documents / application / endpoint_discovery，
    或 trace.project_fields 中的 schema_protocol_extensions。
    """
    return {
        "source_files": [],
        "config_files": [],
        "key_functions": [],
        "description": "项目节点源码映射未在 core 中声明；请读取项目侧 source evidence。",
        "node": node_name,
        "project": project_type,
    }


def get_runtime_value_analysis(key: str, value: Any, context: Dict) -> str:
    """以通用方式描述运行时值，避免在 core 中注入项目术语。"""
    if key == "confidence":
        threshold = context.get("min_confidence", 0.7)
        return (
            f"confidence={value}，阈值要求 >={threshold}。"
            f"{'低于阈值，可能导致下游拒绝' if value < threshold else '满足阈值要求'}"
        )
    if key.startswith("raw_"):
        return f"{key}={value}，这是上游原始值；需由项目侧映射/解析规则解释。"
    if key.startswith("mapped_") or key in {"intent", "label"}:
        return f"{key}={value}，这是项目侧归一化后的值；需与 judge 期望对照。"
    return f"{key}={value}"
