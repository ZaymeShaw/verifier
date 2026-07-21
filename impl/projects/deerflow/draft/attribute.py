from __future__ import annotations

import importlib.util
from pathlib import Path

from impl.core.schema import JudgeResult, RunTrace


_PRODUCTION_PATH = Path(__file__).resolve().parents[1] / "attribute.py"
_SPEC = importlib.util.spec_from_file_location("deerflow_production_attribute_for_draft", _PRODUCTION_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load production deerflow Attribute: {_PRODUCTION_PATH}")
_PRODUCTION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PRODUCTION)
_ProductionAttribute = _PRODUCTION.DeerflowAttribute


def _latest_user_text(request: object) -> str:
    if not isinstance(request, dict):
        return ""
    input_value = request.get("input")
    if not isinstance(input_value, dict):
        return ""
    messages = input_value.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        return content.strip() if isinstance(content, str) else ""
    return ""


def _clarification_sequence(trace: RunTrace) -> list[dict]:
    sequence: list[dict] = []
    for index, turn in enumerate(trace.turn_records or [], start=1):
        if not isinstance(turn, dict):
            continue
        extracted = turn.get("extracted_output")
        if not isinstance(extracted, dict):
            extracted = {}
        questions = []
        for call in extracted.get("tool_calls") or []:
            if not isinstance(call, dict) or call.get("name") != "ask_clarification":
                continue
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            questions.append(str(args.get("question") or "").strip())
        sequence.append({
            "turn_index": turn.get("turn_index") or index,
            "user_text": _latest_user_text(turn.get("request")),
            "ask_clarification_questions": [item for item in questions if item],
            "reply_text": str(extracted.get("reply_text") or "").strip(),
            "stage": str(extracted.get("stage") or "unknown"),
            "call_status": str(turn.get("call_status") or ""),
        })
    return sequence


def _failed_business_output(trace: RunTrace, judge_result: JudgeResult) -> dict:
    failed = []
    for assessment in judge_result.fulfillment_assessments or []:
        def field(name: str, default: object = None) -> object:
            if isinstance(assessment, dict):
                return assessment.get(name, default)
            return getattr(assessment, name, default)

        status = field("status")
        if status != "not_fulfilled":
            continue
        failed.append({
            "expectation_id": str(field("expectation_id", "") or ""),
            "expected_evidence": list(field("expected_evidence", []) or []),
            "actual_evidence": list(field("actual_evidence", []) or []),
        })
    output = trace.extracted_output if isinstance(trace.extracted_output, dict) else {}
    return {
        "final_reply_text": str(output.get("reply_text") or ""),
        "final_tool_calls": list(output.get("tool_calls") or []),
        "final_scripts_called": list(output.get("scripts_called") or []),
        "not_fulfilled_assessments": failed,
    }


