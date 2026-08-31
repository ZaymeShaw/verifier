from __future__ import annotations

import json

import pytest

from impl.core.context.project import load_role_mandatory_context
from impl.core.context.embedding import DeterministicHashEmbeddingProvider
from impl.core.investigation import (
    load_judge_solidify_investigation_projection,
    validate_investigation_package,
)
from impl.core.project_loader import load_project
from impl.core.schema import AuthorityResolution, RunTrace
from impl.projects.client_search.draft.probes.judge_solidify_probe import (
    FORBIDDEN_RUNTIME_FIELDS,
    build_probe_payload,
)


def _authority_spec():
    """Return the client_search spec with in-run authority scopes enabled.

    Draft Judge default enables only post-judge capability_carrier;
    in-run authority stays off. Tests that exercise authority
    assembly/consumption must opt the in-run scopes back in.
    """
    spec = load_project("client_search")
    authority = (spec.verifier or {}).setdefault("authority", {})
    authority["enabled_scopes"] = [
        "responsibility",
        "semantic_mapping",
        "query_equivalence",
        "conflict_arbitration",
    ]
    return spec

def test_client_search_judge_solidify_projection_matches_smoke_evidence(monkeypatch):
    spec = _authority_spec()
    project_root = spec.project_package_path(
        ".",
        field_path="project.package",
        expected_type="directory",
    )
    package = spec.project_package_path(
        "investigation/judge",
        field_path="verifier.assets.investigation.judge",
        expected_type="directory",
    )
    try:
        validate_investigation_package(
            package,
            project_root=project_root,
            expected_project_id="client_search",
            expected_role="judge",
            source_root=spec.source_root_path() if spec.has_business_source else None,
        )
    except ValueError as exc:
        message = str(exc)
        if "source_revision does not match" in message or "content hash changed" in message:
            pytest.skip(message)
        raise
    runtime = load_judge_solidify_investigation_projection(
        spec, use_candidate=True
    )
    from impl.projects.client_search.draft.probes import judge_solidify_probe as probe_mod

    def _echo_replay(_env, probes):
        return {
            "probe_results": [
                {
                    "probe_id": str(item.get("probe_id") or ""),
                    "subject_id": str(item["subject_id"]),
                    "status": str(item["expected_status"]),
                    "statement": "",
                    "reason": "unit-test replay",
                    "tool_call_id": f"probe:{item.get('probe_id')}",
                    "tool_audit_present": True,
                    "environment_snapshot_sha256": "test",
                    "basis_evidence_ref_ids": [],
                    "required_evidence": [],
                }
                for item in probes
            ]
        }

    monkeypatch.setattr(probe_mod, "_run_authority_replay", _echo_replay)
    evidence = build_probe_payload()

    assert runtime["business_contract"]["business_expectations"][0]["expectation_id"] == (
        "find-target-customers"
    )
    # 新方案：调查交接=证据空间（business_contract + 权威调查报告），
    # runtime 不承载 authority 约束/决议资产，authority 判断现场 resolve。
    assert "authority" not in runtime
    assert FORBIDDEN_RUNTIME_FIELDS

    assert evidence["status"] == "succeeded"
    assert evidence["checks"]["authority_snapshot_sha256"]
    assert evidence["checks"]["report"]["materials"] == 15
    assert evidence["checks"]["report"]["coverage_gaps"] == 6
    authorities = evidence["checks"]["authorities"]
    assert {item["analysis_id"] for item in authorities.values()} == {
        "semantic-mapping-authority",
        "query-form-equivalence-authority",
        "responsibility-boundary-unsupported-field",
        "responsibility-boundary-entity-name-query",
        "silently-dropped-request-dimension",
        "enum-space-search-consumption-boundary",
    }
    assert all(item["dimension_ids"] for item in authorities.values())
    assert all(item["required_evidence"] for item in authorities.values())
    for check in authorities.values():
        assert check["case_time"] == {
            "without_decisive_evidence": "not_evaluable",
        }


def test_authority_probe_questions_declare_in_run_class():
    from impl.projects.client_search.draft.probes.judge_solidify_probe import (
        _AUTHORITY_PROBE_CLASSES,
        _AUTHORITY_PROBE_QUESTIONS,
        _IN_RUN_SCOPES,
    )

    assert set(_AUTHORITY_PROBE_CLASSES) == set(_AUTHORITY_PROBE_QUESTIONS)
    assert set(_AUTHORITY_PROBE_CLASSES.values()) <= set(_IN_RUN_SCOPES)


def test_client_search_runtime_loads_solidified_authority_context_not_investigation_dump():
    spec = load_project("client_search")

    context = load_role_mandatory_context(
        spec,
        role="judge",
        operation="judge",
        trace_id="authority-context-test",
        run_id="authority-context-test",
    )

    assert context is not None
    assert "project.client_search.asset.judge_business_contract" in context["unit_ids"]
    assert "project.client_search.asset.judge_authority_enum_values" not in context["unit_ids"]
    assert not any("judge_investigation" in item for item in context["unit_ids"])
    assert "client_search.authority.enum-values" not in context["content"]


def test_client_search_builds_comparator_evidence_before_assessment(monkeypatch):
    """Draft 单次上下文：comparator 证据与 authority.resolve 工具一起进入同一会话。"""
    from impl.projects.client_search import judge as candidate_module

    spec = _authority_spec()
    comparison = {
        "outputs": {
            "wrong": [],
            "missing": [{"field": "age"}],
            "extra": [],
        }
    }
    monkeypatch.setattr(candidate_module, "condition_comparison", lambda *_: comparison)

    context = candidate_module._build_core_context(
        spec,
        RunTrace(
            trace_id="trace-comparator",
            project_id="client_search",
            input={"query": "30岁以上女性客户"},
            extracted_output={"conditions": [{"field": "sex"}]},
        ),
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )

    assert context["comparator_result"] is comparison
    assert context["user_prompt_extras"]["condition_comparison"] == comparison
    authority_env = context["authority_environment"]
    assert authority_env.environment_snapshot_sha256
    assert context["environment_snapshot_sha256"] == (
        authority_env.environment_snapshot_sha256
    )
    tool_names = {getattr(tool, "name", "") for tool in context["tools"]}
    assert "authority_resolve" in tool_names
    assert "investigation_search_index" in tool_names
    assert "investigation_load_entry" in tool_names


def test_comparator_does_not_self_authorize():
    from impl.projects.client_search.judge import condition_comparison

    comparison = condition_comparison(
        load_project("client_search"),
        RunTrace(
            trace_id="trace-current-oracle",
            project_id="client_search",
            input={"query": "帮我找高净值客户"},
            reference_contract={
                "oracle": "current",
                "expected_conditions": [
                    {
                        "field": "clientLevel",
                        "operator": "eq",
                        "value": "VIP",
                    }
                ],
            },
            extracted_output={
                "query_logic": "AND",
                "conditions": [
                    {
                        "field": "clientLevel",
                        "operator": "eq",
                        "value": "VIP",
                    }
                ],
            },
            ready=["reference"],
        ),
    )

    assert comparison["status"] == "succeeded"
    assert comparison["outputs"]["evaluable"] is True
    assert "authority_resolutions" not in comparison["outputs"]


def test_non_oracle_reference_is_evidence_only_not_a_comparison_standard():
    from impl.projects.client_search.judge import condition_comparison

    comparison = condition_comparison(
        load_project("client_search"),
        RunTrace(
            trace_id="trace-historical-reference",
            project_id="client_search",
            input={"query": "帮我找高净值客户"},
            reference_contract={
                "oracle": "historical",
                "expected_conditions": [{
                    "field": "clientLevel",
                    "operator": "eq",
                    "value": "VIP",
                }],
            },
            extracted_output={
                "conditions": [{
                    "field": "clientLevel",
                    "operator": "eq",
                    "value": "OTHER",
                }]
            },
            ready=["reference"],
        ),
    )

    outputs = comparison["outputs"]
    assert outputs["expected_source"] == "reference_evidence"
    assert outputs["evaluable"] is False
    assert outputs["wrong"] == []
    assert outputs["missing"] == []
    assert outputs["extra"] == []
    assert "authority_resolutions" not in outputs


def test_comparator_cannot_use_reference_without_trace_readiness():
    from impl.projects.client_search.judge import condition_comparison

    comparison = condition_comparison(
        load_project("client_search"),
        RunTrace(
            trace_id="trace-reference-not-ready",
            project_id="client_search",
            input={"query": "帮我找高净值客户"},
            reference_contract={
                "oracle": "current",
                "expected_conditions": [{
                    "field": "clientLevel",
                    "operator": "eq",
                    "value": "VIP",
                }],
            },
            extracted_output={
                "conditions": [{
                    "field": "clientLevel",
                    "operator": "eq",
                    "value": "VIP",
                }]
            },
            ready=[],
        ),
    )

    assert comparison["outputs"]["evaluable"] is False
    assert "authority_resolutions" not in comparison["outputs"]


