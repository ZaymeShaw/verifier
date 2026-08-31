"""Authority 运行时最小链路测试：Environment 构造、evidence_refs 物化、resolve 校验。

对应 spec/alg/authority.md §4.2 / §13.3 / §5。
"""
from __future__ import annotations

import pytest

from impl.core.authority_environment import (
    AuthorityEnvironmentInvalid,
    AuthorityToolProtocolViolation,
    _validate_authority_tool_sequence,
    _validate_declared_source_hash,
    _resolve_system_prompt,
    build_authority_environment,
    resolve_authority,
)
from impl.core.context.embedding import DeterministicHashEmbeddingProvider
from impl.core.project_loader import load_project
from impl.core.schema import AuthorityRequest


@pytest.fixture(scope="module")
def client_search_spec():
    spec = load_project("client_search")
    authority = (spec.verifier or {}).setdefault("authority", {})
    authority["enabled_scopes"] = [
        "responsibility",
        "semantic_mapping",
        "query_equivalence",
        "conflict_arbitration",
    ]
    return spec


@pytest.fixture()
def authority_env(client_search_spec):
    return build_authority_environment(
        client_search_spec,
        role="judge",
        use_candidate=True,
        embedding_provider=DeterministicHashEmbeddingProvider(),
        # 业务源哈希漂移属已知环境状态（用户指示不处理）；warn 策略让测试
        # 聚焦 authority 运行时行为本身，不被上游漂移挡住。
        business_source_staleness_policy="warn",
    )


class FakeLlm:
    _caller = "authority"

    def __init__(self, data):
        self.data = data
        self.system = ""
        self.user = ""

    def complete_json(self, system, user, trace_id=None, output_spec=None, **_kwargs):
        self.system = system
        self.user = user
        return dict(self.data)


def test_declared_evidence_hash_is_verified_against_actual_bytes(tmp_path):
    source = tmp_path / "evidence.yaml"
    source.write_bytes(b"rules: []\n")
    actual = "e0dfa70eb69d47fe9cb2be8a4fcd53e74cf7fe26fcbb1f06912b57a9c028e4e0"

    assert _validate_declared_source_hash("ref-1", source, actual) == actual

    with pytest.raises(AuthorityEnvironmentInvalid) as caught:
        _validate_declared_source_hash("ref-1", source, "0" * 64)

    error = caught.value.errors[0]
    assert error["stage"] == "source_hash_validation"
    assert error["expected_sha256"] == "0" * 64
    assert error["actual_sha256"] == actual


def test_authority_tool_sequence_requires_loading_returned_candidates():
    search = {
        "tool_name": "search_context_units",
        "result": '{"candidates":[{"selection_ref":"sel-1"}]}',
    }
    load = {"tool_name": "load_context_units", "result": "[]"}
    _validate_authority_tool_sequence([search, load])

    with pytest.raises(AuthorityToolProtocolViolation, match="immediately followed"):
        _validate_authority_tool_sequence([
            search,
            {"tool_name": "investigation_search_index", "result": "{}"},
        ])

    with pytest.raises(AuthorityToolProtocolViolation, match="stopped after Search"):
        _validate_authority_tool_sequence([search])


