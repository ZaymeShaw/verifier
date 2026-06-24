"""
运行时调用链路分析 Tool - Issue #3 实现设计

目标：让 attribute agent 能够基于运行时信息进行归因，而不是读取静态源码文件

核心原则：
1. 基于 RunTrace 的 execution_trace 提供调用链路分析
2. 只返回关键信息，不返回完整源码
3. 减少 tool call 次数：6-10 次 → 2-3 次
"""

from __future__ import annotations
from typing import Optional, Dict, List, Any
from pathlib import Path

# ============================================================================
# Tool 1: get_call_trace - 获取实际调用链路和分歧点
# ============================================================================

def create_call_trace_tool(trace_provider):
    """创建调用链路分析 tool

    Args:
        trace_provider: 提供 RunTrace 访问的 provider

    Returns:
        get_call_trace 函数
    """

    def get_call_trace(focus: str = "all") -> str:
        """
        Analyze the actual execution call chain and identify divergence points.

        This tool provides a high-level view of what happened during execution,
        which stage failed, and what the actual vs expected outputs were at each stage.

        Use this FIRST before reading any source files - it tells you exactly where
        the problem occurred without needing to understand implementation details.

        Args:
            focus: "all" (full chain) | "divergence" (only failed stages) | "summary" (overview)

        Returns:
            JSON string with call chain, divergence point, and stage-level evidence.

        Example output:
        {
          "call_chain": [
            {
              "stage": "request_normalization",
              "status": "ok",
              "input_sample": {"query": "我想优化健康险..."},
              "output_sample": {"query": "我想优化健康险..."}
            },
            {
              "stage": "intent_api_call",
              "status": "ok",
              "input_sample": {"query": "..."},
              "output_sample": {"intent": "other", "confidence": 0.5}
            },
            {
              "stage": "label_mapping",
              "status": "diverged",
              "expected": {"intent": "nbev_planning"},
              "actual": {"intent": "other"},
              "evidence": "LLM output 'other' does not match expected 'nbev_planning'"
            }
          ],
          "divergence_point": {
            "stage": "intent_api_call",
            "reason": "LLM returned intent='other' instead of expected 'nbev_planning'",
            "next_steps": [
              "Check if LLM prompt includes nbev_planning definition",
              "Check if intent mapping includes correct rules",
              "Verify LLM model config (temperature, max_tokens)"
            ]
          },
          "summary": "Divergence at intent_api_call: LLM output 'other' (confidence=0.5) but expected 'nbev_planning'"
        }
        """
        try:
            trace = trace_provider.get_trace()
            execution_trace = trace.execution_trace or []

            # Build call chain with status analysis
            call_chain = []
            divergence_stage = None

            for i, step in enumerate(execution_trace):
                stage_info = {
                    "stage": step.get("stage") or step.get("node") or f"step_{i}",
                    "status": step.get("status", "unknown"),
                }

                # Add input/output samples (truncated)
                if step.get("input"):
                    stage_info["input_sample"] = _truncate_dict(step["input"], 200)
                if step.get("output"):
                    stage_info["output_sample"] = _truncate_dict(step["output"], 200)

                # Check for divergence
                if step.get("status") in ["failed", "diverged", "error"]:
                    stage_info["status"] = "diverged"
                    if step.get("expected"):
                        stage_info["expected"] = _truncate_dict(step["expected"], 100)
                    if step.get("actual"):
                        stage_info["actual"] = _truncate_dict(step["actual"], 100)
                    if step.get("evidence"):
                        stage_info["evidence"] = str(step["evidence"])[:300]

                    if not divergence_stage:
                        divergence_stage = stage_info["stage"]

                call_chain.append(stage_info)

            # Apply focus filter
            if focus == "divergence":
                call_chain = [s for s in call_chain if s["status"] == "diverged"]
            elif focus == "summary":
                call_chain = call_chain[:3] + ([call_chain[-1]] if len(call_chain) > 3 else [])

            # Build divergence point analysis
            divergence_info = None
            if divergence_stage:
                div_step = next((s for s in call_chain if s["stage"] == divergence_stage), None)
                if div_step:
                    divergence_info = {
                        "stage": divergence_stage,
                        "reason": div_step.get("evidence", "Unknown divergence"),
                        "next_steps": _suggest_next_steps(divergence_stage, div_step)
                    }

            result = {
                "call_chain": call_chain,
                "divergence_point": divergence_info,
                "summary": _build_summary(call_chain, divergence_info)
            }

            import json
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"Error analyzing call trace: {str(e)}"

    return get_call_trace


