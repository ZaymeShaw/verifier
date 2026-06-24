from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .knowledge_base import load_knowledge_base
from .llm_client import LlmClient, project_llm_client
from .project_loader import load_project_document
from .schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace
from .trace_analysis import analyze_execution_trace, map_trace_node_to_source

logger = logging.getLogger(__name__)

MAX_SOURCE_FILE_BYTES = 64000
SOURCE_READABLE_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".txt", ".cfg", ".toml", ".prompt"}
AGGREGATE_TOOL_BUDGET = 192_000
ATTRIBUTE_TOOL_CALL_LIMIT = 6  # Cap search_source_file calls per case; allow more probes for thorough attribution
ATTRIBUTE_MAX_TOOL_HISTORY = 3  # Keep more tool context for multi-step attribution


# Per-field size caps for compact view (chars). Keep loose so attribution still has signal,
# but prevent any single field from blowing the 80k user-prompt budget.
MAX_FIELD_CHARS_LARGE = 10000   # for extracted_output (can be a big client list)
MAX_FIELD_CHARS_MEDIUM = 2500   # for execution_trace items, business_expectations items, reasoning_summary
MAX_FIELD_CHARS_SMALL = 1200    # for evidence, runtime_logs entries, other text fields
MAX_RUNTIME_LOG_ENTRIES = 8
MAX_EVIDENCE_REFS = 15
MAX_EXEC_TRACE_ITEMS = 5
MAX_LIST_ITEMS = 5              # business_expectations, fulfillment_assessments, evidence


def _compact_obj(obj, max_str_chars: int, max_list_items: int | None = None):
    """Recursively walk dicts/lists; truncate any string > max_str_chars, cap list length.

    Preserves structure so the LLM can still reason about each item.
    """
    if isinstance(obj, str):
        if len(obj) > max_str_chars:
            return obj[:max_str_chars] + f"...[truncated {len(obj) - max_str_chars:,} chars]"
        return obj
    if isinstance(obj, dict):
        return {k: _compact_obj(v, max_str_chars, max_list_items) for k, v in obj.items()}
    if isinstance(obj, list):
        items = obj if max_list_items is None else obj[:max_list_items]
        return [_compact_obj(x, max_str_chars, max_list_items) for x in items]
    return obj


def _compact_blob(obj, max_chars: int) -> str:
    """JSON-serialize obj; truncate to max_chars. Used when structure is unpredictable
    (e.g., extracted_output with deeply nested lists)."""
    s = json.dumps(obj, ensure_ascii=False, default=str)
    if len(s) > max_chars:
        return s[:max_chars] + f"...[truncated {len(s) - max_chars:,} chars]"
    return s


def _compact_trace(trace: RunTrace) -> dict:
    """Compact view of RunTrace for attribute prompt.

    Drops raw_response (often large), trims execution_trace to first 5 nodes,
    drops state_history/gate_decisions/transition_decisions (attribution does
    not need them). Caps per-field size to keep prompt under 80k budget.
    """
    return {
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
        "input": _compact_obj(trace.input, MAX_FIELD_CHARS_SMALL),
        "normalized_request": _compact_obj(trace.normalized_request, MAX_FIELD_CHARS_SMALL),
        "extracted_output": _compact_blob(trace.extracted_output, MAX_FIELD_CHARS_LARGE),
        "project_fields": _compact_obj(trace.project_fields, MAX_FIELD_CHARS_SMALL),
        "runtime_logs": _compact_obj(trace.runtime_logs, MAX_FIELD_CHARS_SMALL, MAX_RUNTIME_LOG_ENTRIES),
        "evidence_refs": _compact_obj(trace.evidence_refs, MAX_FIELD_CHARS_SMALL, MAX_EVIDENCE_REFS),
        "execution_trace": _compact_obj(trace.execution_trace, MAX_FIELD_CHARS_MEDIUM, MAX_EXEC_TRACE_ITEMS),
        "status": trace.status,
        "error": _compact_obj(trace.error, MAX_FIELD_CHARS_SMALL),
    }