def _seed_authority_audit(
    authority_tool,
    call_id: str,
    *,
    status: str,
    reason: str,
    unit_id: str = "ref-a",
    required_evidence: tuple[str, ...] = (),
) -> None:
    authority_tool.audit[call_id] = {
        "request": {"decision_question": "当前判断必须采用哪个业务定义？"},
        "resolution": AuthorityResolution(
            status=status,
            statement="" if status == "unresolved" else "采用当前正式定义。",
            reason=reason,
            basis_evidence_ref_ids=(unit_id,),
            required_evidence=tuple(required_evidence),
        ),
        "environment_snapshot_sha256": authority_tool._env.environment_snapshot_sha256,
    }


class SinglePassJudgeLlm:
    def __init__(self, data):
        self.data = data
        self.calls = 0
        self.call_kwargs = []
        self._caller = "judge"

    def complete_json(self, *_args, **_kwargs):
        self.calls += 1
        self.call_kwargs.append(dict(_kwargs))
        return dict(self.data)


def test_client_search_runtime_applies_traceable_authority_gate():
    """§8：单次 agentic 会话内 authority.resolve 的 Tool audit 被 Core 后处理消费。

    unresolved 的引用 → 依赖 assessment 转 not_evaluable；无关 assessment 不阻断；
    authority_runtime 审计证据写入 result.evidence。
    """
    from impl.projects.client_search import judge as candidate_module
    from impl.projects.client_search.judge_execution import judge_trace

    spec = _authority_spec()
    trace = RunTrace(
        trace_id="trace-authority-runtime",
        project_id="client_search",
        input={"query": "帮我找高净值客户"},
        extracted_output={
            "query_logic": "AND",
            "conditions": [
                {"field": "vipType", "operator": "eq", "value": "VIP"}
            ],
        },
        status="ok",
    )
    context = candidate_module._build_core_context(
        spec, trace, embedding_provider=DeterministicHashEmbeddingProvider()
    )
    authority_tool = context["authority_tool"]
    _seed_authority_audit(
        authority_tool,
        "tc-semantic",
        status="unresolved",
        reason=(
            "产品术语资料与历史案例来自不同治理链路，"
            "当前无法确认正式采用哪套定义。"
        ),
        required_evidence=("正式定义来源与生效版本",),
    )
    client = SinglePassJudgeLlm({
        "business_expectations": [
            {
                "expectation_id": "explicit-condition",
                "blocking": True,
                "expected_outcome": "明确条件不得遗漏",
                "acceptance_criteria": ["明确条件不得遗漏"],
            },
            {
                "expectation_id": "semantic-mapping",
                "blocking": True,
                "expected_outcome": "语义映射必须有权威依据",
                "acceptance_criteria": ["语义映射必须有权威依据"],
            },
        ],
        "fulfillment_assessments": [
            {
                "expectation_id": "explicit-condition",
                "status": "fulfilled",
            },
            {
                "expectation_id": "semantic-mapping",
                "status": "fulfilled",
                "authority_tool_call_ids": ["tc-semantic"],
            },
        ],
        "expected": {
            "query_logic": "AND",
            "conditions": [
                {"field": "vipType", "operator": "eq", "value": "VIP"}
            ],
        },
        "reasoning_summary": "初始评估",
    })

    result = judge_trace(
        spec,
        trace,
        user_intent="帮我找高净值客户",
        llm=client,
        project_judge_context=context,
    )

    assert client.calls == 1
    assert client.call_kwargs[0]["stage"] == "judge"
    assert "tools_override" not in client.call_kwargs[0]

    assessments = {
        item.expectation_id: item for item in result.fulfillment_assessments
    }
    assert assessments["explicit-condition"].status == "fulfilled"
    semantic = assessments["semantic-mapping"]
    assert semantic.status == "not_evaluable"
    entry = next(
        item
        for item in semantic.evidence_refs
        if isinstance(item, dict) and item.get("kind") == "authority_unresolved"
    )
    assert entry["reason"]
    assert entry["required_evidence"] == ["正式定义来源与生效版本"]
    assert entry["environment_snapshot_sha256"] == (
        authority_tool._env.environment_snapshot_sha256
    )
    runtime_audit = next(
        item
        for item in result.evidence
        if isinstance(item, dict) and item.get("source") == "authority_runtime"
    )
    assert runtime_audit["tool_call_ids"] == ["tc-semantic"]


def test_client_search_judge_reference_missing_tool_call_marks_needs_human_review():
    """§8：assessment 引用了 audit 中不存在的 tool_call_id → needs_human_review，不静默放行。"""
    from impl.projects.client_search import judge as candidate_module
    from impl.projects.client_search.judge_execution import judge_trace

    spec = _authority_spec()
    trace = RunTrace(
        trace_id="trace-authority-missing-ref",
        project_id="client_search",
        input={"query": "帮我找高净值客户"},
        extracted_output={
            "conditions": [
                {"field": "vipType", "operator": "eq", "value": "VIP"}
            ],
        },
        status="ok",
    )
    context = candidate_module._build_core_context(
        spec, trace, embedding_provider=DeterministicHashEmbeddingProvider()
    )
    client = SinglePassJudgeLlm({
        "business_expectations": [
            {
                "expectation_id": "semantic-mapping",
                "blocking": True,
                "expected_outcome": "语义映射必须有权威依据",
                "acceptance_criteria": ["语义映射必须有权威依据"],
            },
        ],
        "fulfillment_assessments": [
            {
                "expectation_id": "semantic-mapping",
                "status": "fulfilled",
                "authority_tool_call_ids": ["tc-never-ran"],
            },
        ],
        "expected": {
            "query_logic": "AND",
            "conditions": [
                {"field": "vipType", "operator": "eq", "value": "VIP"}
            ],
        },
        "reasoning_summary": "引用了一次未发生的 Authority 调用",
    })

    result = judge_trace(
        spec,
        trace,
        user_intent="帮我找高净值客户",
        llm=client,
        project_judge_context=context,
    )

    assessment = result.fulfillment_assessments[0]
    assert assessment.status == "not_evaluable"
    marker = next(
        item
        for item in assessment.evidence_refs
        if isinstance(item, dict)
        and item.get("kind") == "authority_reference_missing"
    )
    assert marker["needs_human_review"] is True


def test_candidate_accepts_live_request_user_text_as_pre_actual_intent():
    from impl.projects.client_search.judge import build_intent_frame

    spec = load_project("client_search")
    intent_frame = build_intent_frame(
        spec,
        RunTrace(
            trace_id="applicability:user-text",
            project_id="client_search",
            input={"user_text": "查找30岁以上的客户"},
            normalized_request={"user_text": "查找30岁以上的客户"},
        ),
    )

    assert intent_frame["request_candidates"] == [
        {
            "source": "normalized_request.user_text",
            "value": "查找30岁以上的客户",
        },
        {
            "source": "input.user_text",
            "value": "查找30岁以上的客户",
        },
    ]


def test_candidate_catalog_tools_search_and_load_without_dumping_collections():
    from impl.projects.client_search.catalog import (
        FIELD_INDEX_KEY,
        build_draft_catalog_registry,
        search_catalog,
    )
    from impl.projects.client_search.judge import _build_judge_tools

    spec = load_project("client_search")
    registry = build_draft_catalog_registry(spec)
    hits, _searched = search_catalog(
        registry, "clientAge", index_keys=(FIELD_INDEX_KEY,)
    )
    assert hits
    assert hits[0].key == "clientAge"
    assert hits[0].name == "客户本人年龄"
    assert "content" not in hits[0].as_dict()

    empty, _ = search_catalog(registry, "十里堡")
    assert empty == []

    tools = _build_judge_tools(spec)
    assert {tool.name for tool in tools} == {
        "investigation_search_index",
        "investigation_load_entry",
        "field_search_definition",
    }
    definition_tool = next(
        tool
        for tool in tools
        if tool.name == "field_search_definition"
    )

    definition = definition_tool.entrypoint(field="clientAge")
    assert set(definition.actual) == {
        "field",
        "operators",
        "value_types",
        "is_supported",
        "short_name",
        "unit",
    }
    assert definition.actual["field"] == "clientAge"
    assert definition.actual["is_supported"] is True
    assert "description" not in definition.actual
    assert "examples" not in definition.actual
    assert "notes" not in definition.actual


def test_candidate_context_is_small_and_rejects_unrelated_request():
    from impl.projects.client_search.judge import _build_core_context

    context = _build_core_context(
        _authority_spec(),
        RunTrace(
            trace_id="applicability:weather",
            project_id="client_search",
            input={"query": "今天天气怎么样"},
            normalized_request={"query": "今天天气怎么样"},
        ),
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )

    assert "applicable_product_expectation_ids" not in context
    assert context["authority_environment"].environment_snapshot_sha256
    assert context["environment_snapshot_sha256"] == (
        context["authority_environment"].environment_snapshot_sha256
    )
    extras = context["user_prompt_extras"]
    assert extras["product_use_scenarios"]["find-target-customers"]
    assert extras["capability_manifest"] == {}
    assert extras["value_mappings"] == {}
    assert set(extras["enhanced_rules"]) <= {"negation_words"}
    assert "condition_comparison" in extras
    tool_names = {getattr(tool, "name", "") for tool in context["tools"]}
    assert "authority_resolve" in tool_names
    joined = "\n".join(context["system_prompt_extras"])
    assert "fulfillment_assessments 字段约束" in joined
    assert "authority.resolve" in joined
    assert "authority_tool_call_ids" in joined