def test_authority_tool_sequence_requires_loading_navigation_targets():
    calls = [
        {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
        {
            "tool_name": "investigation_load_entry",
            "result": '{"load_targets":["sel-2"]}',
        },
        {"tool_name": "load_context_units", "result": "[]"},
    ]
    _validate_authority_tool_sequence(calls)


def test_authority_tool_sequence_accepts_value_retrieval_after_empty_search():
    """Search 空 → search_index 值级检索 → load_entry → Load 是合法序列。"""
    calls = [
        {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
        {
            "tool_name": "investigation_search_index",
            "result": '{"candidates":[{"key":"orphanType","target_ref":"evidence-navigation://business-field-enums/orphanType"}]}',
        },
        {
            "tool_name": "investigation_load_entry",
            "result": '{"load_targets":["sel-2"]}',
        },
        {"tool_name": "load_context_units", "result": '[{"id":"authority-ref-x"}]'},
    ]
    _validate_authority_tool_sequence(calls)


def test_authority_tool_sequence_requires_loading_after_search_index_candidates():
    """search_index 返回候选后必须 load_entry；不能停在导航候选上。"""
    search_index = {
        "tool_name": "investigation_search_index",
        "result": '{"candidates":[{"target_ref":"evidence-navigation://ref/f"}]}',
    }
    load_entry = {
        "tool_name": "investigation_load_entry",
        "result": '{"load_targets":["sel-2"]}',
    }
    load = {"tool_name": "load_context_units", "result": "[]"}
    _validate_authority_tool_sequence([
        {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
        search_index,
        load_entry,
        load,
    ])

    with pytest.raises(AuthorityToolProtocolViolation, match="stopped after key-index"):
        _validate_authority_tool_sequence([
            {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
            search_index,
            load,
        ])

    with pytest.raises(AuthorityToolProtocolViolation, match="stopped after key-index"):
        _validate_authority_tool_sequence([
            {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
            search_index,
        ])


def test_authority_tool_sequence_allows_batched_key_index_searches():
    """多次 investigation_search_index 的批量检索是合法导航，只要最终被 load_entry 消费。"""
    calls = [
        {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
        {"tool_name": "investigation_search_index", "result": '{"candidates":[{"target_ref":"coverage-gap://responsibility-boundary-unsupported-field"}]}'},
        {"tool_name": "investigation_search_index", "result": '{"candidates":[{"target_ref":"evidence-navigation://business-field-definitions/licensePlateNo"}]}'},
        {"tool_name": "investigation_load_entry", "result": '{"load_targets":["sel-x"]}'},
        {"tool_name": "load_context_units", "result": "[]"},
    ]
    _validate_authority_tool_sequence(calls)


def test_authority_tool_sequence_disallows_dangling_batched_searches():
    """批量 search_index 后若没有 load_entry 消费候选，仍拒绝。"""
    calls = [
        {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
        {"tool_name": "investigation_search_index", "result": '{"candidates":[{"target_ref":"evidence-navigation://field/f"}]}'},
        {"tool_name": "investigation_search_index", "result": '{"candidates":[{"target_ref":"evidence-navigation://field/g"}]}'},
        {"tool_name": "load_context_units", "result": "[]"},
    ]
    with pytest.raises(AuthorityToolProtocolViolation, match="stopped after key-index"):
        _validate_authority_tool_sequence(calls)


def test_authority_tool_sequence_allows_self_contained_navigation_terminal():
    """navigation_only 的 load_entry 内容自包含，可合法作为终态调用（不强制后续 Load）。"""
    calls = [
        {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
        {
            "tool_name": "investigation_search_index",
            "result": '{"candidates":[{"target_ref":"coverage-gap://responsibility-boundary-unsupported-field"}]}',
        },
        {
            "tool_name": "investigation_load_entry",
            "result": '{"load_targets":["sel-x"],"content":{"coverage_gap":{},"navigation_only":true}}',
        },
    ]
    _validate_authority_tool_sequence(calls)


def test_authority_tool_sequence_still_rejects_non_self_terminal_load_entry():
    """非 navigation_only 的 load_entry 作为终态（未 Load）仍拒绝。"""
    calls = [
        {"tool_name": "search_context_units", "result": '{"candidates":[]}'},
        {
            "tool_name": "investigation_load_entry",
            "result": '{"load_targets":["sel-2"]}',
        },
    ]
    with pytest.raises(AuthorityToolProtocolViolation, match="stopped after navigation"):
        _validate_authority_tool_sequence(calls)


def test_environment_materializes_manifest_evidence_refs(authority_env):
    """§13.3：manifest evidence_refs 物化为 authority-ref-* ContextUnit，ref_id 存 tags。

    声明了 slice 的大 YAML（field_definitions / enhanced_rules）不再注册整文件单元，
    改为字段级切片（content 内联，content_ref 为空）；其余 ref 仍整文件物化。
    """
    assert authority_env.registration_errors == []
    catalog = authority_env.context_run.context_unit_catalog()
    evidence_ids = [
        item["context_unit_id"]
        for item in catalog
        if item["context_unit_id"].startswith("authority-ref-")
    ]
    records = [
        authority_env.context_runtime.registry.get(unit_id)["record"]
        for unit_id in evidence_ids
    ]
    yaml_list_chunks = [
        record for record in records
        if record.tags.get("slice") == "yaml_list_chunk"
    ]
    mapping_field_slices = [
        record for record in records
        if record.tags.get("slice") == "yaml_mapping_field"
    ]
    assert len(yaml_list_chunks) > 1
    assert any(
        record.tags.get("field") == "orphanType"
        and record.tags.get("ref_id") == "business-field-enums"
        for record in mapping_field_slices
    )
    assert any(
        record.tags.get("field") == "orphanType"
        and record.tags.get("ref_id") == "business-value-mappings"
        and "孤儿单" in (record.content or "")
        for record in mapping_field_slices
    )
    # manifest 重命名/移除 ref 后，旧单元不得继续出现在证据空间 catalog
    assert not any(
        authority_env.context_runtime.registry.get(unit_id)["record"].tags.get("ref_id")
        == "authority-conflicts-scan-20"
        for unit_id in evidence_ids
    )
    assert not any(
        authority_env.context_runtime.registry.get(unit_id)["record"].tags.get("ref_id")
        in {"authority-conflicts-scan", "judge-authority-resolutions"}
        for unit_id in evidence_ids
    )
    for unit_id in evidence_ids:
        entry = authority_env.context_runtime.registry.get(unit_id)
        assert entry is not None
        record = entry["record"]
        assert record.unit_type == "evidence_ref"
        assert record.scope == "project_static"
        assert record.tags.get("ref_id"), f"ref_id must be kept as source alias: {unit_id}"
        # 物化后 hash 可校验
        assert entry.get("source_hash")
    # 切片单元：内联 content、tags 带 field/slice=field、单单元远小于 Load 预算
    slices = [
        authority_env.context_runtime.registry.get(unit_id)["record"]
        for unit_id in evidence_ids
        if authority_env.context_runtime.registry.get(unit_id)["record"].tags.get("slice") == "field"
    ]
    assert len(slices) > 1
    # 三类物化单元应完整分区；不把资料数、业务字段数或 list chunk 数固化进测试。
    unsliced = [
        record for record in records
        if record.tags.get("slice") not in {"field", "yaml_mapping_field", "yaml_list_chunk"}
    ]
    assert len(evidence_ids) == (
        len(unsliced) + len(slices) + len(mapping_field_slices) + len(yaml_list_chunks)
    )
    for record in slices:
        assert record.content is not None and record.content_ref is None
        assert record.tags.get("field")
        assert len(record.content) <= 100_000
    for record in yaml_list_chunks:
        assert record.content is not None and record.content_ref is None
        assert record.tags.get("root_key") == "polNoInfo.plancodeinfo.planfullname"
        assert len(record.content) <= 100_000
    assert any("住院医疗保险" in record.description for record in yaml_list_chunks)
    # 切片单元可被 Load，且引用校验通过（hash 未变）
    loaded = authority_env.context_run.load_context_units([slices[0].id])
    assert loaded and loaded[0].id == slices[0].id
    assert authority_env.ref_loaded_unchanged(slices[0].id)
    # 未声明切片的 ref 仍整文件物化（content_ref 指向原始文件）
    whole_file = next(
        authority_env.context_runtime.registry.get(unit_id)["record"]
        for unit_id in evidence_ids
        if authority_env.context_runtime.registry.get(unit_id)["record"].tags.get("slice") is None
    )
    assert whole_file.content is None and whole_file.content_ref.startswith("file://")


def test_environment_fail_closed_on_missing_source(client_search_spec):
    """§13.3：已有 EvidenceRef 找不到原始来源 → Environment 构造失败（fail-closed）。

    显式 use_candidate=False 读 production 包（judge draft 开关开启后
    use_candidate=True 会读 draft 包，与本测试意图无关）。
    """
    manifest_path = (
        client_search_spec.project_package_path(must_exist=False)
        / "investigation/judge/manifest.json"
    )
    raw = manifest_path.read_text(encoding="utf-8")
    broken = raw.replace(
        '"location": "src/main/python/data/client_search_query_parse/time_knowledge_args.yaml"',
        '"location": "docs/evidence/does-not-exist.md"',
    )
    manifest_path.write_text(broken, encoding="utf-8")
    try:
        with pytest.raises(FileNotFoundError):
            build_authority_environment(
                client_search_spec,
                role="judge",
                use_candidate=False,
                embedding_provider=DeterministicHashEmbeddingProvider(),
                business_source_staleness_policy="warn",
            )
    finally:
        manifest_path.write_text(raw, encoding="utf-8")


def _env_with_unit(authority_env):
    """取一个已物化的 evidence unit_id 供 basis 引用。"""
    catalog = authority_env.context_run.context_unit_catalog()
    return next(
        item["context_unit_id"]
        for item in catalog
        if item["context_unit_id"].startswith("authority-ref-")
    )


def _loaded_unit_id(authority_env):
    """模拟 Agent 的真实 Load 往返：加载一个物化 evidence unit 并返回其 unit_id。"""
    unit_id = _env_with_unit(authority_env)
    units = authority_env.context_run.load_context_units([unit_id])
    assert units and units[0].id == unit_id
    return unit_id



def test_authority_prompt_requires_reformulation_before_unresolved(authority_env):
    llm = FakeLlm({
        "status": "unresolved",
        "statement": "",
        "reason": "决定性资料不足。",
        "basis_evidence_ref_ids": [],
        "required_evidence": ["决定性资料"],
    })
    resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="某个新概念是否受支持？"),
        llm=llm,
    )
    assert "必须至少改写一次 query" in llm.system
    assert "回到 Context Search/Load" in llm.system
    assert "只有完成上述检索" in llm.system

def test_resolve_resolved_requires_basis(authority_env):
    unit_id = _loaded_unit_id(authority_env)
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="下游正式接口允许哪些字段？"),
        llm=FakeLlm({
            "status": "resolved",
            "statement": "使用当前配置声明的字段集合。",
            "reason": "字段配置唯一决定当前校验范围。",
            "basis_evidence_ref_ids": [unit_id],
            "required_evidence": [],
        }),
    )
    assert resolution.status == "resolved"
    assert resolution.statement
    assert resolution.basis_evidence_ref_ids == (unit_id,)


def test_resolve_unresolved_requires_evidence(authority_env):
    unit_id = _loaded_unit_id(authority_env)
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="正式业务规范允许哪些字段？"),
        llm=FakeLlm({
            "status": "unresolved",
            "statement": "",
            "reason": "当前资料只证明实现行为，不决定正式契约。",
            "basis_evidence_ref_ids": [unit_id],
            "required_evidence": ["带版本的下游正式接口字段契约"],
        }),
    )
    assert resolution.status == "unresolved"
    assert not resolution.statement
    assert resolution.required_evidence == ("带版本的下游正式接口字段契约",)


def test_resolve_resolved_without_basis_downgrades_to_unresolved(authority_env):
    """resolved 却无任何 basis 依据：不得以无依据的 statement 定论。

    §8.4：LLM 业务输出不合规 ≠ 工具执行失败；归一化为 unresolved（依据不充分），
    不落入 tool_failure。
    """
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="当前行为如何校验字段？"),
        llm=FakeLlm({
            "status": "resolved",
            "statement": "结论",
            "reason": "理由",
            "basis_evidence_ref_ids": [],
            "required_evidence": [],
        }),
    )
    assert resolution.status == "unresolved"
    assert not resolution.statement
    assert "basis" in resolution.reason
    assert resolution.required_evidence