def _compact_judge(judge: JudgeResult) -> dict:
    """Compact view of JudgeResult for attribute prompt.

    Drops raw_model_output (often huge — it's the full LLM response payload)
    and score_details. Caps per-field size to keep prompt under 80k budget.
    """
    return {
        "trace_id": judge.trace_id,
        "project_id": judge.project_id,
        "verdict": judge.verdict,
        "score": judge.score,
        "confidence": judge.confidence,
        "intent_model": _compact_obj(judge.intent_model, MAX_FIELD_CHARS_SMALL),
        "consumer_contract": _compact_obj(judge.consumer_contract, MAX_FIELD_CHARS_SMALL),
        "business_expectations": _compact_obj(judge.business_expectations, MAX_FIELD_CHARS_MEDIUM, MAX_LIST_ITEMS),
        "fulfillment_assessments": _compact_obj(judge.fulfillment_assessments, MAX_FIELD_CHARS_MEDIUM, MAX_LIST_ITEMS),
        "overall_fulfillment": _compact_obj(judge.overall_fulfillment, MAX_FIELD_CHARS_SMALL),
        "reconstructed_intent": _compact_obj(judge.reconstructed_intent, MAX_FIELD_CHARS_SMALL),
        "judge_basis": _compact_obj(judge.judge_basis, MAX_FIELD_CHARS_SMALL),
        "judge_method": _compact_obj(judge.judge_method, MAX_FIELD_CHARS_SMALL),
        "intent_decomposition": _compact_obj(getattr(judge, "intent_decomposition", None) or [], MAX_FIELD_CHARS_SMALL, MAX_LIST_ITEMS),
        "condition_assessments": _compact_obj(getattr(judge, "condition_assessments", None) or [], MAX_FIELD_CHARS_SMALL, MAX_LIST_ITEMS),
        "semantic_equivalence_checks": _compact_obj(getattr(judge, "semantic_equivalence_checks", None) or [], MAX_FIELD_CHARS_SMALL, MAX_LIST_ITEMS),
        "verdict_derivation": _compact_obj(getattr(judge, "verdict_derivation", None) or "", MAX_FIELD_CHARS_SMALL),
        "boundary_decision": _compact_obj(getattr(judge, "boundary_decision", None) or "", MAX_FIELD_CHARS_SMALL),
        "evaluation_boundary": _compact_obj(getattr(judge, "evaluation_boundary", None) or "", MAX_FIELD_CHARS_SMALL),
        "primary_assessment": _compact_obj(getattr(judge, "primary_assessment", None) or "", MAX_FIELD_CHARS_SMALL),
        "missing": _compact_obj(getattr(judge, "missing", None) or [], MAX_FIELD_CHARS_SMALL, MAX_LIST_ITEMS),
        "wrong": _compact_obj(getattr(judge, "wrong", None) or [], MAX_FIELD_CHARS_SMALL, MAX_LIST_ITEMS),
        "extra": _compact_obj(getattr(judge, "extra", None) or [], MAX_FIELD_CHARS_SMALL, MAX_LIST_ITEMS),
        "evidence": _compact_obj(getattr(judge, "evidence", None) or [], MAX_FIELD_CHARS_SMALL, MAX_LIST_ITEMS),
        "reasoning_summary": _compact_obj(getattr(judge, "reasoning_summary", None) or "", MAX_FIELD_CHARS_MEDIUM),
        "needs_human_review": getattr(judge, "needs_human_review", None),
        "quality_flags": getattr(judge, "quality_flags", []) or [],
    }



def _load_source_code_evidence(spec: ProjectSpec, project_attribute_context: dict | None) -> dict[str, str]:
    """读取项目源码/配置/文档，作为归因的代码级证据。"""
    source_files: dict[str, str] = {}
    project_root = Path(spec.root) if spec.root else None

    # 1. source_config_paths from adapter
    config_paths = (project_attribute_context or {}).get("source_config_paths") or {}
    if isinstance(config_paths, dict):
        for key, path_str in config_paths.items():
            p = Path(path_str)
            if not p.exists() and project_root:
                p = project_root / path_str
            if p.exists() and p.suffix in SOURCE_READABLE_SUFFIXES:
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                    source_files[str(p)] = content[:MAX_SOURCE_FILE_BYTES]
                except Exception:
                    pass

    # 2. project documents (source_* prefixed)
    for doc_key, doc_rel in (spec.documents or {}).items():
        if not doc_key.startswith("source_"):
            continue
        p = Path(project_root or ".") / str(doc_rel)
        if not p.exists():
            continue
        if p.suffix not in SOURCE_READABLE_SUFFIXES:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            source_files[f"project_doc:{doc_key}"] = content[:MAX_SOURCE_FILE_BYTES]
        except Exception:
            pass

    # 3. adapter.py itself
    if spec.adapter and project_root:
        adapter_path = project_root / spec.adapter
        if adapter_path.exists():
            try:
                source_files[f"project_adapter:{spec.adapter}"] = adapter_path.read_text(encoding="utf-8", errors="ignore")[:MAX_SOURCE_FILE_BYTES]
            except Exception:
                pass

    return source_files


def _taxonomy(spec: ProjectSpec) -> set[str]:
    taxonomy = spec.frontend_extensions.get("error_taxonomy") if spec.frontend_extensions else None
    return set(taxonomy or [])


def _normalize_incomplete_reason(data: dict) -> str:
    reason = str(data.get("incomplete_reason") or "")
    quality = data.get("analysis_quality") or {}
    if reason or not isinstance(quality, dict) or quality.get("passed") is not False:
        return reason
    missing = quality.get("missing") or []
    if missing:
        return "归因质量门未通过，缺少证据：" + "、".join(str(item) for item in missing)
    return "归因质量门未通过，当前证据不足以支撑正式根因。"