def test_judge_context_injects_evidence_space_not_curated_conclusions():
    """新方案：调查交接=证据空间（报告），不给 runtime 预置"问题→结论"决议。

    上下文不再注入 judge_authority_resolutions / authority_reuse_records；
    authority 判断由 Judge 现场调用 authority.resolve 在物化证据空间内裁决。
    """
    from impl.projects.client_search.judge import (
        _build_core_context,
        _load_authority_report,
    )

    spec = _authority_spec()
    report = _load_authority_report(spec)
    assert len(report.materials) == 15
    gap_ids = {gap.gap_id for gap in report.coverage_gaps}
    assert gap_ids == {
        "semantic-mapping-authority",
        "query-form-equivalence-authority",
        "responsibility-boundary-unsupported-field",
        "responsibility-boundary-entity-name-query",
        "silently-dropped-request-dimension",
        "enum-space-search-consumption-boundary",
    }
    assert all(gap.required_evidence for gap in report.coverage_gaps)

    context = _build_core_context(
        spec,
        RunTrace(
            trace_id="evidence-space-not-resolutions",
            project_id="client_search",
            input={"query": "贵C826N1"},
            normalized_request={"query": "贵C826N1"},
        ),
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )
    extras = context["user_prompt_extras"]
    assert "judge_authority_resolutions" not in extras
    assert "authority_reuse_records" not in context
    assert context["authority_environment"].environment_snapshot_sha256
    tool_names = {getattr(tool, "name", "") for tool in context["tools"]}
    assert "authority_resolve" in tool_names


def test_single_pass_judge_consumes_unresolved_authority_resolutions():
    """§8：单次会话内多个 unresolved authority.resolve 分别转对应 assessment 为 not_evaluable。"""
    from impl.projects.client_search import judge as candidate_module
    from impl.projects.client_search.judge_execution import judge_trace

    spec = _authority_spec()
    trace = RunTrace(
        trace_id="authority:explicit-home-cue",
        project_id="client_search",
        input={"query": "平安居家V1及以上客户"},
        normalized_request={"query": "平安居家V1及以上客户"},
        extracted_output={
            "query": "平安居家V1及以上客户",
            "conditions": [{
                "field": "pajjMemberGradeInfo.pajjmembergradesearch",
                "operator": "MATCH",
                "value": "平安居家V1及以上",
            }],
            "query_logic": "AND",
        },
        status="ok",
    )
    context = candidate_module._build_core_context(
        spec, trace, embedding_provider=DeterministicHashEmbeddingProvider()
    )
    authority_tool = context["authority_tool"]
    _seed_authority_audit(
        authority_tool,
        "tc-semantic",
        status="unresolved",
        reason="平安居家V1及以上目标的正式业务值存在两套定义冲突（V1优享/V1及以上的边界）。",
        required_evidence=("正式定义来源",),
    )
    _seed_authority_audit(
        authority_tool,
        "tc-enum",
        status="unresolved",
        reason="pajjMemberGradeInfo.pajjmembergradesearch 的合法值全集缺少下游权威导出。",
        required_evidence=("只读下游聚合",),
    )
    client = SinglePassJudgeLlm({
        "business_expectations": [
            {
                "expectation_id": "home-boundary",
                "blocking": True,
                "expected_outcome": "把平安居家V1及以上映射到pajjMemberGradeInfo.pajjmembergradesearch中的正确业务值",
                "acceptance_criteria": ["保留平安居家等级语义"],
            },
            {
                "expectation_id": "home-enum",
                "blocking": True,
                "expected_outcome": "pajjMemberGradeInfo.pajjmembergradesearch使用下游合法枚举值",
                "acceptance_criteria": ["枚举值完整覆盖业务类别"],
            },
        ],
        "fulfillment_assessments": [
            {
                "expectation_id": "home-boundary",
                "status": "not_evaluable",
                "authority_tool_call_ids": ["tc-semantic"],
            },
            {
                "expectation_id": "home-enum",
                "status": "not_evaluable",
                "authority_tool_call_ids": ["tc-enum"],
            },
        ],
        "expected": {
            "query_logic": "AND",
            "conditions": [
                {"field": "pajjMemberGradeInfo.pajjmembergradesearch", "operator": "MATCH"}
            ],
        },
        "reasoning_summary": "两个不同判断点分别缺少决定性证据",
    })

    result = judge_trace(
        spec,
        trace,
        user_intent="平安居家V1及以上客户",
        llm=client,
        project_judge_context=context,
    )

    assert client.calls == 1
    assert result.overall_fulfillment["status"] == "not_evaluable"
    by_id = {item.expectation_id: item for item in result.fulfillment_assessments}
    assert by_id["home-boundary"].status == "not_evaluable"
    assert by_id["home-enum"].status == "not_evaluable"
    assert {
        tuple(item.authority_tool_call_ids)
        for item in result.fulfillment_assessments
    } == {("tc-semantic",), ("tc-enum",)}
    assert "planning failed" not in result.reasoning_summary


def test_single_pass_judge_uses_resolved_authority_without_override():
    """§8：resolution=resolved 时不覆盖 Judge 结论，assessment 保持原判定。"""
    from impl.projects.client_search import judge as candidate_module
    from impl.projects.client_search.judge_execution import judge_trace

    spec = _authority_spec()
    trace = RunTrace(
        trace_id="authority:enum-completeness",
        project_id="client_search",
        input={"query": "剔除某业务类别客户"},
        normalized_request={"query": "剔除某业务类别客户"},
        extracted_output={"conditions": []},
        status="ok",
    )
    context = candidate_module._build_core_context(
        spec, trace, embedding_provider=DeterministicHashEmbeddingProvider()
    )
    authority_tool = context["authority_tool"]
    _seed_authority_audit(
        authority_tool,
        "tc-enum",
        status="resolved",
        reason="下游只读聚合唯一决定合法值全集。",
    )
    client = SinglePassJudgeLlm({
        "business_expectations": [
            {
                "expectation_id": "exclude-category",
                "blocking": True,
                "expected_outcome": "排除完整业务类别",
                "acceptance_criteria": ["值覆盖产品枚举中的所有产品简称"],
            },
        ],
        "fulfillment_assessments": [
            {
                "expectation_id": "exclude-category",
                "status": "fulfilled",
                "authority_tool_call_ids": ["tc-enum"],
                "actual_evidence": ["actual 列表与下游合法值全集一致"],
            },
        ],
        "reasoning_summary": "已确认合法值全集，排除列表完整。",
    })

    result = judge_trace(
        spec,
        trace,
        user_intent="剔除某业务类别客户",
        llm=client,
        project_judge_context=context,
    )

    assessment = result.fulfillment_assessments[0]
    assert assessment.status == "fulfilled"
    assert assessment.authority_tool_call_ids == ["tc-enum"]


def test_candidate_reports_unrelated_request_as_not_applicable(monkeypatch):
    """适用性判断交回单次 Judge LLM：不适用时 LLM 输出空 business_expectations。"""
    from impl.core import llm_client as llm_client_module
    from impl.projects.client_search import judge as candidate_module
    from impl.projects.client_search.judge import ClientSearchJudge
    from impl.core.authority_environment import build_authority_environment as real_build

    def _test_build(
        spec,
        *,
        role="judge",
        use_candidate=True,
        gateway_tools=(),
        embedding_provider=None,
        trace_id="",
        case_id="",
        business_source_staleness_policy="warn",
    ):
        return real_build(
            spec,
            role=role,
            use_candidate=use_candidate,
            gateway_tools=gateway_tools,
            embedding_provider=DeterministicHashEmbeddingProvider(),
            trace_id=trace_id,
            case_id=case_id,
            business_source_staleness_policy=business_source_staleness_policy,
        )

    monkeypatch.setattr(candidate_module, "build_authority_environment", _test_build)

    class NotApplicableLlm:
        def __init__(self):
            self.calls = 0

        def complete_json(self, *_args, **_kwargs):
            self.calls += 1
            return {
                "business_expectations": [],
                "fulfillment_assessments": [],
                "reasoning_summary": (
                    "该请求是天气查询，不属于 find-target-customers 客户搜索场景，"
                    "业务不适用。"
                ),
            }

    client = NotApplicableLlm()
    monkeypatch.setattr(
        llm_client_module,
        "project_llm_client",
        lambda *_args, **_kwargs: client,
    )

    result = ClientSearchJudge(load_project("client_search")).judge_trace(
        RunTrace(
            trace_id="applicability:weather-result",
            project_id="client_search",
            input={"query": "今天天气怎么样"},
            normalized_request={"query": "今天天气怎么样"},
            extracted_output={"answer": "晴"},
            status="ok",
        )
    )

    assert client.calls == 1
    # Authority-off cannot emit overall not_evaluable, including empty
    # assessments from an out-of-scenario LLM declaration.
    assert result.overall_fulfillment["status"] == "not_fulfilled"
    assert result.overall_fulfillment["status"] != "not_evaluable"
    assert all(
        str((item.get("status") if isinstance(item, dict) else getattr(item, "status", "")) or "").strip().lower()
        != "not_evaluable"
        for item in (result.fulfillment_assessments or [])
    )
    assert "不适用" in result.reasoning_summary
    assert "LLM 调用失败" not in result.reasoning_summary
    assert {
        "source": "business_expectation_applicability",
        "status": "not_applicable",
        "cause": "完全无关",
        "trace_id": "applicability:weather-result",
    } in result.evidence