def test_resolve_unresolved_with_statement_merges_into_reason(authority_env):
    """unresolved 时 LLM 偶发多填 statement：并入 reason 保留信息，不抛错。"""
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="某定义是否存在冲突？"),
        llm=FakeLlm({
            "status": "unresolved",
            "statement": "不应出现的结论",
            "reason": "冲突",
            "basis_evidence_ref_ids": [],
            "required_evidence": ["更多资料"],
        }),
    )
    assert resolution.status == "unresolved"
    assert not resolution.statement
    assert "不应出现的结论" in resolution.reason
    assert resolution.required_evidence == ("更多资料",)


def test_resolve_invalid_basis_downgrades_to_unresolved(authority_env):
    """138 形态：resolved 引用的依据全部无法核验 → 降级 unresolved（依据不充分）。"""
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="某定义是否可确定？"),
        llm=FakeLlm({
            "status": "resolved",
            "statement": "结论",
            "reason": "理由",
            "basis_evidence_ref_ids": ["not-a-materialized-unit"],
            "required_evidence": [],
        }),
    )
    assert resolution.status == "unresolved"
    assert not resolution.statement
    assert "无法核验" in resolution.reason or "not-a-materialized-unit" in resolution.reason
    assert resolution.basis_evidence_ref_ids == ()


def test_resolve_basis_not_loaded_in_run_downgrades_to_unresolved(authority_env):
    """§12.1：catalog 里存在但本 run 未 Load 的 unit 不能进入 basis。

    未 Load 即依据未核验，resolved 降级为 unresolved，而不是工具执行失败。
    """
    unit_id = _env_with_unit(authority_env)
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="某定义是否可确定？"),
        llm=FakeLlm({
            "status": "resolved",
            "statement": "结论",
            "reason": "理由",
            "basis_evidence_ref_ids": [unit_id],
            "required_evidence": [],
        }),
    )
    assert resolution.status == "unresolved"
    assert not resolution.statement
    assert resolution.basis_evidence_ref_ids == ()


def test_resolve_partial_invalid_basis_keeps_resolved_with_valid_units(authority_env):
    """resolved 引用的依据部分无效：过滤无效引用，保留已核验依据仍可定论。"""
    unit_id = _loaded_unit_id(authority_env)
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="某定义是否可确定？"),
        llm=FakeLlm({
            "status": "resolved",
            "statement": "结论",
            "reason": "理由",
            "basis_evidence_ref_ids": [unit_id, "not-a-materialized-unit"],
            "required_evidence": [],
        }),
    )
    assert resolution.status == "resolved"
    assert resolution.statement == "结论"
    assert resolution.basis_evidence_ref_ids == (unit_id,)

def _materialized_evidence_unit_id(authority_env):
    """取当前 manifest 中的整文件 evidence 单元（不依赖搜索排序）。"""
    catalog = authority_env.context_run.context_unit_catalog()
    return next(
        item["context_unit_id"]
        for item in catalog
        if "business-time-knowledge" in item["name"]
    )


def test_authority_agent_load_exposes_materialized_unit_id(authority_env):
    """P0：Authority Agent 的 Load 工具返回物化 unit_id，resolve 接受真实往返引用。"""
    from impl.core.authority_environment import AuthorityContextTools

    tools = AuthorityContextTools(authority_env.context_run)
    loaded = tools.load_context_units([_materialized_evidence_unit_id(authority_env)])
    assert loaded
    selection_ref = loaded[0]["selection_ref"]
    assert selection_ref.startswith("C")
    unit_id = loaded[0]["unit_id"]
    assert unit_id.startswith("authority-ref-")
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="当前业务时间知识是否有权威依据？"),
        llm=FakeLlm({
            "status": "resolved",
            "statement": "采用该业务资料作为依据。",
            "reason": "该物化资料记录当前业务时间知识。",
            "basis_evidence_ref_ids": [unit_id],
            "required_evidence": [],
        }),
    )
    assert resolution.status == "resolved"
    assert resolution.basis_evidence_ref_ids == (unit_id,)


def test_resolve_backfills_loaded_selection_ref_to_materialized_unit_id(authority_env):
    """P0 兜底：LLM 误填本次 Load 返回的 selection_ref 时回填为物化 unit_id。"""
    from impl.core.authority_environment import AuthorityContextTools

    tools = AuthorityContextTools(authority_env.context_run)
    loaded = tools.load_context_units([_materialized_evidence_unit_id(authority_env)])
    selection_ref = loaded[0]["selection_ref"]
    tools.load_context_units([selection_ref])
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="当前业务时间知识是否有权威依据？"),
        llm=FakeLlm({
            "status": "resolved",
            "statement": "采用该业务资料作为依据。",
            "reason": "该物化资料记录当前业务时间知识。",
            "basis_evidence_ref_ids": [selection_ref],
            "required_evidence": [],
        }),
    )
    assert len(resolution.basis_evidence_ref_ids) == 1
    assert resolution.basis_evidence_ref_ids[0].startswith("authority-ref-")
    assert resolution.basis_evidence_ref_ids[0] != selection_ref