def _coverage(value: dict, key: str) -> bool:
    return bool(value.get(key)) if isinstance(value, dict) else False


def _unsupported_claims(result: AttributeResult) -> list:
    coverage = result.evidence_coverage or {}
    claims = coverage.get("unsupported_claims") if isinstance(coverage, dict) else []
    return list(claims or [])


def _has_chain_evidence(result: AttributeResult) -> bool:
    for node in result.chain_nodes or []:
        if isinstance(node, dict) and node.get("status") in {"failed", "suspicious"} and node.get("evidence"):
            return True
    return bool(result.earliest_divergence.get("evidence") if isinstance(result.earliest_divergence, dict) else False)


# FIX P3: Build meaningful incomplete_reason instead of empty template
def _build_incomplete_reason(result: AttributeResult, spec: ProjectSpec, trace: RunTrace, judge: JudgeResult) -> str:
    """根据 judge 和 trace 证据，生成有信息量的 incomplete_reason，而非空模板。"""
    # 收集关键信息
    query = ""
    if isinstance(trace.input, dict):
        query = trace.input.get("query") or trace.input.get("question") or trace.input.get("user_text") or ""
    actual = trace.extracted_output or {}
    expected = judge.expected or {}
    verdict = judge.verdict or "unknown"
    missing_reqs = [item.get("requirement") for item in (judge.missing or []) if isinstance(item, dict)]
    wrong_reqs = [item.get("requirement") for item in (judge.wrong or []) if isinstance(item, dict)]

    # 根据 verdict 和证据生成描述
    reason_parts = []
    if verdict == "incorrect":
        reason_parts.append(f"判定结果为 incorrect")
        if missing_reqs:
            reason_parts.append(f"缺失项：{missing_reqs}")
        if wrong_reqs:
            reason_parts.append(f"错误项：{wrong_reqs}")
        # 添加实际 vs 期望的关键差异
        if isinstance(actual, dict) and isinstance(expected, dict):
            diff_keys = [k for k in expected if k in actual and actual[k] != expected[k]]
            if diff_keys:
                reason_parts.append(f"关键差异字段：{diff_keys[:3]}")
    elif verdict == "uncertain":
        reason_parts.append(f"判定结果为 uncertain，证据不足以做出确定性判断")
    else:
        reason_parts.append(f"判定结果为 {verdict}")

    reason_parts.append("attribute agent 未能获取足够的源码/配置证据来支撑正式根因定位。")
    reason_parts.append("建议：检查 source_file_catalog 是否包含相关 prompt 文件和 adapter 源码。")

    return "；".join(reason_parts) + "。"


def normalize_attribute_trace_result(spec: ProjectSpec, trace: RunTrace, judge: JudgeResult, result: AttributeResult) -> AttributeResult:
    coverage = result.evidence_coverage or {}
    unsupported = _unsupported_claims(result)
    missing = list((result.analysis_quality or {}).get("missing") or []) if isinstance(result.analysis_quality, dict) else []
    has_current_gap = _coverage(coverage, "query") and _coverage(coverage, "actual") and _coverage(coverage, "expected")
    has_chain = _coverage(coverage, "execution_trace") and _has_chain_evidence(result)
    has_location_evidence = _coverage(coverage, "project_docs") or _coverage(coverage, "code_or_config")
    taxonomy = _taxonomy(spec)
    has_valid_llm_attribution = (
        bool(result.expectation_attributions)
        and bool(result.causal_category)
        and result.causal_category != "needs_human_review"
        and (not taxonomy or result.causal_category in taxonomy or result.primary_error_type in taxonomy)
    )
    blocked_by_unsupported = bool(unsupported)
    blocked_by_locations = bool(result.suspected_locations) and not has_location_evidence and not has_valid_llm_attribution
    blocked_by_hypothesis = bool(result.root_cause_hypothesis) and not result.verification_steps and not (has_current_gap and has_chain) and not has_valid_llm_attribution
    has_probe_evidence = bool(result.probe_results) and any(
        isinstance(p, dict) and p.get("status") == "passed" for p in result.probe_results
    )
    if blocked_by_locations and has_probe_evidence:
        blocked_by_locations = False
    if blocked_by_unsupported or blocked_by_locations or blocked_by_hypothesis:
        result.suspected_locations = []
        result.analysis_quality = {
            **(result.analysis_quality or {}),
            "passed": False,
            "status": "insufficient_evidence",
            "missing": sorted(set([*missing, "supported root-cause evidence"])),
        }
        result.incomplete_reason = result.incomplete_reason or _build_incomplete_reason(result, spec, trace, judge)
        if "ungrounded_root_cause" not in result.quality_flags:
            result.quality_flags.append("ungrounded_root_cause")
        return result
    if has_current_gap and has_chain and has_location_evidence and not missing:
        result.analysis_quality = {**(result.analysis_quality or {}), "passed": True, "status": "supported_root_cause"}
        return result
    if has_valid_llm_attribution:
        result.analysis_quality = {
            **(result.analysis_quality or {}),
            "passed": True,
            "status": "supported_root_cause",
            "evidence_quality": "medium" if not has_location_evidence else "high",
        }
        return result
    result.analysis_quality = {
        **(result.analysis_quality or {}),
        "passed": False,
        "status": "next_verification_step",
        "missing": missing or ["local_verification"],
    }
    if not result.incomplete_reason:
        result.incomplete_reason = "归因需要下一步验证：" + "、".join(str(item) for item in result.analysis_quality["missing"])
    else:
        reason = str(result.incomplete_reason)
        if not reason or "supported root-cause evidence" in reason or "unsupported root-cause evidence" in reason:
            result.incomplete_reason = _build_incomplete_reason(result, spec, trace, judge)
    return result