def test_judge_prompt_contract_requires_not_evaluable_cause_markers():
    """上下文工程：Authority 开启时 judge prompt 必须指示 not_evaluable 成因标签契约。

    authority_gate §8.4 只消费显式「结论类型：」标记；prompt 不指示则 LLM 不会写，
    导致输入坏/完全无关等豁免成因也被标 needs_human_review（噪音人审）。
    Authority 关闭时不向模型展示 not_evaluable 词表或成因契约（该块已删除）。
    """
    from impl.projects.client_search import judge as candidate_module

    spec = load_project("client_search")
    trace = RunTrace(
        trace_id="contract:ne-cause-marker",
        project_id="client_search",
        input={"query": "30岁女性客户"},
        normalized_request={"query": "30岁女性客户"},
        extracted_output={
            "conditions": [
                {"field": "age", "operator": "MATCH", "value": 30},
                {"field": "sex", "operator": "MATCH", "value": "女"},
            ],
        },
    )
    joined_off = "\n".join(
        candidate_module._build_core_context(spec, trace)["system_prompt_extras"]
    )
    assert "输入坏" in joined_off
    assert "完全无关" in joined_off
    assert "成因契约" not in joined_off
    assert "结论类型：职责外" not in joined_off
    assert "Authority 能力不可用" not in joined_off

    joined_on = "\n".join(
        candidate_module._build_core_context(_authority_spec(), trace)["system_prompt_extras"]
    )
    assert "结论类型：职责外" in joined_on
    assert "结论类型：完全无关" in joined_on
    assert "结论类型：依据不充分" in joined_on
    assert "结论类型：输入坏" in joined_on
    assert "缺料清单" in joined_on
    assert "Authority 能力不可用" not in joined_on


def test_candidate_judge_tool_reuses_same_audited_result_for_duplicate_arguments(
    monkeypatch,
):
    from impl.projects.client_search import judge as candidate_module
    from impl.tools import ToolResult, VerifiableTool

    calls = []

    def execute(*, field):
        calls.append(field)
        return ToolResult(
            tool_id="field.search_definition",
            tool_type="field_retrieval",
            outputs={"field": field},
        )

    monkeypatch.setattr(candidate_module, "load_field_provider", lambda _spec: object())
    monkeypatch.setattr(
        candidate_module,
        "create_minimal_field_definition_tool",
        lambda _provider, _registry=None: VerifiableTool(
            tool_id="field.search_definition",
            description="查找字段定义",
            parameters={
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "description": "字段名",
                    }
                },
                "required": ["field"],
            },
            execute_fn=execute,
        ),
    )

    function = next(
        item
        for item in candidate_module._build_judge_tools(load_project("client_search"))
        if item.name == "field_search_definition"
    )
    first = function.entrypoint(field="clientAge")
    second = function.entrypoint(field="clientAge")
    third = function.entrypoint(field="clientCity")

    assert first.outputs == second.outputs
    assert third.outputs["field"] == "clientCity"
    assert calls == ["clientAge", "clientCity"]


def test_operator_justified_enum_exact_match_gate():
    """MATCH→CONTAINS 收敛：单值精确命中清单枚举才放行，清单外值/多值/字典不放行。"""
    from impl.projects.client_search.judge import _operator_justified

    entry = {
        "operators": ["CONTAINS", "EXISTS", "NOT_CONTAINS", "NOT_EXISTS"],
        "value_types": ["enum", "exists", "not_exists"],
        "enums": [
            "车辆交强险", "车辆商业险", "e生保", "中高端医疗", "合家欢",
            "家财险", "学平险", "财富", "健康", "生活",
        ],
    }
    assert _operator_justified("agentPerspProductType", "MATCH", entry, [], value="合家欢")
    assert not _operator_justified("agentPerspProductType", "MATCH", entry, [], value="合家福")
    assert not _operator_justified(
        "agentPerspProductType", "MATCH", entry, [], value=["合家欢", "健康"]
    )
    assert not _operator_justified(
        "agentPerspProductType", "MATCH", entry, [], value={"min": "a", "max": "b"}
    )
    assert _operator_justified("agentPerspProductType", "CONTAINS", entry, [], value=["合家欢"])


def test_operator_justified_range_family_and_equivalence_rules():
    """范围族互容与显式等价规则仍放行，不依赖枚举命中。"""
    from impl.projects.client_search.judge import _operator_justified

    age_entry = {
        "operators": ["EXISTS", "GTE", "LTE", "NOT_EXISTS", "RANGE"],
        "value_types": ["exists", "numeric"],
        "enums": [],
    }
    assert _operator_justified("clientAge", "RANGE", age_entry, [], value={"min": 18, "max": 30})
    assert _operator_justified("clientAge", "GT", age_entry, [], value=30)
    rule = {"field": "clientAge", "operator": "BETWEEN"}
    assert _operator_justified("clientAge", "BETWEEN", age_entry, [rule], value={"min": 1, "max": 2})


def test_operator_capability_check_defers_conflict_field():
    """Authority 开启时，operator 冲突缺少裁决引用会 fail-closed 为 NE。

    决议#4（unresolved，观察）声明该字段 MATCH 定义与 RANGE 示例冲突，实际可执行
    操作符无法由资料唯一确定 → 留给 authority.resolve 现场裁决。
    """
    from impl.projects.client_search.judge import _apply_operator_capability_check
    from impl.core.schema import FulfillmentAssessment, JudgeResult, RunTrace

    spec = _authority_spec()
    trace = RunTrace(
        trace_id="operator-gate-023",
        project_id="client_search",
        input={"query": "少儿万能险且有子女"},
        extracted_output={
            "query_logic": "AND",
            "conditions": [
                {"field": "pTypes", "operator": "MATCH", "value": "万能型"},
                {"field": "familyInfo.familyrelation", "operator": "MATCH", "value": "子女"},
                {
                    "field": "familyInfo.familyclientbirthday",
                    "operator": "NOT_MATCH",
                    "value": {"min": "2008-07-29 00:00:00", "max": "2026-07-28 23:59:59"},
                },
            ],
        },
    )
    result = JudgeResult(trace_id="operator-gate-023", project_id="client_search")
    result.fulfillment_assessments = [
        FulfillmentAssessment(
            expectation_id="birthday-range",
            status="fulfilled",
            actual_evidence=[
                {
                    "field": "familyInfo.familyclientbirthday",
                    "operator": "NOT_MATCH",
                    "value": {"min": "2008-07-29 00:00:00", "max": "2026-07-28 23:59:59"},
                }
            ],
        )
    ]
    _apply_operator_capability_check(spec, trace, result)

    assessment = result.fulfillment_assessments[0]
    assert assessment.status == "not_evaluable"
    marker = next(
        item for item in assessment.evidence_refs
        if item.get("kind") == "operator_authority_required_not_consulted"
    )
    assert marker["needs_human_review"] is True
    assert any(
        item.get("source") == "capability_manifest.operator_conflict_deferred"
        and "familyInfo.familyclientbirthday" in str(item.get("fields"))
        for item in result.evidence
    )
    violation = next(
        item for item in result.evidence
        if item.get("source") == "capability_manifest.operator_violation"
    )
    assert "familyInfo.familyclientbirthday" in str(violation["violations"])
    assert "not by itself proof" in violation["rule"]


def test_operator_capability_check_does_not_override_judge_when_authority_disabled():
    """Authority 关闭时，capability mismatch 不得覆盖 Judge 的 F/NF。"""
    from impl.core.project_loader import load_project
    from impl.projects.client_search.judge import _apply_operator_capability_check
    from impl.core.schema import FulfillmentAssessment, JudgeResult, RunTrace

    spec = load_project("client_search")
    trace = RunTrace(
        trace_id="operator-gate-authority-required",
        project_id="client_search",
        input={"query": "30岁客户"},
        extracted_output={
            "conditions": [
                {"field": "clientAge", "operator": "MATCH", "value": 30},
            ],
        },
    )
    result = JudgeResult(trace_id=trace.trace_id, project_id="client_search")
    result.fulfillment_assessments = [
        FulfillmentAssessment(
            expectation_id="age-filter",
            status="fulfilled",
            actual_evidence=[{"detail": "clientAge 使用 MATCH"}],
        )
    ]

    _apply_operator_capability_check(spec, trace, result)

    assessment = result.fulfillment_assessments[0]
    assert assessment.status == "fulfilled"
    assert assessment.score is None
    assert assessment.downstream_impact == ""
    assert not assessment.evidence_refs
    assert not result.evidence