def test_authority_environment_run_narrowed_by_trace_and_case(client_search_spec):
    """§4.2：ContextRun 权限与 trace/case 相交收窄。"""
    env = build_authority_environment(
        client_search_spec,
        role="judge",
        use_candidate=True,
        embedding_provider=DeterministicHashEmbeddingProvider(),
        trace_id="trace-authority-narrow",
        case_id="case-authority-narrow",
        business_source_staleness_policy="warn",
    )
    policy = env.context_run.debug_snapshot()["context_debug"]["policy"]
    assert policy["trace_id"] == "trace-authority-narrow"
    assert policy["case_id"] == "case-authority-narrow"


def test_environment_snapshot_ignores_registry_create_vs_reuse(client_search_spec):
    first = build_authority_environment(
        client_search_spec,
        role="judge",
        use_candidate=True,
        embedding_provider=DeterministicHashEmbeddingProvider(),
        trace_id="stable-trace",
        case_id="stable-case",
        business_source_staleness_policy="warn",
    )
    second = build_authority_environment(
        client_search_spec,
        role="judge",
        use_candidate=True,
        embedding_provider=DeterministicHashEmbeddingProvider(),
        trace_id="stable-trace",
        case_id="stable-case",
        business_source_staleness_policy="warn",
    )

    assert first.environment_snapshot_sha256 == second.environment_snapshot_sha256


def test_authority_tool_dedupes_same_question_within_task(authority_env):
    """§10：相同完整问题 + Environment snapshot 在一次任务内不重复调用。"""
    from impl.core.authority_tool import build_authority_resolve_tool

    tool = build_authority_resolve_tool(
        authority_env,
        llm=FakeLlm({
            "status": "unresolved",
            "statement": "",
            "reason": "正式定义资料冲突且无生效版本声明。",
            "basis_evidence_ref_ids": [],
            "required_evidence": ["当前生效版本、审批记录或替代关系"],
        }),
    )
    first = tool._execute(
        "高净值客户应采用哪一种正式定义？",
        question_class="semantic_mapping",
    )
    second = tool._execute(
        "高净值客户应采用哪一种正式定义？",
        question_class="semantic_mapping",
    )
    assert second["tool_call_id"] == first["tool_call_id"]
    assert len(tool.audit) == 1


def test_authority_tool_call_isolates_evidence_run_between_resolves(authority_env):
    """每次 authority.resolve 调用都是独立证据 run：basis 不能引用先前调用
    留下的 Load 记录，后续调用的 context_coverage 也不继承历史痕迹。"""
    from impl.core.authority_environment import AuthorityContextTools
    from impl.core.authority_tool import build_authority_resolve_tool

    class SequencedLlm:
        _caller = "authority"

        def __init__(self, responses):
            self.responses = list(responses)
            self.index = 0

        def complete_json(self, system, user, trace_id=None, output_spec=None, **_kwargs):
            data = dict(self.responses[self.index])
            self.index += 1
            return data

    unit_id = _materialized_evidence_unit_id(authority_env)
    AuthorityContextTools(authority_env.context_run).load_context_units([unit_id])

    tool = build_authority_resolve_tool(
        authority_env,
        llm=SequencedLlm([
            {
                "status": "unresolved",
                "statement": "",
                "reason": "第一次调用依据不充分。",
                "basis_evidence_ref_ids": [],
                "required_evidence": ["补充资料"],
            },
            {
                "status": "resolved",
                "statement": "第二次结论",
                "reason": "引用上一次调用留下的证据。",
                "basis_evidence_ref_ids": [unit_id],
                "required_evidence": [],
            },
        ]),
    )
    tool._execute("第一次问题", question_class="semantic_mapping")
    second = tool._execute("第二次问题", question_class="semantic_mapping")
    assert second["status"] == "unresolved"
    assert second["basis_evidence_ref_ids"] == []


def test_resolve_rejects_empty_question(authority_env):
    with pytest.raises(ValueError, match="decision_question"):
        resolve_authority(
            authority_env,
            AuthorityRequest(decision_question="   "),
            llm=FakeLlm({
                "status": "unresolved",
                "statement": "",
                "reason": "r",
                "required_evidence": ["e"],
            }),
        )


def test_resolve_tool_audit_then_gate(authority_env):
    """端到端：resolve tool 执行 → audit 收集 → gate 后处理消费。"""
    from impl.core.authority_gate import apply_authority_gate
    from impl.core.authority_tool import build_authority_resolve_tool
    from impl.core.schema import (
        BusinessExpectation,
        FulfillmentAssessment,
        JudgeResult,
    )

    tool = build_authority_resolve_tool(
        authority_env,
        llm=FakeLlm({
            "status": "unresolved",
            "statement": "",
            "reason": "正式定义资料冲突且无生效版本声明。",
            "basis_evidence_ref_ids": [],
            "required_evidence": ["当前生效版本、审批记录或替代关系"],
        }),
    )
    result = tool._execute(
        "高净值客户应采用哪一种正式定义？",
        question_class="semantic_mapping",
    )
    assert result["status"] == "unresolved"
    assert result["tool_call_id"] in tool.audit
    assert tool.audit[result["tool_call_id"]]["environment_snapshot_sha256"] == (
        authority_env.environment_snapshot_sha256
    )

    judge_result = JudgeResult(
        trace_id="t-e2e",
        project_id=authority_env.project_id,
        business_expectations=[
            BusinessExpectation(expectation_id="e-high", blocking=True),
        ],
        fulfillment_assessments=[
            FulfillmentAssessment(
                expectation_id="e-high",
                status="fulfilled",
                authority_tool_call_ids=[result["tool_call_id"]],
            ),
        ],
    )
    out = apply_authority_gate(judge_result, tool.audit)
    assessment = out.fulfillment_assessments[0]
    assert assessment.status == "not_evaluable"
    entry = next(
        item for item in assessment.evidence_refs
        if item.get("kind") == "authority_unresolved"
    )
    assert entry["tool_call_id"] == result["tool_call_id"]
    assert entry["required_evidence"]