def _judge_fulfillment_status(judge: JudgeResult) -> str:
    status = (judge.overall_fulfillment or {}).get("status") if isinstance(judge.overall_fulfillment, dict) else ""
    if status:
        return str(status)
    statuses = []
    for item in judge.fulfillment_assessments or []:
        if isinstance(item, dict):
            statuses.append(str(item.get("status") or ""))
        else:
            statuses.append(str(getattr(item, "status", "")))
    if not statuses:
        return "not_evaluable"
    if any(item == "not_fulfilled" for item in statuses):
        return "not_fulfilled"
    if any(item in {"partially_fulfilled", "not_evaluable", "contested"} for item in statuses):
        return next(item for item in statuses if item in {"partially_fulfilled", "not_evaluable", "contested"})
    return "fulfilled"


def _expectation_id(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("expectation_id") or "")
    return str(getattr(item, "expectation_id", ""))


def _item_value(item: object, key: str, default: object = None) -> object:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _attribution_targets(judge: JudgeResult) -> list[dict]:
    expectations = {}
    for item in judge.business_expectations or []:
        expectation_id = _expectation_id(item)
        if expectation_id:
            expectations[expectation_id] = item
    targets = []
    failing_statuses = {"not_fulfilled", "partially_fulfilled", "not_evaluable", "contested"}
    for assessment in judge.fulfillment_assessments or []:
        expectation_id = _expectation_id(assessment)
        status = str(_item_value(assessment, "status", ""))
        if expectation_id and status in failing_statuses:
            expectation = expectations.get(expectation_id, {})
            targets.append(
                {
                    "expectation_id": expectation_id,
                    "fulfillment_status": status,
                    "source_intent_id": _item_value(expectation, "source_intent_id", ""),
                    "user_goal": _item_value(expectation, "user_goal", "") or _item_value(expectation, "user_intent", ""),
                    "required_outcome": _item_value(expectation, "required_outcome", "") or _item_value(expectation, "expected_outcome", ""),
                    "failure_impact": _item_value(expectation, "failure_impact", "") or _item_value(assessment, "downstream_impact", ""),
                    "assessment": assessment,
                    "expectation": expectation,
                }
            )
    if targets:
        return targets
    for item in judge.business_expectations or []:
        expectation_id = _expectation_id(item)
        if expectation_id:
            targets.append(
                {
                    "expectation_id": expectation_id,
                    "fulfillment_status": _judge_fulfillment_status(judge),
                    "source_intent_id": _item_value(item, "source_intent_id", ""),
                    "user_goal": _item_value(item, "user_goal", "") or _item_value(item, "user_intent", ""),
                    "required_outcome": _item_value(item, "required_outcome", "") or _item_value(item, "expected_outcome", ""),
                    "failure_impact": _item_value(item, "failure_impact", ""),
                    "expectation": item,
                }
            )
    return targets