def test_operator_capability_check_accepts_family_birthday_range_forms():
    from impl.core.project_loader import load_project
    from impl.projects.client_search.judge import _actual_operator_violations
    from impl.core.schema import RunTrace

    spec = load_project("client_search")
    for operator, value in [
        ("GTE", "2020-08-12 00:00:00"),
        ("LTE", "2008-08-11 23:59:59"),
        ("RANGE", {"min": "2013-08-12 00:00:00", "max": "2020-08-11 23:59:59"}),
    ]:
        trace = RunTrace(
            trace_id=f"family-birthday-{operator.lower()}",
            project_id="client_search",
            input={"query": "家庭成员年龄条件"},
            extracted_output={
                "conditions": [{
                    "field": "familyInfo.familyclientbirthday",
                    "operator": operator,
                    "value": value,
                }],
            },
        )
        assert _actual_operator_violations(spec, trace) == []


def test_operator_capability_check_does_not_penalize_unrelated_assessment():
    from impl.core.project_loader import load_project
    from impl.projects.client_search.judge import _apply_operator_capability_check
    from impl.core.schema import FulfillmentAssessment, JudgeResult, RunTrace

    spec = load_project("client_search")
    trace = RunTrace(
        trace_id="operator-gate-unrelated-assessment",
        project_id="client_search",
        input={"query": "30岁客户"},
        extracted_output={
            "conditions": [{"field": "clientAge", "operator": "MATCH", "value": 30}],
        },
    )
    result = JudgeResult(trace_id=trace.trace_id, project_id="client_search")
    result.fulfillment_assessments = [
        FulfillmentAssessment(
            expectation_id="age-filter",
            status="fulfilled",
            score=1.0,
            actual_evidence=[{"field": "clientAge", "operator": "MATCH", "value": 30}],
        ),
        FulfillmentAssessment(
            expectation_id="no-extra-constraints",
            status="fulfilled",
            score=1.0,
            actual_evidence=[{"fields": ["clientAge"], "conditions_count": 1}],
        ),
    ]

    _apply_operator_capability_check(spec, trace, result)

    assert result.fulfillment_assessments[0].status == "fulfilled"
    assert result.fulfillment_assessments[1].status == "fulfilled"


def test_operator_capability_check_preserves_semantic_equivalence_without_authority(
    monkeypatch,
):
    from impl.core.project_loader import load_project
    from impl.projects.client_search import judge as judge_module
    from impl.core.schema import FulfillmentAssessment, JudgeResult, RunTrace

    spec = load_project("client_search")
    trace = RunTrace(
        trace_id="operator-gate-family-age-equivalence",
        project_id="client_search",
        input={"query": "有6岁以下子女的客户"},
        extracted_output={
            "query_logic": "AND",
            "conditions": [
                {
                    "field": "familyInfo.familyrelation",
                    "operator": "MATCH",
                    "value": "子女",
                },
                {
                    "field": "familyInfo.familyclientbirthday",
                    "operator": "GTE",
                    "value": "2020-08-12 00:00:00",
                },
            ],
        },
    )
    result = JudgeResult(trace_id=trace.trace_id, project_id="client_search")
    result.fulfillment_assessments = [
        FulfillmentAssessment(
            expectation_id="child-under-six",
            status="fulfilled",
            score=1.0,
            actual_evidence=[
                {
                    "field": "familyInfo.familyclientbirthday",
                    "operator": "GTE",
                    "value": "2020-08-12 00:00:00",
                }
            ],
        )
    ]
    monkeypatch.setattr(
        judge_module,
        "_actual_operator_violations",
        lambda _spec, _trace: [
            {
                "field": "familyInfo.familyclientbirthday",
                "operator": "GTE",
            }
        ],
    )

    judge_module._apply_operator_capability_check(spec, trace, result)

    assert result.fulfillment_assessments[0].status == "fulfilled"
    assert result.fulfillment_assessments[0].score == 1.0
    assert not result.evidence


def test_operator_capability_check_keeps_enum_exact_match():
    """单值 MATCH 精确命中清单枚举（128 形态）不被 operator gate 判不可执行。"""
    from impl.core.project_loader import load_project
    from impl.projects.client_search.judge import _apply_operator_capability_check
    from impl.core.schema import FulfillmentAssessment, JudgeResult, RunTrace

    spec = load_project("client_search")
    trace = RunTrace(
        trace_id="operator-gate-128",
        project_id="client_search",
        input={"query": "合家福客户"},
        extracted_output={
            "query_logic": "AND",
            "conditions": [
                {"field": "agentPerspProductType", "operator": "MATCH", "value": "合家欢"},
            ],
        },
    )
    result = JudgeResult(trace_id="operator-gate-128", project_id="client_search")
    result.fulfillment_assessments = [
        FulfillmentAssessment(
            expectation_id="product-match",
            status="fulfilled",
            actual_evidence=[{"detail": "agentPerspProductType MATCH 合家欢"}],
        )
    ]
    _apply_operator_capability_check(spec, trace, result)

    assert result.fulfillment_assessments[0].status == "fulfilled"
    assert not any(
        "capability_manifest.operator_violation" in str(item.get("source"))
        for item in result.evidence
    )