def test_authority_material_decision_index_is_navigation_only(authority_env):
    tool_ids = {tool.tool_id for tool in authority_env.navigation_tools}
    assert tool_ids == {"investigation.search_index", "investigation.load_entry"}
    assert not tool_ids & {tool.tool_id for tool in authority_env.gateway_tools}

    search = next(tool for tool in authority_env.navigation_tools if tool.tool_id == "investigation.search_index")
    index_parameter = search.parameters["properties"]["index_key"]
    assert set(index_parameter["enum"]) == {
        "authority.material-decisions",
        "authority.evidence.business-enhanced-rules",
        "authority.evidence.business-field-definitions",
        "authority.evidence.business-field-enums",
        "authority.evidence.business-value-mappings",
        "material.business-planfullname-enums.values",
    }
    assert "collection_ref=authority-investigation-report" in search.description
    assert "target_kind=material_decision" in search.description
    assert "collection_ref=business-planfullname-enums" in search.description
    assert "target_kind=evidence_locator" in search.description
    assert "住院医疗保险" not in search.description
    assert "阖家团圆康" not in search.description
    # 第一层只按资料能力定位 MaterialDecision，不把 case 枚举值塞入集合索引。
    material_result = search.execute_fn(
        index_key="authority.material-decisions",
        query="产品全称合法值空间",
        limit=5,
    )
    assert material_result.status == "succeeded"
    material_keys = {c["key"] for c in material_result.actual["candidates"]}
    assert "business-planfullname-enums.decision-1" in material_keys

    # 第二层在大资料内部索引具体值；首段、中段、尾段都必须可召回。
    for value in ("住院医疗保险", "阖家团圆康"):
        value_result = search.execute_fn(
            index_key="material.business-planfullname-enums.values",
            query=value,
            limit=3,
        )
        assert value_result.status == "succeeded"
        assert value_result.actual["candidates"], value
        key = value_result.actual["candidates"][0]["key"]
        loaded = next(
            tool for tool in authority_env.navigation_tools
            if tool.tool_id == "investigation.load_entry"
        ).execute_fn(
            index_key="material.business-planfullname-enums.values", key=key
        )
        assert loaded.status == "succeeded"
        content = loaded.actual["content"]
        assert content["source_ref_id"] == "business-planfullname-enums"
        assert content["navigation_only"] is True
        assert "load_targets" not in content
        assert loaded.actual["load_targets"]
        assert all(item.startswith("C") for item in loaded.actual["load_targets"])
        assert loaded.actual["target_resolution"]["status"] == "resolved"
        assert loaded.actual["target_resolution"]["strategy"] == "yaml-list-range-overlap"
        units = authority_env.context_run.load_context_units(
            loaded.actual["load_targets"]
        )
        assert units
        assert any(value in unit.content for unit in units)


def test_authority_context_search_caps_each_query_to_three(authority_env, monkeypatch):
    from impl.core.authority_environment import AuthorityContextTools

    seen = {}

    def fake_search(_run, queries, top_k_per_query=None):
        seen["queries"] = list(queries)
        seen["top_k_per_query"] = top_k_per_query
        return []

    monkeypatch.setattr(
        "impl.core.authority_environment.search_context_units_tool", fake_search
    )
    tools = AuthorityContextTools(authority_env.context_run)
    from typing import get_type_hints
    assert set(get_type_hints(tools.search_context_units)) == {"queries"}
    tools.search_context_units(["a", "b"])
    assert seen == {"queries": ["a", "b"], "top_k_per_query": 3}


def test_authority_prompt_requires_search_then_load_without_parallel_navigation(authority_env):
    prompt = _resolve_system_prompt(authority_env)

    assert "第一轮工具调用只能调用一次 search_context_units" in prompt
    assert "禁止在这一轮并行调用 investigation_search_index" in prompt
    assert "紧接着的一轮只能调用一次 load_context_units" in prompt
    assert "完成第一次原始资料 Load 后" in prompt
    assert "M1/inlive_boundary 只可作为已登记信任模型下的边界代理" in prompt
    assert "不能证明某个具体口语、别名或输入值应当映射到哪个归一值" in prompt
    assert "只有 current_behavior 或inlive_boundary" in prompt
    assert "必须返回 unresolved" in prompt
    assert "M1/inlive_boundary 只可作为已登记信任模型下的边界代理" in prompt
    assert "不能证明某个具体口语、别名或输入值应当映射到哪个归一值" in prompt
    assert "只有 current_behavior 或inlive_boundary" in prompt
    assert "必须返回 unresolved" in prompt


def test_authority_prompt_allows_value_retrieval_via_key_index_after_empty_search(authority_env):
    """CG-ENG-006：Search 无候选时允许用内部对象索引做值级检索，命中后必须 Load。"""
    prompt = _resolve_system_prompt(authority_env)

    assert "Search 未返回任何候选时" in prompt
    assert "下一轮可用 investigation_search_index 做值级/字段级检索" in prompt
    assert "authority.evidence.*" in prompt
    assert "命中后必须紧跟 investigation_load_entry" in prompt
    assert "不得以“候选不决定性”跳过" in prompt
    assert "Load 后仍缺决定性证据时，才可导航内部对象索引精确定位" in prompt
    # 值级检索仍禁止并行导航/扩搜，治理边界不因放开口子而消失。
    assert "禁止在这一轮并行调用 investigation_search_index" in prompt
    assert "不得连续改写同义词搜索" in prompt


def test_authority_prompt_uses_provider_safe_navigation_function_names(authority_env):
    prompt = _resolve_system_prompt(authority_env)

    assert "investigation_search_index" in prompt
    assert "investigation_load_entry" in prompt
    assert "- investigation.search_index：" not in prompt
    assert "- investigation.load_entry：" not in prompt

class SequenceLlm:
    _caller = "authority"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.governance = []

    def complete_json(self, system, user, trace_id=None, output_spec=None, **_kwargs):
        self.calls.append({
            "system": system,
            "user": user,
            "trace_id": trace_id,
            "kwargs": dict(_kwargs),
        })
        self.governance.append(dict(getattr(self, "_context_governance_report", {}) or {}))
        if not self.responses:
            raise AssertionError("unexpected extra complete_json call")
        return dict(self.responses.pop(0))


def test_claim_mode_blind_then_supported(authority_env):
    """担保模式先盲查，再比对；第一阶段输入不得泄漏 claim。"""
    from impl.core.schema import AuthorityClaim

    unit_id = _loaded_unit_id(authority_env)
    llm = SequenceLlm(
        {
            "status": "resolved",
            "statement": "在职有效客户是 orphanType 的合法枚举值。",
            "reason": "枚举资料直接列出该值。",
            "basis_evidence_ref_ids": [unit_id],
            "required_evidence": [],
        },
        {"status": "supported", "reason": "独立结论与待担保断言一致。"},
    )
    claim = AuthorityClaim(
        claim_statement="在职有效客户是 orphanType 的合法枚举值。",
        subject={"kind": "enum_value", "name": "orphanType", "value": "在职有效客户"},
        conclusion_kind="inlive_boundary",
        intended_use="expectation-core-delivery",
    )
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(decision_question="orphanType 是否允许在职有效客户？", claim=claim),
        llm=llm,
    )

    assert resolution.status == "supported"
    assert resolution.independent_resolution is not None
    assert resolution.independent_resolution.status == "resolved"
    assert resolution.basis_evidence_ref_ids == (unit_id,)
    assert len(llm.calls) == 2
    assert "claim" not in llm.calls[0]["user"]
    assert "claim_statement" in llm.calls[1]["user"]
    assert llm.calls[0]["trace_id"] == "authority-resolve"
    assert llm.calls[1]["trace_id"] == "authority-resolve-claim-compare"