def _fulfilled_attribute_result(trace: RunTrace, judge: JudgeResult) -> AttributeResult:
    fulfillment_status = _judge_fulfillment_status(judge)
    expectation_ids = [_expectation_id(item) for item in (judge.business_expectations or judge.fulfillment_assessments or [])]
    expectation_ids = [item for item in expectation_ids if item]
    if not expectation_ids:
        expectation_ids = ["primary_business_expectation"]
    evidence = list(judge.evidence or [judge.reasoning_summary or "business expectations are fulfilled"])
    attributions = [
        {
            "expectation_id": expectation_id,
            "fulfillment_status": fulfillment_status,
            "causal_category": "no_issue",
            "earliest_divergence": {"node": "fulfillment_assessment", "evidence": evidence, "confidence": "high"},
            "causal_chain": [{"name": "fulfillment_assessment", "status": "succeeded", "evidence": evidence}],
            "local_verifications": [],
            "suspected_locations": [],
            "improvement_direction": [],
            "source_evidence": [],
            "probe_evidence": evidence,
            "incomplete_reason": "",
        }
        for expectation_id in expectation_ids
    ]
    return AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or ""),
        expectation_attributions=attributions,
        causal_category="no_issue",
        probe_results=[{"probe": "fulfillment_assessment", "status": "passed", "evidence": evidence}],
        failure_category="fulfilled_expectation",
        failure_stage="fulfilled_expectation",
        analysis_method="fulfilled_expectation_attribution",
        evidence_chain=evidence,
        trace_analysis=list(trace.execution_trace or []),
        chain_nodes=[{"name": "fulfillment_assessment", "status": "succeeded", "evidence": evidence, "reason": "business expectations fulfilled"}],
        local_verifications=[],
        earliest_divergence={"node": "fulfillment_assessment", "evidence": evidence, "confidence": "high"},
        evidence_coverage={"judge_evidence": bool(evidence), "execution_trace": bool(trace.execution_trace)},
        analysis_quality={"passed": True, "missing": []},
        incomplete_reason="",
        suspected_locations=[],
        root_cause_hypothesis="业务预期已达成，当前归因为 no_issue，不进入失败根因链路。",
        verification_steps=["复核 judge.fulfillment_assessments 均为 fulfilled，确认当前输出满足业务预期。"],
        patch_direction=["无需修改业务实现；若后续出现 contested 或 not_fulfilled evidence，再按对应 expectation 重新归因。"],
        business_impact="当前输出满足业务预期，可作为 fulfilled 聚合证据。",
        primary_error_type="no_issue",
        error_types=[],
        severity="none",
        needs_human_review=False,
        scenario=str(trace.project_fields.get("scenario") or ""),
        quality_flags=[],
    )