def _truncate_dict(d: dict, max_chars: int) -> dict:
    """Truncate dict values to max_chars"""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = v[:max_chars] + "..." if len(v) > max_chars else v
        elif isinstance(v, (int, float, bool)):
            result[k] = v
        elif isinstance(v, dict):
            result[k] = _truncate_dict(v, max_chars // 2)
        else:
            result[k] = str(v)[:max_chars]
    return result


def _suggest_next_steps(stage: str, step_info: dict) -> List[str]:
    """Suggest next debugging steps based on stage"""
    suggestions = []

    if "intent" in stage.lower() or "llm" in stage.lower():
        suggestions.append("Use get_function_signature to check LLM call config")
        suggestions.append("Use get_config_value to check intent definitions")
        if step_info.get("actual", {}).get("confidence", 1.0) < 0.7:
            suggestions.append("Low confidence suggests prompt may lack examples for this query pattern")

    if "mapping" in stage.lower():
        suggestions.append("Use get_config_value to check mapping rules")

    if "validation" in stage.lower():
        suggestions.append("Check input schema and validation rules")

    return suggestions or ["Investigate implementation of this stage"]


def _build_summary(call_chain: List[dict], divergence: Optional[dict]) -> str:
    """Build one-line summary"""
    if not divergence:
        return f"All {len(call_chain)} stages completed successfully"

    div_stage = divergence["stage"]
    reason = divergence["reason"][:150]
    return f"Divergence at {div_stage}: {reason}"


# ============================================================================
# Tool 2: get_function_signature - 获取函数签名和元信息
# ============================================================================

def create_function_signature_tool(signature_provider):
    """创建函数签名查询 tool"""

    def get_function_signature(function_path: str) -> str:
        """
        Get function signature and metadata without reading full source code.

        This is more efficient than reading entire files - it returns only the
        function definition, docstring, and key configuration (e.g., LLM model config).

        Args:
            function_path: Format "module.function" or "stage_name" from call trace

        Returns:
            JSON with signature, docstring, and relevant config

        Example:
        {
          "function": "intent_recognition._tier2_llm",
          "signature": "def _tier2_llm(query: str, context: dict) -> dict",
          "docstring": "Tier 2: Call LLM for intent recognition...",
          "config": {
            "model": "claude-3-sonnet",
            "temperature": 0.3,
            "prompt_template": "intent_prompt.INTENT_RECOGNITION_TEMPLATE"
          },
          "calls": ["llm_client.complete", "intent_mapper.map_raw_intent"]
        }
        """
        try:
            sig_info = signature_provider.get_signature(function_path)
            if not sig_info:
                return f"Function '{function_path}' not found in signature registry"

            import json
            return json.dumps(sig_info, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Error retrieving signature: {str(e)}"

    return get_function_signature


# ============================================================================
# Tool 3: get_config_value - 获取配置值
# ============================================================================

def create_config_value_tool(config_provider):
    """创建配置值查询 tool"""

    def get_config_value(config_path: str) -> str:
        """
        Get a specific configuration value without loading entire config files.

        More targeted than reading full config.py or constants.py files.

        Args:
            config_path: Dot-separated path like "intent_mapping.4001" or
                        "intent_list" or "llm_config.temperature"

        Returns:
            The configuration value as JSON

        Example queries:
        - "intent_list" → ["customer_portrait", "nbev_planning", ...]
        - "intent_mapping.4001" → "other"
        - "llm_config.model" → "claude-3-sonnet"
        """
        try:
            value = config_provider.get_config(config_path)
            if value is None:
                return f"Config path '{config_path}' not found"

            import json
            return json.dumps({"config_path": config_path, "value": value}, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Error retrieving config: {str(e)}"

    return get_config_value


# ============================================================================
# Provider Interfaces
# ============================================================================

class TraceProvider:
    """提供 RunTrace 访问的接口"""
    def get_trace(self):
        """返回当前的 RunTrace 对象"""
        raise NotImplementedError


class SignatureProvider:
    """提供函数签名访问的接口"""
    def get_signature(self, function_path: str) -> Optional[Dict[str, Any]]:
        """返回函数签名和元信息"""
        raise NotImplementedError


class ConfigProvider:
    """提供配置值访问的接口"""
    def get_config(self, config_path: str) -> Any:
        """返回配置值"""
        raise NotImplementedError
