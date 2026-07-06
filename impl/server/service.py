from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..core import case_pool, context_store, pipeline
from ..core.config import CONFIG_PATH, get_runtime_config
from ..core.project_loader import list_projects
from ..core.schema import (
    BatchRunResult,
    CasePoolSaveResponse,
    CasePoolsResponse,
    MockBuildResponse,
    MockCasesResponse,
    MockDatasetsResponse,
    RunChainResponse,
    normalize_attribute_result,
    normalize_attribute_results,
    normalize_case_pool_table,
    normalize_check_report,
    normalize_cluster_summary,
    normalize_frontend_view,
    normalize_judge_result,
    normalize_run_trace,
    to_dict,
)
from ..core.table_view import build_case_pool_table_from_runs, build_trace_table_row, build_trace_table_row_from_run
SERVER_STARTED_AT = time.time()


def _config_hash() -> str:
    if not CONFIG_PATH.exists():
        return ""
    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()[:12]


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def project_from(data: Dict[str, Any]) -> str:
    return str(data.get("project") or data.get("project_id") or "")


def compact_mapping(value: Any) -> Any:
    if isinstance(value, list):
        return [compact_mapping(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: compact_mapping(item)
        for key, item in value.items()
        if key not in {"raw_text", "raw_response", "downstream_payload", "raw_sections", "raw_sse", "raw_cards", "raw_model_text", "frontend_view"}
    }


def compact_run(run: Dict[str, Any]) -> Dict[str, Any]:
    trace_obj = normalize_run_trace(run.get("trace"))
    judge_obj = normalize_judge_result(run.get("judge"))
    attribute_obj = normalize_attribute_result(run.get("attribute"))
    check_obj = normalize_check_report(run.get("check"))
    frontend_view_obj = normalize_frontend_view(run.get("frontend_view"))
    cluster_obj = normalize_cluster_summary(run.get("cluster"))
    trace = to_dict(trace_obj) if trace_obj else {}
    judge = compact_mapping(to_dict(judge_obj) if judge_obj else {})
    attribute = compact_mapping(to_dict(attribute_obj) if attribute_obj else {})
    frontend_view = to_dict(frontend_view_obj) if frontend_view_obj else {}
    frontend_view.pop("raw_sections", None)
    compact_trace = dict(trace)
    compact_trace.pop("raw_response", None)
    compact_trace["schema_protocol_extensions"] = compact_mapping(compact_trace.pop("project_fields", {}) or {})
    live_result = trace.get("live_result") if isinstance(trace.get("live_result"), dict) else {}
    compact = {
        "case_id": trace.get("case_id") or run.get("case_id"),
        "execution_mode": trace.get("execution_mode") or run.get("execution_mode"),
        "output_source": trace.get("output_source") or run.get("output_source") or live_result.get("output_source"),
        "trace_id": trace.get("trace_id"),
        "trace": compact_trace,
        "judge": judge,
        "attribute": attribute,
        "cluster": to_dict(cluster_obj) if cluster_obj else None,
        "check": to_dict(check_obj) if check_obj else None,
        "frontend_view": frontend_view,
        "error": run.get("error"),
    }
    table_row = build_trace_table_row_from_run(compact)
    compact["table_row"] = to_dict(table_row)
    compact["status"] = table_row.status
    return compact


def compact_batch_result(batch_result: Any) -> Dict[str, Any]:
    data = to_dict(batch_result)
    data["runs"] = [compact_run(run) for run in data.get("runs", [])]
    if data.get("table"):
        data["table"] = to_dict(normalize_case_pool_table(data.get("table")))
    else:
        data["table"] = to_dict(build_case_pool_table_from_runs(data.get("project_id", ""), data["runs"]))
    return data


def case_event(index: int, run: Dict[str, Any]) -> Dict[str, Any]:
    compact = compact_run(run)
    table_row = compact.get("table_row") or {}
    judge_summary = table_row.get("judge_summary") or {}
    attribution_summary = table_row.get("attribution_summary") or {}
    reason = attribution_summary.get("summary_text") or judge_summary.get("reason") or compact.get("error") or ""
    return {
        "index": index,
        "case_id": compact.get("case_id"),
        "status": table_row.get("fulfillment_status") or table_row.get("status") or compact.get("status") or "",
        "error": compact.get("error") or (compact.get("trace") or {}).get("error") or "",
        "reason": reason,
        "reason_source": attribution_summary.get("causal_category") or judge_summary.get("reason_source") or "",
        "reason_stage": table_row.get("divergence_stage") or judge_summary.get("reason_stage") or "",
        "is_formal_attribution": bool(attribution_summary.get("is_formal_attribution", False)),
        "judge_reason": judge_summary.get("reason") or "",
        "judge_reason_source": judge_summary.get("reason_source") or "",
        "judge_reason_stage": judge_summary.get("reason_stage") or "",
        "run": compact,
    }


def health() -> Dict[str, Any]:
    runtime_config = get_runtime_config()
    return {
        "status": "ok",
        "pid": os.getpid(),
        "started_at": datetime.fromtimestamp(SERVER_STARTED_AT, tz=timezone.utc).isoformat(),
        "config_hash": _config_hash(),
        "code_version": _git_commit(),
        "server": {
            "host": runtime_config.server.host,
            "port": runtime_config.server.port,
        },
        "uat": {
            "host": runtime_config.uat.host,
            "port": runtime_config.uat.port,
        },
    }


def projects() -> Dict[str, Any]:
    return {"projects": list_projects()}


def analysis(data: Dict[str, Any]) -> Any:
    return pipeline.analysis(project_from(data))


def live_run(data: Dict[str, Any]) -> Any:
    return pipeline.live_run(project_from(data), data.get("input") or {})


def mock_cases(data: Dict[str, Any]) -> MockCasesResponse:
    project = project_from(data)
    return MockCasesResponse(project_id=project, cases=pipeline.mock_cases(project))


def mock_datasets(data: Dict[str, Any]) -> MockDatasetsResponse:
    project = project_from(data)
    return MockDatasetsResponse(project_id=project, datasets=pipeline.mock_datasets(project))


def mock_build_intent(data: Dict[str, Any]) -> MockBuildResponse:
    project = project_from(data)
    case = pipeline.mock_build_intent(
        project,
        scenario=data.get("scenario") or "",
        intent_labels=data.get("intent_labels") or [],
        template=data.get("template"),
        required_input_fields=data.get("required_input_fields") or [],
    )
    return MockBuildResponse(project_id=project, case=case)


def mock_build_interaction(data: Dict[str, Any]) -> MockBuildResponse:
    project = project_from(data)
    case = pipeline.mock_build_interaction(
        project,
        intent_result=data.get("intent_result") or {},
        live_context=data.get("live_context") or {},
        previous_turns=data.get("previous_turns") or [],
    )
    return MockBuildResponse(project_id=project, case=case)


def list_case_pools(data: Dict[str, Any]) -> CasePoolsResponse:
    project = project_from(data)
    return CasePoolsResponse(project_id=project, pools=case_pool.list_case_pools(project))


def save_case_pool(data: Dict[str, Any]) -> CasePoolSaveResponse:
    saved = case_pool.save_case_pool(project_from(data), data.get("name") or "", data.get("cases") or [])
    return CasePoolSaveResponse(id=saved.get("id", ""), name=saved.get("name", ""), cases=saved.get("cases", []))


def load_case_pool(data: Dict[str, Any]) -> Any:
    return case_pool.load_case_pool(project_from(data), data.get("id") or "")


def delete_case_pool(data: Dict[str, Any]) -> Any:
    return case_pool.delete_case_pool(project_from(data), data.get("id") or "")


def judge(data: Dict[str, Any]) -> Any:
    return pipeline.judge(project_from(data), normalize_run_trace(data.get("trace")), data.get("expected_intent"))


def attribute(data: Dict[str, Any]) -> Any:
    return pipeline.attribute(project_from(data), normalize_run_trace(data.get("trace")), normalize_judge_result(data.get("judge")))


def cluster(data: Dict[str, Any]) -> Any:
    return pipeline.cluster(project_from(data), normalize_attribute_results(data.get("attributes", [])))


def check(data: Dict[str, Any]) -> Any:
    return pipeline.check(
        project_from(data),
        normalize_run_trace(data.get("trace")) if data.get("trace") else None,
        normalize_judge_result(data.get("judge")) if data.get("judge") else None,
        normalize_attribute_result(data.get("attribute")) if data.get("attribute") else None,
        normalize_cluster_summary(data.get("cluster")) if data.get("cluster") else None,
    )


def run_chain(data: Dict[str, Any]) -> RunChainResponse:
    run = pipeline.run_chain(project_from(data), data.get("input") or {}, expected_intent=data.get("expected_intent"))
    return RunChainResponse(
        trace=normalize_run_trace(run.get("trace")),
        judge=normalize_judge_result(run.get("judge")),
        attribute=normalize_attribute_result(run.get("attribute")) if run.get("attribute") else None,
        cluster=normalize_cluster_summary(run.get("cluster")) if run.get("cluster") else None,
        check=normalize_check_report(run.get("check")) if run.get("check") else None,
        frontend_view=normalize_frontend_view(run.get("frontend_view")) if run.get("frontend_view") else None,
        table_row=build_trace_table_row_from_run(run) if not run.get("table_row") else run.get("table_row"),
    )


def batch_run(data: Dict[str, Any]) -> BatchRunResult:
    concurrency = max(1, min(int(data.get("concurrency") or 4), 8))
    result = pipeline.batch_run(project_from(data), data.get("cases") or data.get("inputs") or [], expected_intent=data.get("expected_intent"), concurrency=concurrency)
    return BatchRunResult(
        project_id=result.project_id,
        total=result.total,
        runs=result.runs,
        cluster=normalize_cluster_summary(result.cluster) if result.cluster else None,
        check=normalize_check_report(result.check) if result.check else None,
        table=normalize_case_pool_table(result.table) if result.table else None,
        fallbacks=result.fallbacks,
    )


def frontend_view(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    return pipeline.frontend_view(
        project,
        normalize_run_trace(data.get("trace")) if data.get("trace") else None,
        normalize_judge_result(data.get("judge")) if data.get("judge") else None,
        normalize_attribute_result(data.get("attribute")) if data.get("attribute") else None,
        normalize_cluster_summary(data.get("cluster")) if data.get("cluster") else (pipeline.cluster(project, normalize_attribute_results(data.get("attributes", []))) if data.get("attributes") else None),
        normalize_check_report(data.get("check")) if data.get("check") else None,
    )


def trace_view(data: Dict[str, Any]) -> Any:
    if data.get("trace"):
        return normalize_run_trace(data.get("trace"))
    if data.get("run") and isinstance(data.get("run"), dict):
        return normalize_run_trace((data.get("run") or {}).get("trace"))
    return pipeline.live_run(project_from(data), data.get("input") or {})


def table_view(data: Dict[str, Any]) -> Any:
    project = project_from(data)
    if data.get("runs"):
        return build_case_pool_table_from_runs(project, data.get("runs") or [])
    if data.get("run"):
        return build_trace_table_row_from_run(data.get("run") or {})
    trace = normalize_run_trace(data.get("trace")) if data.get("trace") else None
    if not trace:
        return build_case_pool_table_from_runs(project, [])
    return build_trace_table_row(
        trace,
        normalize_judge_result(data.get("judge")) if data.get("judge") else None,
        normalize_attribute_result(data.get("attribute")) if data.get("attribute") else None,
        normalize_frontend_view(data.get("frontend_view") or data.get("view")) if (data.get("frontend_view") or data.get("view")) else None,
        normalize_check_report(data.get("check")) if data.get("check") else None,
        case_context=data.get("case_context") if isinstance(data.get("case_context"), dict) else None,
    )


def list_context_summaries(project_id: str, *, caller: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """列出某项目最近的 LLM 上下文调用摘要（不含 prompt 全量）。"""
    summaries = context_store.list_recent_contexts(project_id, caller=caller, limit=limit)
    return [to_dict(s) for s in summaries]


def list_contexts_by_trace(project_id: str, trace_id: str) -> List[Dict[str, Any]]:
    """某次 trace 的完整 LLM 上下文链（按时间排序，含 prompt 全量）。"""
    records = context_store.load_contexts_by_trace(project_id, trace_id)
    return [to_dict(r) for r in records]


def get_context(project_id: str, trace_id: str, caller: str) -> Dict[str, Any]:
    """某次 trace 中某个 agent 的上下文记录（含 prompt 全量）。"""
    record = context_store.load_context(project_id, trace_id, caller)
    return to_dict(record) if record else {}


def analyze_contexts(data: Dict[str, Any]) -> Dict[str, Any]:
    """L3 LLM 内容分析：取若干条 ContextRecord 拼成分析 prompt 调 LLM。

    防递归：分析调用本身会经过 LlmClient，会被 _track_context 记录成一条
    caller="context_analyzer" 的 ContextRecord。分析 prompt 里明确标注这些是
    待分析样本，避免与正常 agent 调用混淆。
    """
    project_id = str(data.get("project_id") or data.get("project") or "default")
    caller = str(data.get("caller") or "")
    analysis_type = str(data.get("analysis_type") or "redundancy")
    sample_size = max(1, min(10, int(data.get("sample_size") or 3)))
    if not caller:
        return {"error": "caller is required"}
    summaries = context_store.list_recent_contexts(project_id, caller=caller, limit=sample_size * 3)
    if not summaries:
        return {"error": f"no context records for caller={caller} project={project_id}"}
    # 取最近 N 条，按时间倒序
    summaries.sort(key=lambda r: r.created_at, reverse=True)
    picked = summaries[:sample_size]
    # 加载完整记录（含 prompt/response）
    samples = []
    for s in picked:
        full = context_store.load_context(project_id, s.trace_id, s.caller)
        if full:
            samples.append(full)
    if not samples:
        return {"error": "failed to load full context records"}
    system, user = _build_analyze_prompt(analysis_type, caller, samples)
    from .llm_bridge import llm_client_for_analysis
    from ..core.structured_output import FREE_TEXT_OUTPUT
    client = llm_client_for_analysis(project_id)
    # context-analyze 是自由文本分析，无固定结构，用 FREE_TEXT_OUTPUT（单字段 result: str）
    result = client.complete_json(system, user, trace_id=f"context-analyze-{caller}", output_spec=FREE_TEXT_OUTPUT)
    analysis_text = ""
    if isinstance(result, dict):
        if result.get("error"):
            return {"error": result.get("error"), "raw_text": result.get("raw_text", "")}
        analysis_text = str(result.get("analysis") or result.get("summary") or result.get("reasoning_summary") or "")
        if not analysis_text:
            analysis_text = json.dumps(result, ensure_ascii=False)
    else:
        analysis_text = str(result)
    return {"analysis": analysis_text, "caller": caller, "analysis_type": analysis_type, "sample_count": len(samples)}


def _build_analyze_prompt(analysis_type: str, caller: str, samples: List[Any]) -> tuple:
    type_desc = {
        "redundancy": "检测这些 system_prompt 里常驻部分是否过大、是否有可压缩的冗余内容，给出具体可删减的段落",
        "quality": "对 response 做语义抽样，判断 LLM 输出是否有退化迹象（如空泛、重复、不遵循 schema）",
        "consistency": "对比同一 caller 不同 trace 的 prompt 结构差异，指出哪些部分应该固定却变了",
    }.get(analysis_type, "分析这些上下文记录")
    system = (
        "你是通用评估系统的上下文分析器。下面是某个 agent 的若干条 LLM 上下文记录样本。\n"
        f"分析任务：{type_desc}。\n"
        "每条记录包含 system_prompt / user_prompt / response / prompt_size / elapsed_ms / error。\n"
        "只基于样本内容分析，不要编造未提供的信息。输出 JSON，包含字段 analysis（中文分析结论）。\n"
    )
    user_parts = [f"caller={caller} analysis_type={analysis_type} sample_count={len(samples)}"]
    for i, s in enumerate(samples, 1):
        msgs = s.messages or []
        sys_msg = next((m for m in msgs if m.get("role") == "system"), {})
        usr_msg = next((m for m in msgs if m.get("role") == "user"), {})
        user_parts.append(
            f"\n--- 样本 {i} (trace_id={s.trace_id} prompt_size={s.prompt_size} elapsed_ms={s.elapsed_ms} error={s.error or 'none'}) ---\n"
            f"system_prompt:\n{str(sys_msg.get('content') or '')[:8000]}\n\n"
            f"user_prompt:\n{str(usr_msg.get('content') or '')[:4000]}\n\n"
            f"response:\n{json.dumps(s.response, ensure_ascii=False)[:4000]}\n"
        )
    return system, "\n".join(user_parts)