def test_claim_mode_governance_preserves_origin_lineage(authority_env):
    from impl.core.schema import AuthorityClaim

    authority_env.trace_id = "judge-trace-1"
    authority_env.case_id = "case-1"
    unit_id = _loaded_unit_id(authority_env)
    llm = SequenceLlm(
        {
            "status": "resolved",
            "statement": "当前值空间包含该值。",
            "reason": "已加载枚举资料。",
            "basis_evidence_ref_ids": [unit_id],
            "required_evidence": [],
        },
        {"status": "supported", "reason": "结论一致。"},
    )
    request = AuthorityRequest(
        decision_question="该值是否在当前值空间？",
        claim=AuthorityClaim(
            claim_statement="该值在当前值空间。",
            subject={"kind": "enum_value", "value": "x"},
            conclusion_kind="inlive_boundary",
            intended_use="judge-assessment",
        ),
    )

    resolve_authority(
        authority_env,
        request,
        llm=llm,
        authority_call_id="authority.call-1",
    )

    assert [call["trace_id"] for call in llm.calls] == ["judge-trace-1", "judge-trace-1"]
    snapshots = [report["snapshot"] for report in llm.governance]
    assert [snapshot["stage"] for snapshot in snapshots] == [
        "independent_resolution",
        "claim_compare",
    ]
    assert all(snapshot["lineage"] == {
        "trace_id": "judge-trace-1",
        "case_id": "case-1",
        "call_id": "authority.call-1",
    } for snapshot in snapshots)


def test_claim_mode_unresolved_classifies_gap_only(authority_env):
    from impl.core.schema import AuthorityClaim

    llm = SequenceLlm(
        {
            "status": "unresolved",
            "statement": "",
            "reason": "已有管辖资料，但缺少渠道生效条件。",
            "basis_evidence_ref_ids": [],
            "required_evidence": ["渠道生效规则"],
        },
        {"status": "gap_only", "reason": "主题受管辖，但缺少决定性渠道条件。"},
    )
    resolution = resolve_authority(
        authority_env,
        AuthorityRequest(
            decision_question="该渠道应采用哪个映射？",
            claim=AuthorityClaim(
                claim_statement="该渠道应映射到 A。",
                subject={"kind": "mapping", "source": "该渠道"},
                conclusion_kind="normative_rule",
                intended_use="expectation-mapping",
            ),
        ),
        llm=llm,
    )

    assert resolution.status == "gap_only"
    assert resolution.statement == ""
    assert resolution.required_evidence == ("渠道生效规则",)
    assert resolution.independent_resolution.status == "unresolved"


def test_claim_mode_rejects_comparison_that_rewrites_independent_result(authority_env):
    """盲查 resolved 后，比对阶段不得伪装成资料缺口。"""
    from impl.core.schema import AuthorityClaim

    unit_id = _loaded_unit_id(authority_env)
    llm = SequenceLlm(
        {
            "status": "resolved",
            "statement": "结论 A",
            "reason": "资料决定 A",
            "basis_evidence_ref_ids": [unit_id],
            "required_evidence": [],
        },
        {"status": "gap_only", "reason": "试图推翻盲查结论"},
    )
    with pytest.raises(ValueError, match="incompatible with independent"):
        resolve_authority(
            authority_env,
            AuthorityRequest(
                decision_question="应采用 A 还是 B？",
                claim=AuthorityClaim(
                    claim_statement="应采用 A",
                    subject="mapping:A-or-B",
                    conclusion_kind="normative_rule",
                    intended_use="expectation-1",
                ),
            ),
            llm=llm,
        )


def test_client_search_field_navigation_budget_preserves_authority_capacity(monkeypatch):
    from impl.projects.client_search import judge as draft_judge
    from impl.tools import ToolResult, VerifiableTool

    executed = []

    def make_tool(tool_id):
        def execute(**kwargs):
            executed.append((tool_id, kwargs))
            return ToolResult(tool_id=tool_id, status="succeeded", actual=kwargs)

        return VerifiableTool(
            tool_id=tool_id,
            description=tool_id,
            parameters={"type": "object", "properties": {}, "required": []},
            execute_fn=execute,
        )

    monkeypatch.setattr(
        draft_judge,
        "_build_field_tools",
        lambda _spec: [
            make_tool("client_search.field.search_keys"),
            make_tool("field.search_definition"),
        ],
    )

    tools = draft_judge._build_judge_tools(object())
    search = next(tool for tool in tools if tool.name == "client_search_field_search_keys")
    load = next(tool for tool in tools if tool.name == "field_search_definition")

    results = [
        search.entrypoint(query="q1"),
        load.entrypoint(field="f1"),
        search.entrypoint(query="q2"),
        load.entrypoint(field="f2"),
        search.entrypoint(query="q3"),
        load.entrypoint(field="f3"),
    ]

    assert len(executed) == draft_judge._FIELD_NAVIGATION_CALL_LIMIT
    assert results[4].status == "inconclusive"
    assert results[4].runtime_metadata["budget_kind"] == "field_navigation"
    assert results[5].status == "inconclusive"
    assert draft_judge._JUDGE_TOOL_CALL_LIMIT > draft_judge._FIELD_NAVIGATION_CALL_LIMIT


def test_client_search_draft_prompt_declares_llm_owned_field_allowlist():
    from pathlib import Path

    source = Path("impl/projects/client_search/judge.py").read_text(encoding="utf-8")
    assert "以本节为唯一准则" in source
    assert "禁止输出 overall_fulfillment、confidence、evidence_refs、authority_analysis_ids、actual" in source
    assert "boundary 必须是 JSON object" in source
    assert "工具参数必须是严格 JSON" in source


def test_authority_internal_budget_can_complete_governance_and_evidence_loads():
    from impl.core import authority_environment

    assert authority_environment.AUTHORITY_INTERNAL_TOOL_CALL_LIMIT >= 6
    prompt = authority_environment._resolve_system_prompt(_FakePromptEnv())
    assert "下一步必须立即 Load" in prompt
    assert "不得连续改写同义词搜索" in prompt


class _FakePromptEnv:
    project_id = "test"
    caller_role = "judge"
    environment_snapshot_sha256 = "snapshot"
    permission_boundary = {}


def test_claim_compare_payload_projects_only_conclusion_fields():
    """CG-ENG-004：claim 比对阶段只注入独立结论本身，不携带证据地址与 required_evidence。"""
    import json
    from types import SimpleNamespace

    from impl.core.authority_environment import _compare_claim
    from impl.core.schema import AuthorityClaim, AuthorityIndependentResolution

    env = SimpleNamespace(
        governance_mode="production",
        trace_id="trace-x",
        case_id="case-x",
        project_id="client_search",
    )
    llm = SequenceLlm({"status": "supported", "reason": "独立结论与待担保断言一致。"})
    independent = AuthorityIndependentResolution(
        status="resolved",
        statement="在职有效客户是 orphanType 的合法枚举值。",
        reason="枚举资料直接列出该值。",
        basis_evidence_ref_ids=("authority-ref-1",),
        required_evidence=("决定性资料",),
    )
    claim = AuthorityClaim(
        claim_statement="在职有效客户是 orphanType 的合法枚举值。",
        subject={"kind": "enum_value", "name": "orphanType", "value": "在职有效客户"},
        conclusion_kind="inlive_boundary",
        intended_use="expectation-core-delivery",
    )

    result = _compare_claim(
        llm,
        AuthorityRequest(decision_question="orphanType 是否允许在职有效客户？", claim=claim),
        independent,
        env=env,
        authority_call_id="call-1",
    )

    assert result.status == "supported"
    assert llm.calls[0]["trace_id"] == "trace-x"
    # CG-ENG-005：比对阶段调用点必须标注自己的 caller，注入同一 client 时
    # 不能把第一阶段的 audit caller 覆盖掉。
    assert llm._caller == "authority-claim-compare"
    user = json.loads(llm.calls[0]["user"])
    view = user["independent_resolution"]
    assert set(view) == {"status", "statement", "reason"}
    assert "basis_evidence_ref_ids" not in view
    assert "required_evidence" not in view
    assert user["claim"]["claim_statement"] == claim.claim_statement
    # 无 context_run 的注入环境不携带 trace 信号；context_coverage 仍必须投影。
    assert user["context_coverage"] == {}
    # CG-ENG-008：比对阶段即使与第一阶段同一 client，也必须在模型边界强制无工具。
    assert llm.calls[0]["kwargs"]["tools_override"] == []