def test_candidate_skips_authority_environment_for_direct_evidence_case(monkeypatch):
    from impl.projects.client_search import judge as candidate_module

    calls = []

    def _unexpected_build(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("direct-evidence case must not build Authority Environment")

    monkeypatch.setattr(candidate_module, "build_authority_environment", _unexpected_build)
    context = candidate_module._build_core_context(
        load_project("client_search"),
        RunTrace(
            trace_id="direct-evidence:no-authority",
            project_id="client_search",
            input={"query": "30岁女性客户"},
            normalized_request={"query": "30岁女性客户"},
            extracted_output={
                "query_logic": "AND",
                "conditions": [
                    {"field": "age", "operator": "MATCH", "value": 30},
                    {"field": "sex", "operator": "MATCH", "value": "女"},
                ],
            },
        ),
    )

    assert calls == []
    assert context["authority_environment"] is None
    assert context["authority_tool"] is None
    assert context["environment_snapshot_sha256"] == ""
    assert context["user_prompt_extras"]["authority_mode"] == "not_required"
    assert "authority_candidate_reasons" not in context["user_prompt_extras"]
    assert "authority_obligation_contract" not in context["user_prompt_extras"]
    assert "authority_resolve" not in {
        getattr(tool, "name", "") for tool in context["tools"]
    }


def test_disabled_authority_preserves_boundary_candidates_without_building_tool(monkeypatch):
    from impl.projects.client_search import judge as candidate_module

    calls = []

    def _unexpected_build(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("disabled authority must not build Authority Environment")

    monkeypatch.setattr(candidate_module, "build_authority_environment", _unexpected_build)
    context = candidate_module._build_core_context(
        load_project("client_search"),
        RunTrace(
            trace_id="boundary:disabled-authority",
            project_id="client_search",
            input={"query": "7月盘客"},
            normalized_request={"query": "7月盘客"},
            extracted_output={
                "conditions": [],
                "robot_text": "提示：盘客暂不支持搜索，无法进行查询。",
            },
        ),
    )

    assert calls == []
    assert context["authority_environment"] is None
    assert context["authority_tool"] is None
    assert context["user_prompt_extras"]["authority_mode"] == "disabled_with_candidates"
    assert "authority_candidate_reasons" not in context["user_prompt_extras"]
    assert "authority_obligation_contract" not in context["user_prompt_extras"]
    prompt = "\n".join(context["system_prompt_extras"])
    assert "not_fulfilled" in prompt
    assert "成因契约" not in prompt
    assert "结论类型：职责外" not in prompt


def test_candidate_builds_authority_environment_for_boundary_candidate(monkeypatch):
    from impl.projects.client_search import judge as candidate_module

    monkeypatch.setattr(
        candidate_module,
        "_unsupported_boundary_evidence",
        lambda _trace, **_kwargs: {"all_conditions_unsupported": True},
    )
    context = candidate_module._build_core_context(
        _authority_spec(),
        RunTrace(
            trace_id="boundary:authority-required",
            project_id="client_search",
            input={"query": "按车牌找客户"},
            normalized_request={"query": "按车牌找客户"},
            extracted_output={"conditions": [], "robot_text": "暂不支持车牌查询"},
        ),
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )

    assert context["authority_environment"] is not None
    assert context["authority_tool"] is not None
    assert context["user_prompt_extras"]["authority_mode"] == "on_demand"
    assert (
        "capability_or_responsibility_boundary:all_conditions_unsupported"
        in context["user_prompt_extras"]["authority_candidate_reasons"]
    )


def _license_plate_trace():
    return RunTrace(
        trace_id="boundary:093-license-plate",
        project_id="client_search",
        input={"query": "贵C826N1"},
        normalized_request={"query": "贵C826N1"},
        extracted_output={
            "query_logic": "AND",
            "conditions": [],
            "intent_summary": "提示：车牌号暂不支持搜索，无法进行查询。",
            "robot_text": "提示：车牌号暂不支持搜索，无法进行查询。",
        },
    )


def _panke_trace():
    return RunTrace(
        trace_id="boundary:panke-customer-review",
        project_id="client_search",
        input={"query": "7月盘客"},
        normalized_request={"query": "7月盘客"},
        extracted_output={
            "conditions": [],
            "robot_text": "提示：盘客暂不支持搜索，无法进行查询。",
        },
    )


def test_candidate_triggers_on_explicit_unsupported_without_lexical_overlap():
    """093 类：请求是具体值、提示是字段标签，无词法重叠。

    Catalog Search uses the user request only, so a plate number is a silent
    miss. Do not search live labels (that echoed Live's own field name).
    Authority may still assemble via empty actual conditions.
    """
    from impl.projects.client_search import judge as candidate_module

    spec = _authority_spec()
    trace = _license_plate_trace()
    raw = candidate_module._unsupported_boundary_evidence(trace)
    assert raw.get("acknowledges_requested_constraint") is False
    enriched = candidate_module._enrich_unsupported_boundary_evidence(
        spec, trace, raw
    )
    assert enriched.get("explicit_unsupported_capability") is False
    assert "missing blocking result is not_fulfilled" not in str(
        enriched.get("decision_rule") or ""
    )

    context = candidate_module._build_core_context(
        spec,
        trace,
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )
    reasons = context["user_prompt_extras"]["authority_candidate_reasons"]
    assert "capability_or_responsibility_boundary:explicit_unsupported_field" not in reasons
    assert "missing_semantic_carrier:empty_actual_conditions" in reasons
    assert context["user_prompt_extras"]["authority_mode"] == "on_demand"


def test_enrich_loads_unsupported_field_from_user_query():
    """User query itself hits an explicit unsupported field (盘客 → customerReview)."""
    from impl.projects.client_search import judge as candidate_module

    spec = _authority_spec()
    trace = _panke_trace()
    raw = candidate_module._unsupported_boundary_evidence(trace)
    enriched = candidate_module._enrich_unsupported_boundary_evidence(
        spec, trace, raw
    )
    assert enriched.get("explicit_unsupported_capability") is True
    fields = [
        item.get("field")
        for item in enriched.get("explicit_unsupported_fields") or []
    ]
    assert "customerReview" in fields
    assert "missing blocking result is not_fulfilled" not in str(
        enriched.get("decision_rule") or ""
    )

    context = candidate_module._build_core_context(
        spec,
        trace,
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )
    reasons = context["user_prompt_extras"]["authority_candidate_reasons"]
    assert context["user_prompt_extras"]["authority_mode"] == "on_demand"
    assert "capability_or_responsibility_boundary:explicit_unsupported_field" in reasons


def test_enrich_does_not_inject_blocking_nf_rule():
    """Catalog supplement must not rewrite incoming decision_rule with NF doctrine."""
    from impl.projects.client_search import judge as candidate_module

    forbidden = "missing blocking result is not_fulfilled"
    spec_on = _authority_spec()
    spec_off = load_project("client_search")
    for spec in (spec_on, spec_off):
        for trace in (_license_plate_trace(), _panke_trace()):
            raw = candidate_module._unsupported_boundary_evidence(trace)
            incoming_rule = str(raw.get("decision_rule") or "")
            enriched = candidate_module._enrich_unsupported_boundary_evidence(
                spec, trace, raw
            )
            outgoing_rule = str(enriched.get("decision_rule") or "")
            assert forbidden not in outgoing_rule
            assert outgoing_rule == incoming_rule


def test_disabled_authority_088_093_decision_rule_does_not_leak_not_evaluable():
    """Authority off: 088 盘客 / 093 车牌 decision_rule must not leak NE."""
    from impl.projects.client_search import judge as candidate_module

    spec_off = load_project("client_search")
    from impl.core.authority_scopes import in_run_authority_enabled
    assert in_run_authority_enabled(spec_off) is False
    spec_on = _authority_spec()
    forbidden = (
        "not_evaluable when the capability is unconfirmed",
        "out-of-boundary not_evaluable",
    )
    for trace in (_panke_trace(), _license_plate_trace()):
        raw = candidate_module._unsupported_boundary_evidence(
            trace, authority_enabled=False
        )
        enriched = candidate_module._enrich_unsupported_boundary_evidence(
            spec_off, trace, raw
        )
        rule = str(enriched.get("decision_rule") or "")
        for phrase in forbidden:
            assert phrase not in rule
        assert "Authority is disabled" in rule
        assert "Missing blocking core delivery is not_fulfilled" in rule
        assert "not_evaluable" not in rule
        assert "transparent refusal" in rule
        assert "must not make the case fulfilled" in rule

        context = candidate_module._build_core_context(spec_off, trace)
        prompt_rule = str(
            (
                context["user_prompt_extras"].get("unsupported_boundary_evidence") or {}
            ).get("decision_rule")
            or ""
        )
        for phrase in forbidden:
            assert phrase not in prompt_rule
        assert "not_fulfilled" in prompt_rule
        assert "not_evaluable" not in prompt_rule

        on_rule = str(
            candidate_module._enrich_unsupported_boundary_evidence(
                spec_on,
                trace,
                candidate_module._unsupported_boundary_evidence(
                    trace, authority_enabled=True
                ),
            ).get("decision_rule")
            or ""
        )
        assert "after authority.resolve" in on_rule
        assert "unconfirmed capability" in on_rule
        assert "not_evaluable" in on_rule


def test_candidate_triggers_on_partial_acknowledged_unsupported():
    """073 类：系统保留部分条件但拒绝请求自身约束（部分不支持）。

    acknowledges_requested_constraint=True（约束标签与请求词法重叠）即视为
    能力边界判断点，即使不是 all_conditions_unsupported 也要装配 authority。
    """
    from impl.projects.client_search import judge as candidate_module

    spec = _authority_spec()
    trace = RunTrace(
        trace_id="boundary:073-policy-date",
        project_id="client_search",
        input={"query": "2025年6月份投保的新客户名单"},
        normalized_request={"query": "2025年6月份投保的新客户名单"},
        extracted_output={
            "query_logic": "AND",
            "conditions": [
                {"field": "isBuyInsurance", "operator": "CONTAINS", "value": ["客户", "准客"]},
            ],
            "intent_summary": "客户类型包含客户、准客的客户\n提示：投保日期暂不支持搜索，系统将按可支持字段搜索。",
            "robot_text": "客户类型包含客户、准客的客户\n提示：投保日期暂不支持搜索，系统将按可支持字段搜索。",
        },
    )
    raw = candidate_module._unsupported_boundary_evidence(trace)
    assert raw.get("acknowledges_requested_constraint") is True
    assert raw.get("all_conditions_unsupported") is False

    context = candidate_module._build_core_context(
        spec,
        trace,
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )
    reasons = context["user_prompt_extras"]["authority_candidate_reasons"]
    assert context["user_prompt_extras"]["authority_mode"] == "on_demand"
    assert (
        "capability_or_responsibility_boundary:unsupported_constraint_acknowledged"
        in reasons
    )


def test_candidate_triggers_on_coverage_gap_for_silently_dropped_dimension():
    """138 类：请求维度被静默丢弃，无 notice/manifest 字段/reference 信号。

    请求文本命中调查层覆盖缺口（silently-dropped-request-dimension）且无更相关
    MaterialDecision 时，必须装配 authority：职责外/职责内能力缺失由 authority
    现场裁决（依赖调查层缺口索引，非启发式；investigate-authority-judge.md §11/§17）。
    """
    from impl.projects.client_search import judge as candidate_module

    spec = _authority_spec()
    trace = RunTrace(
        trace_id="boundary:138-salesperson-dimension",
        project_id="client_search",
        input={"query": "陈金秀在别的业务员的投保的平安产品"},
        normalized_request={"query": "陈金秀在别的业务员的投保的平安产品"},
        extracted_output={
            "query_logic": "AND",
            "conditions": [
                {"field": "searchClientName", "operator": "MATCH", "value": "陈金秀"},
            ],
            "intent_summary": "客户姓名为陈金秀的客户",
            "robot_text": "客户姓名为陈金秀的客户",
        },
    )
    context = candidate_module._build_core_context(
        spec,
        trace,
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )
    reasons = context["user_prompt_extras"]["authority_candidate_reasons"]
    assert context["user_prompt_extras"]["authority_mode"] == "on_demand"
    assert (
        "capability_or_responsibility_boundary:coverage_gap:"
        "silently-dropped-request-dimension"
        in reasons
    )
    assert context["authority_environment"] is not None


def test_field_definition_tool_preserves_explicit_unsupported_flags():
    from impl.projects.client_search.field_tools import (
        build_field_key_index_registry,
        create_minimal_field_definition_tool,
    )
    from impl.projects.client_search.field_provider import ClientSearchFieldDefinitionProvider

    spec = load_project("client_search")
    provider = ClientSearchFieldDefinitionProvider(spec)
    registry = build_field_key_index_registry(spec, provider)
    tool = create_minimal_field_definition_tool(provider, registry)

    for field in ("customerReview", "licensePlateNo"):
        result = tool.execute_fn(field=field)
        assert result.status == "succeeded"
        assert result.actual["is_supported"] is False


_AUTHORITY_OFF_F_NE_LICENSE_MARKERS = (
    "不直接视为当前系统输出错误",
    "不直接判为当前系统输出错误",
    "才返回 `not_evaluable`",
    "才返回 not_evaluable",
)


def test_semantic_field_hits_does_not_inject_value_mapping_aliases():
    """P2: spoken mapping aliases are not loaded facts.

    Reverse-lookup fragments are field/enum labels only. A query that only
    contains a value_mapping spoken key must not add that field. Field name
    in the request and enum hits remain valid compact-manifest seeds.
    """
    from impl.projects.client_search.judge import (
        _extract_fields_from_trace,
        _manifest_label_fragments,
        _semantic_field_hits,
    )

    manifest = {
        "wealthTier": {
            "field": "wealthTier",
            "enums": ["普通", "钻石卡"],
        },
        "sex": {
            "field": "sex",
            "enums": ["男", "女"],
        },
    }
    mapping = {
        "wealthTier": {
            "高净值": "钻石卡",
            "有钱人": "钻石卡",
        },
    }
    # Guard: if aliases were still folded into fragments, 高净值 would overlap.
    fragments = _manifest_label_fragments("wealthTier", manifest["wealthTier"])
    assert "高净值" not in fragments
    assert "高净" not in fragments
    assert "有钱" not in fragments
    assert "钻石卡" in fragments or "钻石" in fragments

    alias_query = "帮我找高净值客户"
    assert "wealthTier" not in _semantic_field_hits(alias_query, manifest)
    alias_trace = RunTrace(
        trace_id="alias-not-loaded-fact",
        project_id="client_search",
        input={"query": alias_query},
        normalized_request={"query": alias_query},
    )
    alias_fields = _extract_fields_from_trace(alias_trace, manifest)
    assert "wealthTier" not in alias_fields
    # Mapping dict is unused by reverse-lookup; passing it must not matter.
    assert mapping["wealthTier"]["高净值"] == "钻石卡"

    enum_trace = RunTrace(
        trace_id="enum-still-hits",
        project_id="client_search",
        input={"query": "钻石卡客户"},
        normalized_request={"query": "钻石卡客户"},
    )
    enum_fields = _extract_fields_from_trace(enum_trace, manifest)
    assert "wealthTier" in enum_fields
    assert "wealthTier" in _semantic_field_hits("钻石卡客户", manifest)

    name_trace = RunTrace(
        trace_id="field-name-still-hits",
        project_id="client_search",
        input={"query": "按 wealthTier 筛选客户"},
        normalized_request={"query": "按 wealthTier 筛选客户"},
    )
    name_fields = _extract_fields_from_trace(name_trace, manifest)
    assert "wealthTier" in name_fields


def test_authority_off_excludes_f_ne_licensing_clauses_for_088_093():
    """Authority off: slice ContextUnit clauses that license F/NE vs fulfilled.md §3.1.

    Markers drop old production-style boundary sentences from mandatory_context.
    Authority on keeps the JudgeResult marker only (those docs stay intact).
    """
    from impl.projects.client_search import judge as candidate_module

    spec_off = load_project("client_search")
    spec_on = _authority_spec()
    judge_result_marker = "`JudgeResult` 协议字段"

    for trace in (_panke_trace(), _license_plate_trace()):
        context_off = candidate_module._build_core_context(spec_off, trace)
        joined_off = "\n".join(context_off["system_prompt_extras"])
        assert "成因契约" not in joined_off
        assert "结论类型：职责外" not in joined_off
        decision_rule = str(
            (
                context_off["user_prompt_extras"].get("unsupported_boundary_evidence") or {}
            ).get("decision_rule")
            or ""
        )
        assert "not_evaluable" not in decision_rule
        extras_blob = json.dumps(context_off["user_prompt_extras"], ensure_ascii=False)
        assert "not_evaluable" not in extras_blob
        markers_off = context_off["context_governance"]["excluded_clause_markers"]
        assert judge_result_marker in markers_off
        assert "not_evaluable" in markers_off
        for marker in _AUTHORITY_OFF_F_NE_LICENSE_MARKERS:
            assert marker in markers_off

        context_on = candidate_module._build_core_context(
            spec_on, trace, embedding_provider=DeterministicHashEmbeddingProvider()
        )
        markers_on = context_on["context_governance"]["excluded_clause_markers"]
        assert markers_on == [judge_result_marker]
        for marker in _AUTHORITY_OFF_F_NE_LICENSE_MARKERS:
            assert marker not in markers_on

def test_authority_off_catalog_consumption_instructs_search_then_load():
    """Always-on Catalog consumption: Search→Load; stuffed lists are not Evidence.

    Authority-off extras and decision_rule must not leak not_evaluable.
    """
    from pathlib import Path

    from impl.projects.client_search import judge as candidate_module

    spec = load_project("client_search")
    trace = RunTrace(
        trace_id="catalog-consumption:off",
        project_id="client_search",
        input={"query": "30岁女性客户"},
        normalized_request={"query": "30岁女性客户"},
        extracted_output={
            "conditions": [
                {"field": "age", "operator": "MATCH", "value": 30},
                {"field": "sex", "operator": "MATCH", "value": "女"},
            ],
        },
    )
    context = candidate_module._build_core_context(spec, trace)
    extras = context["system_prompt_extras"]
    joined = "\n".join(extras)
    assert "Search→Load" in joined
    assert "investigation.load_entry" in joined
    assert "SearchHit" in joined
    assert "不是 Evidence" in joined
    assert "成因契约" not in joined
    assert "结论类型：职责外" not in joined
    extras_blob = json.dumps(context["user_prompt_extras"], ensure_ascii=False)
    assert "not_evaluable" not in extras_blob
    decision_rule = str(
        (
            context["user_prompt_extras"].get("unsupported_boundary_evidence") or {}
        ).get("decision_rule")
        or ""
    )
    assert "not_evaluable" not in decision_rule
    execution_src = Path(
        "impl/projects/client_search/judge_execution.py"
    ).read_text(encoding="utf-8")
    assert "优先使用 prompt 信息" not in execution_src
    assert context["user_prompt_extras"].get("catalog_consumption", {}).get(
        "locator_not_evidence"
    ) is True


def test_loaded_mapping_facts_strong_hit_and_silent_miss():
    """P2: strong exact mapping Load is a fact; a Catalog miss stays silent."""
    from impl.projects.client_search import judge as candidate_module

    spec = load_project("client_search")
    hit_context = candidate_module._build_core_context(
        spec,
        RunTrace(
            trace_id="mapping-facts:spoken-alias",
            project_id="client_search",
            input={"query": "孤儿单"},
            normalized_request={"query": "孤儿单"},
        ),
    )
    facts = hit_context["user_prompt_extras"]["loaded_mapping_facts"]
    assert facts
    assert any(
        item.get("field") == "orphanType"
        and item.get("spoken") == "孤儿单"
        and "纯存续单" in str(item.get("normalized") or "")
        for item in facts
    )
    for item in facts:
        assert set(item) <= {"field", "spoken", "normalized"}
        assert "score" not in item
        assert "index_key" not in item
        assert "decision_rule" not in item
    joined_hit = "\n".join(hit_context["system_prompt_extras"])
    assert "Search→Load" in joined_hit
    assert "成因契约" not in joined_hit
    assert "结论类型：职责外" not in joined_hit
    assert "not_evaluable" not in json.dumps(
        hit_context["user_prompt_extras"], ensure_ascii=False
    )

    miss_context = candidate_module._build_core_context(
        spec,
        RunTrace(
            trace_id="mapping-facts:silent-miss",
            project_id="client_search",
            input={"query": "合家福"},
            normalized_request={"query": "合家福"},
        ),
    )
    assert miss_context["user_prompt_extras"]["loaded_mapping_facts"] == []
    joined_miss = "\n".join(miss_context["system_prompt_extras"])
    assert "Search→Load" in joined_miss
    assert "成因契约" not in joined_miss
    assert "结论类型：职责外" not in joined_miss
    assert "not_evaluable" not in json.dumps(
        miss_context["user_prompt_extras"], ensure_ascii=False
    )


def _assert_no_not_evaluable_status(result) -> None:
    assert result.overall_fulfillment["status"] != "not_evaluable"
    for item in result.fulfillment_assessments or []:
        status = item.get("status") if isinstance(item, dict) else getattr(item, "status", "")
        assert str(status or "").strip().lower() != "not_evaluable"


def test_authority_off_abort_stays_not_evaluable():
    """LLM/tool abort is not a business NF. At most not_evaluable."""
    from impl.core.judge import _minimal_honest_judge_result, finalize_judge_result
    from impl.projects.client_search.judge_execution import (
        fail_closed_authority_off_judge_result,
    )

    spec_off = load_project("client_search")
    ((spec_off.verifier or {}).setdefault("authority", {}))["enabled_scopes"] = []
    spec_on = _authority_spec()
    trace = RunTrace(
        trace_id="abort-tool-budget",
        project_id="client_search",
        input={"query": "查找目标客户"},
    )
    abort_data = {
        "error": "tool_budget_exceeded",
        "raw_text": "actual tool calls 10 exceed configured limit 8",
    }

    core = _minimal_honest_judge_result(spec_off, trace, abort_data)
    assert core.overall_fulfillment["status"] == "not_evaluable"
    assert list(core.fulfillment_assessments or []) == []
    assert "llm_call_failed" in list(core.evidence or [])

    off = finalize_judge_result(
        fail_closed_authority_off_judge_result(spec_off, core)
    )
    assert off.overall_fulfillment["status"] == "not_evaluable"
    assert list(off.fulfillment_assessments or []) == []
    assert "llm_call_failed" in list(off.evidence or [])
    assert "核心业务交付" not in [
        item.get("expectation_id") if isinstance(item, dict) else getattr(item, "expectation_id", "")
        for item in (off.business_expectations or [])
    ]

    on_core = _minimal_honest_judge_result(spec_on, trace, abort_data)
    on = finalize_judge_result(
        fail_closed_authority_off_judge_result(spec_on, on_core)
    )
    assert on.overall_fulfillment["status"] == "not_evaluable"


def test_authority_off_llm_cooling_stays_not_evaluable():
    from impl.core.judge import finalize_judge_result
    from impl.core.schema import JudgeResult
    from impl.projects.client_search.judge_execution import (
        fail_closed_authority_off_judge_result,
    )

    spec_off = load_project("client_search")
    ((spec_off.verifier or {}).setdefault("authority", {}))["enabled_scopes"] = []
    cooling = JudgeResult(
        trace_id="llm-cooling",
        project_id="client_search",
        business_expectations=[],
        fulfillment_assessments=[],
        overall_fulfillment={"status": "not_evaluable", "assessment_count": 0},
        reasoning_summary="LLM 调用失败，未做出算法判断: all llm endpoints are cooling",
        evidence=["llm_call_failed"],
    )
    off = finalize_judge_result(
        fail_closed_authority_off_judge_result(spec_off, cooling)
    )
    assert off.overall_fulfillment["status"] == "not_evaluable"
    assert list(off.fulfillment_assessments or []) == []


def test_authority_off_empty_assessments_fail_closed_to_not_fulfilled():
    from impl.core.judge import finalize_judge_result
    from impl.core.schema import FulfillmentAssessment, JudgeResult
    from impl.projects.client_search.judge_execution import (
        fail_closed_authority_off_judge_result,
    )

    spec_off = load_project("client_search")
    ((spec_off.verifier or {}).setdefault("authority", {}))["enabled_scopes"] = []
    empty = JudgeResult(
        trace_id="empty-assessments",
        project_id="client_search",
        business_expectations=[],
        fulfillment_assessments=[],
        overall_fulfillment={"status": "not_evaluable", "assessment_count": 0},
    )
    off = finalize_judge_result(
        fail_closed_authority_off_judge_result(spec_off, empty)
    )
    assert off.overall_fulfillment["status"] == "not_fulfilled"
    _assert_no_not_evaluable_status(off)

    ne_assessment = JudgeResult(
        trace_id="ne-assessment",
        project_id="client_search",
        business_expectations=[{
            "expectation_id": "核心业务交付",
            "blocking": True,
            "expected_outcome": "交付用户请求",
        }],
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="核心业务交付",
                status="not_evaluable",
                actual_evidence=["llm produced no usable judgment"],
            )
        ],
        overall_fulfillment={"status": "not_evaluable"},
    )
    remapped = finalize_judge_result(
        fail_closed_authority_off_judge_result(spec_off, ne_assessment)
    )
    assert remapped.overall_fulfillment["status"] == "not_fulfilled"
    _assert_no_not_evaluable_status(remapped)


