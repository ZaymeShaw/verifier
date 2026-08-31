from __future__ import annotations

from impl.core.context.embedding import DeterministicHashEmbeddingProvider
from impl.core.project_loader import load_project
from impl.core.schema import RunTrace
from impl.projects.client_search.judge import (
    _build_core_context as build_draft_context,
)
from impl.projects.client_search.judge_execution import (
    judge_trace as draft_judge_trace,
)
from impl.projects.client_search.live import capability_manifest


class _NoopJudgeLlm:
    model = "test-model"
    _project_id = "client_search"

    def __init__(self) -> None:
        self.tools = []
        self.system = ""

    def complete_json(self, system, _user, **_kwargs):
        self.system = system
        return {
            "business_expectations": [],
            "applicable_product_expectation_ids": [],
            "fulfillment_assessments": [],
            "expected": None,
            "missing": [],
            "wrong": [],
            "extra": [],
            "evidence": [],
            "reasoning_summary": "当前请求不属于客户搜索。",
        }


def _trace(trace_id: str) -> RunTrace:
    return RunTrace(
        trace_id=trace_id,
        project_id="client_search",
        input={"user_text": "你好"},
        normalized_request={"user_text": "你好"},
        extracted_output={},
        ready=["reference_contract_optional"],
    )


def test_draft_compiler_blocks_nothing_when_contract_and_tool_plan_are_consistent():
    spec = load_project("client_search")
    trace = _trace("context-governance-draft")
    context = build_draft_context(
        spec,
        trace,
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )
    client = _NoopJudgeLlm()
    client.tools = list(context["tools"])

    draft_judge_trace(
        spec,
        trace,
        llm=client,
        project_judge_context=context,
    )

    report = client._context_governance_report
    assert report["gate"] == {"mode": "draft", "blocking": False}
    assert report["findings"] == []
    assert "`JudgeResult` 协议字段" not in client.system
    assert report["snapshot"]["tool_plan"]


def _field_trace(trace_id: str) -> RunTrace:
    return RunTrace(
        trace_id=trace_id,
        project_id="client_search",
        input={"query": "徐晓燕"},
        normalized_request={"query": "徐晓燕"},
        extracted_output={
            "query_logic": "AND",
            "conditions": [
                {"field": "searchClientName", "operator": "MATCH", "value": "徐晓燕"},
            ],
        },
    )


def test_draft_judge_system_has_intent_decomposition_and_evidence_grading():
    spec = load_project("client_search")
    trace = _field_trace("context-governance-judge-directives")
    context = build_draft_context(spec, trace)
    client = _NoopJudgeLlm()
    client.tools = list(context["tools"])

    draft_judge_trace(
        spec,
        trace,
        llm=client,
        project_judge_context=context,
    )

    system = client.system
    assert "### 意图拆解" in system
    assert "### 证据分级" in system
    assert "### 裸词规则" not in system
    assert "独立姓名证据" not in system
    assert "再搜下一个约束" in system
    assert "不要继续 Search" not in system
    assert "只有实际引用到的二级证据才能支撑 fulfilled" in system
    assert "不得仅因字段名不在清单中" in system
    assert "规则优先于自然语言推断" not in system
    assert "该项目确定性规则优先" not in system
    assert "inlive 空间列出的操作符或 match_mode 只证明可达" in system


def test_draft_judge_intent_frame_uses_compact_manifest_not_full():
    spec = load_project("client_search")
    trace = _field_trace("context-governance-compact-manifest")
    context = build_draft_context(spec, trace)

    intent_manifest = context["intent_frame"]["capability_manifest"]
    extras_manifest = context["user_prompt_extras"]["capability_manifest"]
    assert intent_manifest == extras_manifest
    assert intent_manifest
    full_manifest = capability_manifest(spec, full=True)
    assert set(intent_manifest) < set(full_manifest)


def test_draft_judge_authority_disabled_keeps_only_mode_marker():
    spec = load_project("client_search")
    trace = _field_trace("context-governance-authority-disabled")
    context = build_draft_context(spec, trace)

    extras = context["user_prompt_extras"]
    assert extras["authority_mode"] in {"disabled_with_candidates", "not_required"}
    assert "authority_candidate_reasons" not in extras
    assert "authority_obligation_contract" not in extras