def test_claim_compare_payload_includes_context_coverage_signal():
    """CG-ENG-007：context_coverage 来自 ContextRun 确定性 trace，不是模型自述。"""
    import json
    from types import SimpleNamespace

    from impl.core.authority_environment import _compare_claim
    from impl.core.schema import AuthorityClaim, AuthorityIndependentResolution

    class FakeRun:
        def debug_snapshot(self):
            return {"context_debug": {
                "search_queries": ["orphanType"],
                "candidate_ids": ["authority-ref-a", "authority-ref-b"],
                "loaded_ids": ["authority-ref-a"],
            }}

    env = SimpleNamespace(
        governance_mode="production",
        trace_id="trace-x",
        case_id="case-x",
        project_id="client_search",
        context_run=FakeRun(),
    )
    llm = SequenceLlm({"status": "gap_only", "reason": "已有管辖资料但缺决定性条件。"})
    independent = AuthorityIndependentResolution(
        status="unresolved",
        statement="",
        reason="资料冲突。",
        basis_evidence_ref_ids=("authority-ref-a",),
        required_evidence=("决定性证据",),
    )
    claim = AuthorityClaim(
        claim_statement="该值是合法枚举值。",
        subject={"kind": "enum_value", "name": "orphanType", "value": "x"},
        conclusion_kind="inlive_boundary",
        intended_use="judge-assessment",
    )

    result = _compare_claim(
        llm,
        AuthorityRequest(decision_question="orphanType 是否允许该值？", claim=claim),
        independent,
        env=env,
        authority_call_id="call-1",
    )

    assert result.status == "gap_only"
    user = json.loads(llm.calls[0]["user"])
    assert user["context_coverage"] == {
        "searched": True,
        "candidate_count": 2,
        "loaded_count": 1,
        "has_candidate": True,
        "has_loaded": True,
    }