def test_authority_off_extras_do_not_force_inclusive_below_or_ban_lt():
    """Generic 以下/LT: Authority-off extras compare live operator; LT n is legal."""
    from impl.projects.client_search import judge as candidate_module
    from impl.projects.client_search.judge import _LIVE_OPERATOR_DELIVERY_PROTOCOL

    spec = load_project("client_search")
    ((spec.verifier or {}).setdefault("authority", {}))["enabled_scopes"] = []
    from impl.core.authority_scopes import in_run_authority_enabled
    assert in_run_authority_enabled(spec) is False
    trace = RunTrace(
        trace_id="live-operator-protocol",
        project_id="client_search",
        input={"query": "n周岁以下客户"},
        normalized_request={"query": "n周岁以下客户"},
        extracted_output={
            "conditions": [{"field": "clientAge", "operator": "LT", "value": "n"}],
        },
    )
    context = candidate_module._build_core_context(
        spec, trace, embedding_provider=DeterministicHashEmbeddingProvider()
    )
    extras = context["system_prompt_extras"]
    joined = "\n".join(extras)
    assert _LIVE_OPERATOR_DELIVERY_PROTOCOL in extras
    assert "含本数" not in joined
    assert "不支持LT" not in joined
    assert "不包括LT" not in joined
    assert "`LT n`" in joined
    assert "n周岁以下" in joined
    assert "RANGE-including-n" in joined
    assert "SearchHit" in joined
    assert "058" not in joined
    assert "少儿" not in joined
    assert "17周岁" not in joined
    consumption = context["user_prompt_extras"].get("catalog_consumption") or {}
    assert consumption.get("locator_not_evidence") is True
    assert consumption.get("compare_live_operator_as_delivered") is True
    assert consumption.get("exclusive_below_lt_valid_without_loaded_inclusive_rule") is True
    assert consumption.get("parser_generation_recipes_not_fulfillment_oracle") is True
    assert "含边界" not in joined
    assert "unless a Loaded mapping/rule says so" not in joined
    assert "明确要求含边界" not in joined
    assert "parser 生成配方" in joined
    enhanced = context["user_prompt_extras"].get("enhanced_rules") or {}
    for rule in enhanced.get("rules") or []:
        assert set(rule) <= {"name", "field"}
        assert "operator" not in rule
        assert "patterns" not in rule
        assert "value" not in rule
        assert "merge_to_llm" not in rule
    enhanced_blob = json.dumps(enhanced, ensure_ascii=False)
    assert '"operator"' not in enhanced_blob
    assert '"patterns"' not in enhanced_blob
    assert candidate_module._JUDGE_TOOL_CALL_LIMIT == 8
    assert candidate_module._FIELD_NAVIGATION_CALL_LIMIT == 4