class DeerflowDraftAttribute(_ProductionAttribute):
    """Candidate that routes each Judge gap to the matching deerflow business branch."""

    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> dict:
        from impl.core.project_loader import load_project_role_tools

        context = dict(super().build_context(trace, judge_result) or {})
        # Keep the decisive raw/stored comparison small enough for Search,
        # Finalization and Reviewer to consume without loading a full historical
        # Gateway message history.  Stage-only differences are deliberately not
        # included: an intermediate stored ``unknown`` does not by itself prove a
        # repair-relevant defect.
        extraction_deltas = []
        for probe in _PRODUCTION._deerflow_integrity_probes(trace, judge_result):
            if not str(probe.get("probe_id") or "").startswith("deerflow_turn_"):
                continue
            reply_mismatch = probe.get("raw_vs_extracted_reply_match") is False
            tool_mismatch = probe.get("raw_vs_extracted_tool_calls_match") is False
            if not (reply_mismatch or tool_mismatch):
                continue
            extraction_deltas.append({
                "turn_index": probe.get("turn_index"),
                "raw_reply_matches": not reply_mismatch,
                "raw_tool_names": list(probe.get("raw_tool_names") or []),
                "extracted_tool_names": list(probe.get("extracted_tool_names") or []),
                "stored_stage": probe.get("extracted_stage"),
                "raw_replay_stage": probe.get("inferred_stage"),
                "raw_replay_stage_rule": probe.get("stage_inference_rule"),
            })
        runtime_checks = dict(context.get("runtime_checks") or {})
        runtime_checks["decisive_extraction_deltas"] = extraction_deltas
        runtime_checks["clarification_sequence"] = _clarification_sequence(trace)
        runtime_checks["failed_business_output"] = _failed_business_output(trace, judge_result)
        context["runtime_checks"] = runtime_checks
        context.update({
            "tools": list(load_project_role_tools(self.spec, "attribute") or []),
            "tool_call_limit": 5,
            "system_prompt_override": """你是 deerflow 项目的 Draft Attribute 主执行者。
先读当前 not_fulfilled expectations、逐轮输出和 runtime_checks，再选择一条与当前 business gap 匹配的调查分支；不得因为某个静态 Investigation ContextUnit 存在就默认它是当前根因。第一次 Search 只查询当前分支需要的材料，然后 Load 对应文字 flow 和 runtime_checks；不要为了凑证据加载无关 ContextUnit。

证据状态规则：`raw_message_history_unrecorded_turns` 表示当前 RunTrace 投影没有保存 Gateway 原始消息历史，是“无法比较”，绝不等于 Gateway 返回空消息。只有 `decisive_extraction_deltas` 非空，才能进入 MESSAGE_HISTORY → extraction 分支；该列表只允许包含原始业务 AI 消息真实存在且 raw/stored reply 或 tools 明确不同的 turn。列表为空时不得归因 reply/tool/stage extraction，也不得把 extracted_output 称为 verifier 虚构。exact raw messages 可得且重放能区分竞争解释时，才调用 deerflow.message_history_replay。

若 gap 是信息已补充但仍反复澄清或没有进入规划，进入 `deerflow clarification-to-planning flow`：第一次 Search 必须同时查询 `deerflow clarification-to-planning flow` 和 `clarification_sequence current case runtime_checks`；只 Load 文字 flow 与 runtime_checks，不 Load Mermaid。用 clarification_sequence 证明各轮用户输入和实际澄清行为。源码材料使用 source_file_catalog 中的精确 key `project_doc:source_lead_agent_prompt`，通过 source_search_text 查询 `PRIORITY CHECK`、`Only after all clarifications are resolved` 或 `DO NOT skip clarification`，不要改读 backend/CLAUDE.md。静态 prompt 与行为同时存在只能确定修复候选；没有部署 revision 对齐或局部干预/重放，不得声称 prompt 已被证明为当前 case 唯一根因。

若 gap 是上传、脚本执行、结果交付等其他业务机制，应以对应业务链路为查询词继续使用通用 source/context tools；不要硬套 extraction 或 clarification 分支。NBEV skill 文档存在不能证明它被选中，Judge reference 中虚构或非当前项目脚本名也不能证明业务缺陷。若部署 revision、skill 选择或隐藏模型执行无法从当前 trace 对齐，必须写 unresolved_reason。

若 gap 是预算、计数、比例或其他可由当前业务输出直接重算的约束，不先搜源码。先用精确查询 `failed_business_output current case runtime_checks` 找到并 Load 当前 case 的 runtime_checks ContextUnit，使原始业务输出进入可引用证据链；然后调用对应确定性验证 Tool。预算场景调用 deerflow.budget_reconcile，并把已加载业务输出中每个成本项的原文放入 source_quote。Finalization 的 finding 必须同时引用 runtime_checks 原始业务输出和预算 Tool 重算结果；只有 Tool 结果不够，因为 Tool 参数和 source_quote 是模型转写。一个可复算的成本遗漏本身就是修复相关的业务机制 finding：结论写“哪个成本项未进入聚合、实际总额与约束差多少、预算 invariant 未被执行”，不得升级为“模型数学能力缺陷”或“prompt 缺陷”，除非另有干预证据。

只调查 not_fulfilled expectation，按一个真实缺陷合并 findings。finding 必须能指向会改变修复方案的业务或 verifier 机制，并引用 Finalization 重载的 ContextUnit。fulfilled case 不产 finding。""",
        })
        extras = dict(context.get("user_prompt_extras") or {})
        strategy = dict(extras.get("project_attribute_strategy") or {})
        strategy.update({
            "investigation_entry": "Select the matching deerflow flow from the current Judge gap; extraction is only one branch.",
            "field_ownership": "Gateway owns raw AI messages; verifier derives reply/tool/scripts/stage compact fields.",
            "branch_policy": "confirmed raw/stored mismatch -> extraction; repeated clarification -> clarification/planning; otherwise follow the matching business mechanism",
            "anti_overfit_policy": "Unrecorded raw history, historical trace, source presence, expected tool name, or derived stage alone cannot prove current-case cause.",
        })
        extras["project_attribute_strategy"] = strategy
        context["user_prompt_extras"] = extras
        return context