def attribute_failure(
    spec: ProjectSpec,
    trace: RunTrace,
    judge: JudgeResult,
    llm: Optional[LlmClient] = None,
    project_attribute_context: Optional[dict] = None,
) -> AttributeResult:
    if _judge_fulfillment_status(judge) == "fulfilled" and judge.verdict == "correct":
        return _fulfilled_attribute_result(trace, judge)
    attribution = load_project_document(spec, "attribution")
    attribution_targets = _attribution_targets(judge)

    # Build source file catalog (paths + sizes only, not contents) and on-demand retrieval tool
    from impl.tools.source_retrieval import ProjectSourceFileProvider, create_source_file_search_tool
    source_provider = ProjectSourceFileProvider(spec, project_attribute_context, aggregate_byte_budget=AGGREGATE_TOOL_BUDGET)
    source_file_catalog = source_provider.list_files()
    search_source_file = create_source_file_search_tool(source_provider)
    tools = [search_source_file]

    system = """你是通用评估系统的 attribute agent。目标是与 judge 有本质区别：judge 评估业务预期是否达成，你必须围绕未达成、部分达成、不可评估或被质疑的 intent-derived business_expectations 深入源码/配置/prompt/trace/probe，解释 fulfillment 状态背后的因果链。

【输出格式硬性要求】
- 最终输出必须是单个合法 JSON 对象，以 `{` 起始、以 `}` 结尾。
- 禁止 markdown 散文、章节标题、列表、自然语言说明或思维链作为最终回答。
- 如需引用代码片段，必须放入 JSON 字符串字段（如 evidence_chain、local_verifications）。
- 如必须使用 ``` 代码块包裹，仅允许一个 ```json ... ``` 代码块包裹完整 JSON，且代码块外不得有其他散文。

核心流程：
0. **优先使用 trace_analysis**（Issue #3 新增）：
   - user prompt 中的 `trace_analysis` 字段包含预处理的调用链路分析结果
   - 包括：first_failed_node（第一个失败节点）、divergence_chain（分歧链路）、runtime_values（运行时实际值）、suggested_probes（建议的验证方向）、source_mapping（失败节点对应的源码位置）
   - **优先基于这些预处理结果进行归因**，避免花费大量 tool call 去读源码理解调用链路
1. 从 attribution_targets 选择需要归因的 expectation；这些 target 已由 judge 的 intent_model/business_expectations/fulfillment_assessments 产生，不要独立重建用户意图
2. 对每个 expectation 重建 expected behavior、actual behavior、gap 或 contested fulfillment reason
3. 在 execution_trace、project_attribute_context.chain_nodes_to_check 和按需读取的源码文件中定位最早分歧
4. 产出 expectation_attributions，包含 expectation_id、fulfillment_status、causal_category、earliest_divergence、causal_chain、local_verifications、suspected_locations、improvement_direction
5. suspected_locations 只能使用 source_file_catalog 中真实存在的路径/配置/文档证据；不能编造路径、函数名或历史 case
6. 如果 probe/source evidence 不足，必须设置 incomplete_reason 和 blocked-probe reason，不能伪造正式归因

分析优先级和策略：
1. **优先分析 execution_trace**（运行时实际发生了什么）：
   - 检查 run_trace.execution_trace 中的每个 step
   - 定位第一个 status="failed"/"diverged"/"error" 的 step
   - 记录该 step 的 expected vs actual，这是最直接的分歧证据
   - 基于分歧点的 stage/node 名称，推断对应的函数/模块

2. **然后按需读取源码文件**（验证假设，核心能力！）：
   - user prompt 中的 source_file_catalog 列出所有可用源码文件（key、path、size_chars、description）
   - **必须调用 search_source_file(file_key) 工具读取关键文件内容**，不能仅凭文件名推测
   - 对于 external LLM service（如 intent recognition），优先级：
     * 如果 trace 中有 LLM 的实际输出（如 raw_intent="4001"），先分析输出为何被判定为错误
     * 然后读取 **config 文件**（如 intent.py, config.py）确认映射规则是否完整
     * 最后才考虑读取 **prompt 文件**（如 intent_prompt.py）确认 LLM prompt 内容
   - 对于配置错误，直接读取 **config 文件**确认枚举值、阈值等
   - 只调用你需要的文件，优先读取与分歧点相关的文件
   - suspected_locations 中的路径必须来自 source_file_catalog 中实际存在的文件
   - **禁止说"无法访问 prompt 文件"或"prompt 内容不可见"** —— catalog 中的文件都可以通过 tool 读取

3. **Tool 使用效率**：
   - 优先读取小文件（config、mapping）而不是大文件（完整 prompt）
   - 基于 trace 中的具体值（如 raw_intent="4001"）直接检查映射表，而不是读取整个 prompt 去理解 LLM 应该输出什么
   - 每个 probe 应该有明确目标：验证某个具体假设（如"4001 是否映射到 nbev_planning"）

关键规则：
- causal_category 使用 implementation_bug、model_capability_gap、boundary_limitation、unclear_contract、insufficient_evidence、no_issue 等
- fulfilled 也可以被解释为 no_issue，但不需要失败归因
- improvement_direction 必须指向产生机制，而不是泛泛建议
- 分析文字必须使用中文，包括 root_cause_hypothesis、verification_steps、patch_direction、business_impact 等所有文本字段。禁止使用英文撰写归因内容。
- **必须执行至少 1 个 probe**（调用 search_source_file 读取源码文件）来支撑归因结论，除非 execution_trace 已经提供了充分的分歧证据
- **Tool call 预算有限（最多 {tool_call_limit} 次）**，优先读取与分歧点直接相关的小文件（config、mapping），而不是完整的大文件（prompt）
- 如果 execution_trace 中已经有具体的错误值（如 raw_intent="4001", mapped="other"），直接检查映射规则，不需要读取完整 prompt
- 如果 tool call 预算用尽且归因不完整，必须设置 incomplete_reason="tool_call_budget_exhausted: 已读取 N 个文件，但仍需读取 [file_list] 来完成归因"
- 如果 catalog 中有关键文件但因预算限制未读取，在 incomplete_reason 中明确说明，不要说"文件不在 catalog"或"无法访问"。"""

    # Issue #3: 在 user prompt 中提供预处理的调用链路分析结果
    # 这样 agent 可以"直接引用系统原函数"，而不需要读大量源码文件去推测
    trace_analysis_result = None
    if trace.execution_trace:
        try:
            trace_analysis_result = analyze_execution_trace(trace.execution_trace)
            # 如果找到了分歧点，映射到源码位置
            if trace_analysis_result.get("first_failed_node"):
                node_name = trace_analysis_result["first_failed_node"]["name"]
                project_name = spec.name if spec else "unknown"
                source_mapping = map_trace_node_to_source(node_name, project_name)
                trace_analysis_result["source_mapping"] = source_mapping
        except Exception as e:
            logger.warning(f"Trace analysis failed: {e}")
            trace_analysis_result = {"error": str(e)}

    user_data = {
            "trace_analysis": trace_analysis_result,  # Issue #3: 预处理的调用链路分析
            "attribution_spec": attribution,
            "run_trace": _compact_trace(trace),
            "judge_result": _compact_judge(judge),
            "attribution_targets": attribution_targets,
            "project_attribute_context": project_attribute_context or {},
            "source_file_catalog": source_file_catalog,
            "allowed_error_taxonomy": sorted(_taxonomy(spec)),
            "required_output": {
                "expectation_attributions": [
                    {"expectation_id": "string", "fulfillment_status": "fulfilled|partially_fulfilled|not_fulfilled|not_evaluable|contested", "causal_category": "implementation_bug|model_capability_gap|boundary_limitation|unclear_contract|insufficient_evidence|no_issue", "earliest_divergence": {}, "causal_chain": [], "local_verifications": [], "suspected_locations": [], "improvement_direction": [], "source_evidence": [], "probe_evidence": [], "incomplete_reason": "string"}
                ],
                "causal_category": "implementation_bug|model_capability_gap|boundary_limitation|unclear_contract|insufficient_evidence|no_issue",
                "probe_results": [],
                "failure_category": "string",
                "failure_stage": "string",
                "analysis_method": "string",
                "evidence_chain": [],
                "trace_analysis": [],
                "chain_nodes": [
                    {"name": "string", "status": "normal|suspicious|failed|not_verified", "evidence": [], "reason": "string"}
                ],
                "local_verifications": [
                    {"method": "string", "target": "string", "result": "string", "evidence": []}
                ],
                "earliest_divergence": {
                    "node": "string",
                    "expected": "object|string|null",
                    "actual": "object|string|null",
                    "evidence": [],
                    "confidence": "high|medium|low|unknown"
                },
                "evidence_coverage": {
                    "query": "boolean",
                    "actual": "boolean",
                    "expected": "boolean",
                    "execution_trace": "boolean",
                    "project_docs": "boolean",
                    "code_or_config": "boolean",
                    "unsupported_claims": []
                },
                "analysis_quality": {
                    "passed": "boolean",
                    "missing": [],
                    "standard": "string"
                },
                "incomplete_reason": "string",
                "suspected_locations": [],
                "root_cause_hypothesis": "string",
                "verification_steps": [],
                "patch_direction": [],
                "business_impact": "string",
                "primary_error_type": "string",
                "error_types": [],
                "severity": "string",
                "needs_human_review": "boolean|null",
                "scenario": "string",
                "quality_flags": [],
            },
        }
    user = json.dumps(user_data, ensure_ascii=False)
    # Log prompt sizes for budget monitoring
    system_size = len(system)
    user_size = len(user)
    catalog_count = len(source_file_catalog)
    catalog_total_chars = sum(e.get("size_chars", 0) for e in source_file_catalog)
    compact_trace_size = len(json.dumps(_compact_trace(trace), ensure_ascii=False, default=str))
    compact_judge_size = len(json.dumps(_compact_judge(judge), ensure_ascii=False, default=str))
    targets_size = len(json.dumps(attribution_targets, ensure_ascii=False, default=str))
    context_size = len(json.dumps(project_attribute_context or {}, ensure_ascii=False, default=str))
    logger.info(
        f"[attribute] trace_id={trace.trace_id} case_id={trace.input.get('case_id', '?') if isinstance(trace.input, dict) else '?'} "
        f"Prompt sizes: system={system_size:,} chars, user={user_size:,} chars (~{user_size//4:,} tokens), "
        f"sections: trace={compact_trace_size:,}, judge={compact_judge_size:,}, targets={targets_size:,}, "
        f"context={context_size:,}; source_catalog={catalog_count} files (~{catalog_total_chars:,} chars via tool)"
    )
    if user_size > 80000:
        logger.warning(f"[attribute] user prompt {user_size:,} chars exceeds 80k budget")
    else:
        logger.info(f"[attribute] user prompt within 80k budget")

    # CRITICAL: Do NOT pass knowledge to avoid JsonDb creation
    # knowledge = load_knowledge_base(spec)
    client = llm or project_llm_client(
        spec, role="attribute", knowledge=None, tools=tools,
        tool_call_limit=ATTRIBUTE_TOOL_CALL_LIMIT,
        compress_tool_results=True,
        max_tool_calls_from_history=ATTRIBUTE_MAX_TOOL_HISTORY,
    )
    try:
        data = client.complete_json(system, user, trace_id=trace.trace_id)
    except Exception as e:
        logger.error(f"[attribute] LLM call failed with exception: {e}")
        data = {"error": "llm_request_failed", "raw_text": str(e)}
    # Detect parse failure: LLM returned prose-only output (no JSON fence) so
    # extract_json fell back to {"raw_text": ...}. Without this guard, the code
    # below silently constructs an AttributeResult with empty
    # expectation_attributions and a misleading "needs_human_review" taxonomy hit.
    _parse_failed = (
        not data.get("error")
        and not data.get("expectation_attributions")
        and not data.get("causal_category")
        and not data.get("failure_category")
        and bool(data.get("raw_text"))
    )
    if _parse_failed:
        data = {**data, "error": "attribute_parse_failed"}
    _llm_call_failed = data.get("error") in ("llm_request_failed", "missing_api_key", "attribute_parse_failed")
    if _llm_call_failed or "llm_call_failed" in (judge.quality_flags or []):
        error_text = data.get("raw_text") or data.get("error") or judge.reasoning_summary or "judge LLM call failed"
        return AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.input.get("case_id") or ""),
            expectation_attributions=[{"expectation_id": item.get("expectation_id"), "fulfillment_status": item.get("status"), "causal_category": "insufficient_evidence", "earliest_divergence": {"node": "semantic judge or attribute LLM", "evidence": [error_text], "confidence": "high"}, "causal_chain": [{"name": "semantic judge or attribute LLM", "status": "failed", "evidence": [error_text]}], "local_verifications": [], "suspected_locations": [], "improvement_direction": ["恢复 LLM 后重新运行 judge 和 attribute agent。"], "incomplete_reason": "attribute blocked"} for item in (judge.fulfillment_assessments or [])],
            causal_category="insufficient_evidence",
            probe_results=[{"probe": "llm_call", "status": "failed", "evidence": [error_text]}],
            failure_category="未归因",
            failure_stage="llm_attribute_call" if _llm_call_failed else "judge_llm_call",
            analysis_method="llm_call_failed" if _llm_call_failed else "judge_llm_failed_blocked_attribute",
            evidence_chain=[error_text, *(judge.evidence or [])],
            trace_analysis=list(trace.execution_trace or []),
            chain_nodes=[{"name": "semantic judge or attribute LLM", "status": "failed", "evidence": [error_text], "reason": error_text}],
            local_verifications=[],
            earliest_divergence={"node": "semantic judge or attribute LLM", "evidence": [error_text], "confidence": "high"},
            evidence_coverage={"query": bool(trace.normalized_request or trace.input), "actual": bool(trace.extracted_output), "expected": bool(judge.expected), "execution_trace": bool(trace.execution_trace), "project_docs": False, "code_or_config": False, "unsupported_claims": []},
            analysis_quality={"passed": False, "missing": ["semantic judge result" if "llm_call_failed" in (judge.quality_flags or []) else "attribute LLM result"], "standard": "归因必须基于当前 case 的 judge、trace 和可验证链路证据。"},
            incomplete_reason="judge LLM 调用失败，不能产出正式根因。" if "llm_call_failed" in (judge.quality_flags or []) else "attribute agent LLM 调用失败。",
            suspected_locations=[],
            root_cause_hypothesis="语义 judge 或 attribute agent 调用失败，当前只能确认执行 trace，无法完成正式归因。",
            verification_steps=["检查 LLM API key、余额、网络和模型配置。", "恢复 LLM 后重新运行 judge 和 attribute agent。"],
            patch_direction=["修复 LLM 调用配置或费用问题；不要把该兜底结果当作最终业务根因。"],
            business_impact="当前 case 需要人工复核，不能进入正式失败根因聚簇。",
            primary_error_type="needs_human_review",
            error_types=["needs_human_review"],
            severity="unknown",
            needs_human_review=True,
            scenario=str(trace.project_fields.get("scenario") or ""),
            quality_flags=[*(judge.quality_flags or []), "attribute_blocked"],
            raw_model_output=data,
        )
    primary_error_type = str(data.get("primary_error_type") or data.get("failure_category") or "未归因")
    taxonomy = _taxonomy(spec)
    if taxonomy and primary_error_type not in taxonomy:
        primary_error_type = "needs_human_review" if "needs_human_review" in taxonomy else primary_error_type
    error_types = [str(item) for item in list(data.get("error_types") or [])]
    if taxonomy:
        error_types = [item for item in error_types if item in taxonomy]
    if primary_error_type and primary_error_type != "none" and primary_error_type not in error_types:
        error_types.append(primary_error_type)
    incomplete_reason = _normalize_incomplete_reason(data)
    result = AttributeResult(
        trace_id=trace.trace_id,
        project_id=trace.project_id,
        case_id=str(trace.input.get("case_id") or ""),
        expectation_attributions=list(data.get("expectation_attributions") or []),
        causal_category=str(data.get("causal_category") or primary_error_type or ""),
        probe_results=list(data.get("probe_results") or []),
        failure_category=str(data.get("failure_category") or "未归因"),
        failure_stage=str(data.get("failure_stage") or "不确定"),
        analysis_method=str(data.get("analysis_method") or "current_case_llm_attribute"),
        evidence_chain=list(data.get("evidence_chain") or []),
        trace_analysis=list(data.get("trace_analysis") or trace.execution_trace or []),
        chain_nodes=list(data.get("chain_nodes") or []),
        local_verifications=list(data.get("local_verifications") or []),
        earliest_divergence=dict(data.get("earliest_divergence") or {}),
        evidence_coverage=dict(data.get("evidence_coverage") or {}),
        analysis_quality=dict(data.get("analysis_quality") or {}),
        incomplete_reason=incomplete_reason,
        suspected_locations=list(data.get("suspected_locations") or []),
        root_cause_hypothesis=str(data.get("root_cause_hypothesis") or ""),
        verification_steps=list(data.get("verification_steps") or []),
        patch_direction=list(data.get("patch_direction") or []),
        business_impact=str(data.get("business_impact") or ""),
        primary_error_type=primary_error_type,
        error_types=error_types,
        severity=str(data.get("severity") or ""),
        needs_human_review=data.get("needs_human_review"),
        scenario=str(data.get("scenario") or trace.project_fields.get("scenario") or ""),
        quality_flags=list(data.get("quality_flags") or []),
        raw_model_output=data,
    )
    return normalize_attribute_trace_result(spec, trace, judge, result)
