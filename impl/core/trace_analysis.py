"""调用链路分析工具 - Issue #3 核心实施

这些工具让 attribute agent 可以"直接引用系统原函数"，而不是读大量源码文件。
"""

from __future__ import annotations
from typing import Optional, Dict, List, Any

from .schema import ExecutionTraceEvent


def analyze_execution_trace(trace: List[ExecutionTraceEvent]) -> Dict[str, Any]:
    """解析 execution_trace，直接返回关键分析结果

    这是用户要求的"直接引用系统原函数"的核心 - 不让 agent 读文件推测，
    而是直接从运行时数据中提取关键信息。

    Args:
        trace: RunTrace.execution_trace

    Returns:
        {
            "first_failed_node": {
                "name": "intent_api_call",
                "stage": "tier2_llm",
                "status": "diverged",
                "expected": {"intent": "nbev_planning"},
                "actual": {"intent": "other", "raw_intent": "4001"},
                "evidence": "LLM output 4001 mapped to 'other' instead of 'nbev_planning'"
            },
            "divergence_chain": [
                {"node": "request_normalization", "status": "ok"},
                {"node": "intent_api_call", "status": "diverged"},  # <-- 第一个失败点
                {"node": "label_mapping", "status": "diverged"}
            ],
            "runtime_values": {
                "raw_intent": "4001",
                "mapped_intent": "other",
                "confidence": 0.5
            },
            "suggested_probes": [
                "检查 intent mapping: 4001 → ?",
                "检查 intent 枚举: nbev_planning 的数值编码"
            ]
        }
    """
    if not trace:
        return {"error": "Empty trace", "first_failed_node": None}

    first_failed = None
    divergence_chain = []
    runtime_values = {}

    for step in trace:
        step_data = step.__dict__ if isinstance(step, ExecutionTraceEvent) else step
        node_name = step_data.get("stage") or step_data.get("node") or "unknown"
        status = step_data.get("status", "unknown")

        chain_entry = {"node": node_name, "status": status}
        divergence_chain.append(chain_entry)

        # 收集运行时实际值
        if step_data.get("output"):
            output = step_data["output"]
            if isinstance(output, dict):
                runtime_values.update({
                    k: v for k, v in output.items()
                    if k in ["raw_intent", "intent", "confidence", "slots", "entities"]
                })

        # 定位第一个失败点
        if not first_failed and status in ["failed", "diverged", "error"]:
            first_failed = {
                "name": node_name,
                "stage": step_data.get("stage", node_name),
                "status": status,
                "expected": step_data.get("expected"),
                "actual": step_data.get("actual"),
                "evidence": step_data.get("evidence", "")
            }

    # 基于分歧点生成建议的 probe 方向
    suggested_probes = []
    if first_failed and runtime_values:
        if "raw_intent" in runtime_values and "intent" in runtime_values:
            raw = runtime_values["raw_intent"]
            mapped = runtime_values["intent"]
            suggested_probes.append(f"检查 intent mapping 规则: {raw} 应该映射到什么？")
            if first_failed.get("expected"):
                expected_intent = first_failed["expected"].get("intent")
                if expected_intent and expected_intent != mapped:
                    suggested_probes.append(f"检查 {expected_intent} 的数值编码是否为 {raw}")

    return {
        "first_failed_node": first_failed,
        "divergence_chain": divergence_chain,
        "runtime_values": runtime_values,
        "suggested_probes": suggested_probes
    }


def map_trace_node_to_source(node_name: str, project_type: str) -> Dict[str, Any]:
    """将 trace node 名称映射到源码位置

    这避免了让 agent 读取大量源码去"理解"系统，而是直接告诉它
    某个 node 对应的源码和配置在哪里。

    Args:
        node_name: trace 中的 node/stage 名称，如 "intent_api_call", "label_mapping"
        project_type: 项目类型，如 "MPI", "QA", "client_search"

    Returns:
        {
            "source_files": ["impl/projects/MPI/intent_recognition.py"],
            "config_files": ["impl/projects/MPI/config.py", "impl/projects/MPI/intent.py"],
            "key_functions": ["_tier2_llm", "_map_raw_intent"],
            "description": "Tier 2 LLM intent recognition and mapping"
        }
    """
    # 项目特定的 node → source 映射
    mappings = {
        "MPI": {
            "intent_api_call": {
                "source_files": ["impl/projects/marketting-planning-intent/adapter.py"],
                "config_files": ["impl/projects/marketting-planning-intent/intent.py"],
                "key_functions": ["extract_output", "_normalize_intent"],
                "description": "Intent API 调用和输出解析"
            },
            "label_mapping": {
                "source_files": ["impl/projects/marketting-planning-intent/adapter.py"],
                "config_files": ["impl/projects/marketting-planning-intent/intent.py"],
                "key_functions": ["_map_raw_to_label"],
                "description": "Raw intent 到标签的映射"
            }
        },
        "QA": {
            "answer_generation": {
                "source_files": ["impl/projects/QA/adapter.py"],
                "config_files": [],
                "key_functions": ["extract_output"],
                "description": "QA 答案生成和提取"
            }
        }
    }

    project_mapping = mappings.get(project_type, {})
    node_mapping = project_mapping.get(node_name)

    if not node_mapping:
        return {
            "error": f"Unknown node '{node_name}' for project '{project_type}'",
            "source_files": [],
            "config_files": [],
            "key_functions": [],
            "description": ""
        }

    return node_mapping


def get_runtime_value_analysis(key: str, value: Any, context: Dict) -> str:
    """分析运行时值的含义，而不是让 agent 读 prompt 去理解

    Args:
        key: 值的名称，如 "raw_intent"
        value: 实际值，如 "4001"
        context: 上下文信息，如 {"project": "MPI", "expected_intent": "nbev_planning"}

    Returns:
        人类可读的分析，如：
        "raw_intent=4001 在 MPI 项目中应该映射到某个 intent 标签。
         当前期望 nbev_planning，但实际映射为 other。
         建议检查: intent.py 中的 INTENT_MAPPING 字典"
    """
    project = context.get("project", "")

    if key == "raw_intent" and project == "MPI":
        expected = context.get("expected_intent", "")
        return (
            f"raw_intent={value} 是 LLM 输出的数值编码。"
            f"在 MPI 项目中，应该通过 INTENT_MAPPING 映射到 intent 标签。"
            f"{'期望映射到: ' + expected if expected else ''}"
            f"建议检查 intent.py 中的映射规则。"
        )

    if key == "confidence":
        threshold = context.get("min_confidence", 0.7)
        return (
            f"confidence={value}，阈值要求 >={threshold}。"
            f"{'低于阈值，可能导致下游拒绝' if value < threshold else '满足阈值要求'}"
        )

    return f"{key}={value}"