def test_field_slice_description_stays_summary_without_implementation_details():
    """CG-ENG-006：字段级切片 description 只保留摘要，值级召回交给 key-index。"""
    import tempfile
    from pathlib import Path

    from impl.core.authority_environment import (
        _materialize_sliced_yaml_records,
        _materialize_yaml_mapping_field_records,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "mappings.yaml"
        path.write_text(
            "field_a:\n"
            "  - value: 在职有效客户\n"
            "    alias: 在职\n"
            "field_b:\n"
            "  - 团体\n",
            encoding="utf-8",
        )
        records = _materialize_yaml_mapping_field_records(
            ref_id="ref-mappings",
            resolved=path,
            slice_spec={"mode": "yaml_mapping_field"},
            base_tags={"ref_id": "ref-mappings"},
            project_id="client_search",
            role="judge",
        )

    assert len(records) == 2
    for record in records:
        assert "内容：" not in record.description
        assert "在职有效客户" not in record.description
        assert "authority.evidence" not in record.description
        assert "不再把整字段内容复制" not in record.description
        assert record.content

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "rules.yaml"
        path.write_text(
            "rules:\n"
            "  - field: ayhMemberGradeInfo.ayhqualifiedtime\n"
            "    value: 在职有效客户\n"
            "    operator: IN\n",
            encoding="utf-8",
        )
        field_records = _materialize_sliced_yaml_records(
            ref_id="ref-rules",
            resolved=path,
            slice_spec={
                "mode": "field",
                "list_key": "rules",
                "field_key": "field",
            },
            base_tags={"ref_id": "ref-rules"},
            project_id="client_search",
            role="judge",
        )

    assert len(field_records) == 1
    assert "在职有效客户" not in field_records[0].description
    assert field_records[0].content


def test_field_slice_projects_evidence_locator_index_closed_loop():
    """CG-ENG-006/P4：声明驱动的字段级切片投影 evidence_locator 索引闭环。"""
    import json
    import tempfile
    from pathlib import Path

    from impl.core.authority_environment import (
        _build_evidence_load_target_resolver,
        _materialize_sliced_yaml_records,
        _materialize_yaml_mapping_field_records,
        _project_field_slice_evidence_indexes,
    )
    from impl.core.authority_key_index import build_authority_key_index_registry
    from impl.core.schema.investigation_judge import (
        load_authority_investigation_report,
    )

    declared = {"entry_granularity": "field"}
    with tempfile.TemporaryDirectory() as tmpdir:
        mapping_path = Path(tmpdir) / "mappings.yaml"
        mapping_path.write_text(
            "field_a:\n"
            "  - value: 在职有效客户\n"
            "    alias: 在职\n"
            "field_b:\n"
            "  - 团体人身保险\n",
            encoding="utf-8",
        )
        mapping_records = _materialize_yaml_mapping_field_records(
            ref_id="ref-mappings",
            resolved=mapping_path,
            slice_spec={"mode": "yaml_mapping_field"},
            base_tags={"ref_id": "ref-mappings", "key_index": json.dumps(declared)},
            project_id="client_search",
            role="judge",
        )
        rules_path = Path(tmpdir) / "rules.yaml"
        rules_path.write_text(
            "rules:\n"
            "  - field: ayhMemberGradeInfo.ayhqualifiedtime\n"
            "    value: 在职有效客户\n"
            "    operator: IN\n",
            encoding="utf-8",
        )
        rules_records = _materialize_sliced_yaml_records(
            ref_id="ref-rules",
            resolved=rules_path,
            slice_spec={
                "mode": "field",
                "list_key": "rules",
                "field_key": "field",
            },
            base_tags={"ref_id": "ref-rules", "key_index": json.dumps(declared)},
            project_id="client_search",
            role="judge",
        )
        undeclared_records = _materialize_yaml_mapping_field_records(
            ref_id="ref-undeclared",
            resolved=mapping_path,
            slice_spec={"mode": "yaml_mapping_field"},
            base_tags={"ref_id": "ref-undeclared"},
            project_id="client_search",
            role="judge",
        )
    records = [*mapping_records, *rules_records, *undeclared_records]

    class FakeRun:
        def selection_refs_for_context_units(self, unit_ids):
            return tuple(
                f"C{index}" for index in range(1, len(list(unit_ids)) + 1)
            )

    indexes = _project_field_slice_evidence_indexes(records)
    # 声明驱动的 field / yaml_mapping_field 投影；无声明的 ref 不投影（§14）。
    assert [item.index_key for item in indexes] == [
        "authority.evidence.ref-mappings",
        "authority.evidence.ref-rules",
    ]
    index = indexes[0]
    assert index.collection_ref == "ref-mappings"
    assert index.target_kind == "evidence_locator"
    assert index.entry_granularity == "field"
    keys = [entry.key for entry in index.entries]
    assert keys == ["field_a", "field_b"]
    field_a = index.entries[0]
    assert field_a.name == "Evidence ref-mappings · field_a"
    # search_text 口径：字段名在前 + 值级确定性投影（协议 §12.2）。
    assert field_a.search_text.startswith("field_a")
    assert "在职有效客户" in field_a.search_text
    assert "在职" in field_a.search_text
    assert field_a.target_ref.startswith("evidence-navigation://ref-mappings/")

    rules_index = indexes[1]
    assert rules_index.collection_ref == "ref-rules"
    assert rules_index.entries[0].key == "ayhMemberGradeInfo.ayhqualifiedtime"
    assert "在职有效客户" in rules_index.entries[0].search_text

    report = load_authority_investigation_report(
        Path("impl/projects/client_search/investigation/judge/docs/authority-investigation-report.json")
    )
    registry = build_authority_key_index_registry(
        report,
        indexes=indexes,
        load_target_resolver=_build_evidence_load_target_resolver(
            records, FakeRun()
        ),
    )

    hits, _ = registry.search("authority.evidence.ref-mappings", "在职有效客户")
    assert [hit.key for hit in hits] == ["field_a"]
    assert hits[0].target_ref == field_a.target_ref

    loaded, receipt = registry.load(
        "authority.evidence.ref-mappings", "field_a"
    )
    assert loaded["locator"] == "field_a"
    assert loaded["content"]["navigation_only"] is True
    assert loaded["load_targets"] == ["C1"]
    assert receipt.target_resolution["strategy"] == "field-locator"
    assert receipt.target_resolution["matched_unit_count"] == 1


def test_field_locator_prefers_exact_field_name_over_substring_collision():
    """field-locator 精确优先：'polNo' 不能误配到 'polNoInfo.applicantname'。"""
    import json
    import tempfile
    from pathlib import Path

    from impl.core.authority_environment import (
        _build_evidence_load_target_resolver,
        _materialize_yaml_mapping_field_records,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "enums.yaml"
        path.write_text(
            "polNo:\n"
            "  - 保单号\n"
            "polNoInfo.applicantname:\n"
            "  - 投保人姓名\n"
            "polNoInfo.polStatus:\n"
            "  - 保单状态\n",
            encoding="utf-8",
        )
        records = _materialize_yaml_mapping_field_records(
            ref_id="ref-enums",
            resolved=path,
            slice_spec={"mode": "yaml_mapping_field"},
            base_tags={"ref_id": "ref-enums", "key_index": json.dumps({"entry_granularity": "field"})},
            project_id="client_search",
            role="judge",
        )

    class FakeRun:
        def selection_refs_for_context_units(self, unit_ids):
            return tuple(
                f"C{index}" for index in range(1, len(list(unit_ids)) + 1)
            )

    resolver = _build_evidence_load_target_resolver(records, FakeRun())
    # 精确字段名解析到自身切片，而不是被更短字段名的子串污染。
    exact = resolver("ref-enums", "polNoInfo.applicantname")
    assert exact["status"] == "resolved"
    assert exact["strategy"] == "field-locator"
    assert exact["matched_unit_count"] == 1
    short = resolver("ref-enums", "polNo")
    assert short["status"] == "resolved"
    assert short["matched_unit_count"] == 1


def test_authority_tool_protocol_violation_maps_to_unresolved_with_missing_evidence(authority_env):
    """authority-minimal-chain.md §8：模型未完成查证（导航违例）不得落 tool_failure。

    归一为 unresolved（依据不充分）并带缺料清单，使 fulfilled.md §10 依据链可审计；
    端点瞬时故障仍走 tool_failure fail-closed。
    """
    from impl.core.authority_tool import build_authority_resolve_tool
    from impl.core.schema import AuthorityResolution

    class ViolationLlm:
        _caller = "authority"
        def complete_json(self, system, user, trace_id=None, output_spec=None, **_kwargs):
            # 触发 _validate_authority_tool_sequence：search 返回候选但未 Load 就终止。
            return {
                "status": "unresolved",
                "reason": "r",
                "tool_call_log": [
                    {
                        "tool_name": "search_context_units",
                        "result": '{"candidates":[{"selection_ref":"C1","context_unit_ids":["u1"]}]}',
                    }
                ],
            }

    tool = build_authority_resolve_tool(authority_env, llm=ViolationLlm())
    result = tool._execute(
        "客户搜索是否支持按公司名称查询？",
        question_class="responsibility",
    )
    assert result["status"] == "unresolved"
    assert result["required_evidence"]
    call_id = result["tool_call_id"]
    entry = tool.audit[call_id]
    assert not entry.get("tool_failure")
    assert isinstance(entry["resolution"], AuthorityResolution)
    assert entry["resolution"].status == "unresolved"
    assert entry["resolution"].required_evidence


def test_authority_tool_budget_exceeded_claim_maps_to_gap_only(authority_env):
    """工具预算耗尽属确定性查证失败 → claim 模式归一 gap_only（依据不充分）+ 缺料清单。"""
    from impl.core.authority_tool import build_authority_resolve_tool

    class BudgetLlm:
        _caller = "authority"
        def complete_json(self, system, user, trace_id=None, output_spec=None, **_kwargs):
            return {"error": "tool_budget_exceeded", "raw_text": "actual 8 calls, limit 8"}

    tool = build_authority_resolve_tool(authority_env, llm=BudgetLlm())
    result = tool._execute(
        "客户搜索是否支持按业务员维度筛选？",
        question_class="responsibility",
        claim={
            "claim_statement": "支持按业务员维度筛选客户。",
            "subject": "salesperson",
            "conclusion_kind": "inlive_boundary",
            "intended_use": "判断职责内能力",
        },
    )
    assert result["status"] == "gap_only"
    assert result["required_evidence"]
    entry = tool.audit[result["tool_call_id"]]
    assert not entry.get("tool_failure")
    assert entry["resolution"].status == "gap_only"


def test_authority_tool_transient_failure_stays_tool_failure(authority_env):
    """端点/瞬时故障（此处模拟 5xx）必须保持 tool_failure fail-closed，不归一成 unresolved。"""
    from impl.core.authority_tool import build_authority_resolve_tool

    class TransientLlm:
        _caller = "authority"
        def complete_json(self, system, user, trace_id=None, output_spec=None, **_kwargs):
            raise RuntimeError("502 Bad Gateway: upstream outage")

    tool = build_authority_resolve_tool(authority_env, llm=TransientLlm())
    result = tool._execute("某定义是否可确定？", question_class="semantic_mapping")
    assert result["status"] == "tool_failure"
    entry = tool.audit[result["tool_call_id"]]
    assert entry["tool_failure"] is True
    assert not result["required_evidence"]