def test_stuffed_enhanced_rules_skip_merge_to_llm_false_bodies():
    """Stuffed extras are locator keys; merge_to_llm false bodies are not dumped."""
    from impl.projects.client_search.enhanced_rules_key_index import (
        build_enhanced_rules_key_index,
        retrieve_enhanced_rules_for_fields,
    )

    index = build_enhanced_rules_key_index("client_search")
    compact = retrieve_enhanced_rules_for_fields(["clientAge"])
    stuffed_names = {item.get("name") for item in compact.get("rules") or []}
    hidden = [
        str(item.get("name") or "").strip()
        for item in index.get("clientAge") or []
        if isinstance(item, dict) and item.get("merge_to_llm") is False
    ]
    assert hidden
    assert stuffed_names.isdisjoint(hidden)
    for rule in compact.get("rules") or []:
        assert set(rule) <= {"name", "field"}
    blob = json.dumps(compact.get("rules") or [], ensure_ascii=False)
    assert '"operator"' not in blob
    assert '"patterns"' not in blob
    assert '"value"' not in blob


def test_field_navigation_search_does_not_consume_load_budget():
    """Search is free; Load/search_definition spend the 4-call budget.

    A strong hit only stops retries of that same query, so a later constraint
    can still Search. Same-query retries with different kwargs are blocked.
    """
    from impl.projects.client_search.catalog import (
        MAPPINGS_INDEX_KEY,
        STRONG_HIT_FLOOR,
    )
    from impl.projects.client_search.judge import (
        _FIELD_NAVIGATION_CALL_LIMIT,
        _JUDGE_TOOL_CALL_LIMIT,
        _build_judge_tools,
    )

    spec = load_project("client_search")
    tools = _build_judge_tools(spec)
    by_name = {tool.name: tool for tool in tools}
    search = by_name["investigation_search_index"]
    load = by_name["investigation_load_entry"]
    definition = by_name["field_search_definition"]
    assert _JUDGE_TOOL_CALL_LIMIT == 8
    assert _FIELD_NAVIGATION_CALL_LIMIT == 4

    miss = search.entrypoint(query="十里堡")
    assert miss.status == "succeeded"
    assert not (miss.actual or {}).get("candidates")

    hit = search.entrypoint(query="孤儿单")
    assert hit.status == "succeeded"
    candidates = (hit.actual or {}).get("candidates") or []
    assert any(float(item.get("score") or 0) >= STRONG_HIT_FLOOR for item in candidates)

    other_constraint = search.entrypoint(query="clientAge")
    assert other_constraint.status == "succeeded"

    blocked = search.entrypoint(query="孤儿单", limit=3)
    assert blocked.status == "inconclusive"
    assert "strong hit already available" in (blocked.error or "")
    assert (blocked.runtime_metadata or {}).get("stop_reason") == (
        "strong_hit_already_available"
    )

    mapping = load.entrypoint(index_key=MAPPINGS_INDEX_KEY, key="orphanType::孤儿单")
    assert mapping.status == "succeeded"
    content = (mapping.actual or {}).get("content") or {}
    assert content.get("field") == "orphanType"
    assert content.get("spoken") == "孤儿单"

    loads = [
        definition.entrypoint(field="clientAge"),
        definition.entrypoint(field="clientSex"),
        definition.entrypoint(field="clientBirthday"),
    ]
    assert all(item.status == "succeeded" for item in loads)
    exhausted = definition.entrypoint(field="clientCity")
    assert exhausted.status == "inconclusive"
    assert (exhausted.runtime_metadata or {}).get("budget_kind") == "field_navigation"

