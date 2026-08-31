"""Authority Agent 运行时环境（Core 私有）与 resolve 入口。

对应 spec/alg/authority.md §4.2 宿主无关 Ports 的 verifier Adapter：

- EvidenceSpace     ：ContextRuntime/ContextRun（search / load / ref 校验 / hash）
- Materializer      ：manifest evidence_refs 物化为 ContextUnitRecord（§13.3）
- ToolGateway       ：授权 VerifiableTool（Agno 化），结果可回填物化
- PermissionBoundary：ProjectSpec + Role + Draft/Production 资产选择 + 预算
- EnvironmentSnapshot：environment_snapshot_sha256（项目/Role/资料 revision/工具指纹）

公共协议只暴露 AuthorityRequest 与 AuthorityResolution（impl.core.schema.authority）；
本模块的 AuthorityEnvironment 是 Core 私有组合对象，主 LLM 不能选择或扩大。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from typing import Annotated

from pydantic import Field

from impl.core.context.errors import ContextValidationError
from impl.core.context.runtime import ContextRun, ContextRuntime
from impl.core.context.bootstrap import DEFAULT_CONTEXT_DATA_ROOT, build_context_runtime
from impl.core.context.resolvers import CompositeContentResolver, standard_content_resolver
from impl.core.context.tools import (
    GuardedContextTools,
    load_context_units_tool,
    search_context_units_tool,
)
from impl.core.project_loader import (
    resolve_project_package_root,
    resolve_project_source_root,
    resolve_role_assets,
)
from impl.core.schema import (
    AuthorityIndependentResolution,
    AuthorityRequest,
    AuthorityResolution,
)
from impl.core.authority_key_index import (
    MATERIAL_DECISION_INDEX_KEY,
    create_authority_navigation_tools,
)
from impl.core.schema.investigation_judge import load_authority_investigation_report
from impl.core.schema import to_dict
from impl.core.schema.investigation import (
    SLICE_MODE_FIELD,
    SLICE_MODE_YAML_LIST_CHUNK,
    SLICE_MODE_YAML_MAPPING_FIELD,
    load_investigation_manifest,
)
from impl.core.schema.investigation_key_index import (
    InvestigationKeyEntry,
    InvestigationKeyIndex,
)
from impl.core.context.models import ContextUnitRecord
from impl.tools import ToolResult, VerifiableTool
from impl.tools.protocol import runtime_tool_name
from impl.tools import build_agno_tools

logger = logging.getLogger(__name__)

# 导航允许批量 investigation_search_index 后（校验已放宽为"结束前消费候选"），
# 一次 resolve 的合法调用序列最长约 7-8 次：search_context_units + load_context_units
# + 批量 search_index(≤3) + load_entry + 材料 load_context_units + 缺料复核。
# 8 仍是硬性成本上限，防 agentic 失控；过小只会把合法导航逼成预算耗尽。
AUTHORITY_INTERNAL_TOOL_CALL_LIMIT = 8

AUTHORITY_RUNTIME_PROTOCOL_VERSION = 2


class AuthorityEnvironmentInvalid(RuntimeError):
    """The bound evidence space cannot safely support an Authority call."""

    def __init__(self, errors: Sequence[Mapping[str, Any]]):
        self.errors = tuple(dict(item) for item in errors)
        super().__init__(
            "Authority Environment evidence registration failed: "
            + json.dumps(self.errors, ensure_ascii=False, sort_keys=True)
        )


class AuthorityToolProtocolViolation(RuntimeError):
    """The Authority model violated the runtime-owned evidence navigation order."""


def _tool_result_contains_key(value: Any, key: str) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return False
    if isinstance(value, Mapping):
        if key in value and value.get(key) not in (None, "", [], {}):
            return True
        return any(_tool_result_contains_key(item, key) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_tool_result_contains_key(item, key) for item in value)
    return False


def _validate_authority_tool_sequence(tool_calls: Sequence[Mapping[str, Any]]) -> None:
    """Enforce the Search→Load disciplines that cannot safely live in prose alone.

    Disciplines:
    - the first Authority tool call must load context units (search_context_units);
    - search_context_units candidates must be immediately loaded;
    - key-index navigation may batch several investigation_search_index, but all
      searches must be consumed by investigation_load_entry before the session
      ends (no dangling candidates);
    - a non-navigation investigation_load_entry returning load_targets must be
      followed by load_context_units; navigation-only entries carry self-contained
      decision/gap content and may legitimately terminate the session.
    """
    calls = [dict(item) for item in tool_calls]
    if not calls:
        return

    names = [str(item.get("tool_name") or "") for item in calls]
    if not names[0].endswith("search_context_units"):
        raise AuthorityToolProtocolViolation(
            "the first Authority tool call must be search_context_units"
        )

    for index, call in enumerate(calls[:-1]):
        name = names[index]
        next_name = names[index + 1]
        if (
            name.endswith("search_context_units")
            and _tool_result_contains_key(call.get("result"), "selection_ref")
            and not next_name.endswith("load_context_units")
        ):
            raise AuthorityToolProtocolViolation(
                "search_context_units returned candidates but was not immediately followed "
                "by load_context_units"
            )
        if (
            name.endswith("investigation_load_entry")
            and _tool_result_contains_key(call.get("result"), "load_targets")
            and not next_name.endswith("load_context_units")
            and not _tool_result_contains_key(call.get("result"), "navigation_only")
        ):
            raise AuthorityToolProtocolViolation(
                "investigation_load_entry returned load_targets but was not immediately "
                "followed by load_context_units without terminal self-contained content"
            )

    final = calls[-1]
    if (
        names[-1].endswith("search_context_units")
        and _tool_result_contains_key(final.get("result"), "selection_ref")
    ):
        raise AuthorityToolProtocolViolation(
            "Authority stopped after Search candidates without loading evidence"
        )
    if (
        names[-1].endswith("investigation_load_entry")
        and _tool_result_contains_key(final.get("result"), "load_targets")
        and not _tool_result_contains_key(final.get("result"), "navigation_only")
    ):
        raise AuthorityToolProtocolViolation(
            "Authority stopped after navigation load_targets without loading evidence"
        )
    outstanding_index_candidates = False
    for call in calls:
        name = str(call.get("tool_name") or "")
        result = call.get("result")
        if name.endswith("investigation_search_index") and _tool_result_contains_key(result, "target_ref"):
            outstanding_index_candidates = True
        elif name.endswith("investigation_load_entry"):
            outstanding_index_candidates = False
    if outstanding_index_candidates:
        raise AuthorityToolProtocolViolation(
            "Authority stopped after key-index candidates without loading evidence"
        )


# 静态资料物化为 project_static；动态 ToolResult 由调用方按 case-scoped 物化。
SCOPE_PROJECT_STATIC = "project_static"
SCOPE_CASE = "case"


@dataclass
class AuthorityEnvironment:
    """Core 私有的运行时组合对象（不属于公共协议）。

    公共协议只暴露 AuthorityRequest / AuthorityResolution；Environment 由代码
    确定性构造，主 LLM 不能选择或扩大该空间。
    """

    project_id: str
    caller_role: str
    trace_id: str
    case_id: str
    governance_mode: str
    context_run: ContextRun
    context_runtime: ContextRuntime
    # Core 私有：用于构造 resolve 的 LLM client，不参与 snapshot 序列化。
    spec: Any = None
    # ToolGateway：授权 VerifiableTool（已 Agno 化）。结果自动回填物化。
    gateway_tools: list[Any] = field(default_factory=list)
    # Navigation tools：只缩小资料候选，不物化为证据，也不能直接作为 basis。
    navigation_tools: list[Any] = field(default_factory=list)
    # PermissionBoundary：当前上下文可见范围与预算。
    permission_boundary: dict[str, Any] = field(default_factory=dict)
    environment_snapshot_sha256: str = ""
    registration_errors: list[dict[str, str]] = field(default_factory=list)
    staleness_warnings: list[dict[str, str]] = field(default_factory=list)

    def ref_loaded_unchanged(self, unit_id: str) -> bool:
        """EvidenceSpace.ref 校验：已实际 Load 过、能回到 registry 且内容 hash 未变。

        authority.md §12.1：一个 ContextUnit 只有被实际 Load 后才可进入
        basis_evidence_ref_ids；hash 变化表示资料已修订，旧结论不可复用。
        """
        entry = self.context_runtime.registry.get(unit_id)
        if entry is None:
            return False
        loaded_hash = self.context_run.content_hash_for_loaded_unit(unit_id)
        if loaded_hash is None:
            return False
        return loaded_hash == str(entry.get("source_hash") or "")


def _sha256(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_declared_source_hash(
    ref_id: str,
    path: Path,
    declared: str,
    *,
    business_source_staleness_policy: str = "strict",
    staleness_warnings: list[dict[str, str]] | None = None,
) -> str:
    """Return the actual file hash; fail closed on drift under strict policy.

    Under ``warn`` (Draft candidate runtime) drift is recorded as an
    informational staleness warning instead of failing the environment
    construction. Structural failures (missing files, path escapes) still
    fail closed in every policy.
    """
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = str(declared or "").strip()
    if expected and actual != expected:
        if business_source_staleness_policy == "warn":
            warning = {
                "ref_id": str(ref_id),
                "stage": "source_hash_validation",
                "expected_sha256": expected,
                "actual_sha256": actual,
                "reason": "EvidenceRef content hash changed (warn policy)",
                "routing": "drift_recorded",
            }
            if staleness_warnings is not None:
                staleness_warnings.append(warning)
            return actual
        raise AuthorityEnvironmentInvalid([{
            "ref_id": str(ref_id),
            "stage": "source_hash_validation",
            "expected_sha256": expected,
            "actual_sha256": actual,
            "reason": "EvidenceRef content hash changed",
        }])
    return actual


def _registered_context_fingerprints(
    runtime: ContextRuntime,
    records: Iterable[ContextUnitRecord],
) -> list[dict[str, str]]:
    """Describe semantic registered content, excluding mutable registration actions."""

    fingerprints: list[dict[str, str]] = []
    for record in records:
        entry = runtime.registry.get(record.id)
        if entry is None:
            raise AuthorityEnvironmentInvalid([{
                "ref_id": str(record.tags.get("ref_id") or record.id),
                "stage": "registry_lookup",
                "reason": f"registered ContextUnit is missing: {record.id}",
            }])
        fingerprints.append({
            "context_unit_id": str(record.id),
            "ref_id": str(record.tags.get("ref_id") or ""),
            "source_hash": str(entry.get("source_hash") or ""),
        })
    return sorted(fingerprints, key=lambda item: item["context_unit_id"])


def _content_resolver(spec: Any) -> CompositeContentResolver:
    roots: list[Path] = []
    project_root = resolve_project_package_root(spec, must_exist=False)
    if project_root.exists():
        roots.append(project_root)
    if spec.has_business_source:
        source_root = resolve_project_source_root(spec)
        if source_root not in roots:
            roots.append(source_root)
    return standard_content_resolver(roots)


def _build_context_runtime(
    spec: Any,
    *,
    role: str,
    use_candidate: bool,
    embedding_provider: Any = None,
    trace_id: str = "",
    case_id: str = "",
) -> tuple[ContextRuntime, ContextRun]:
    from impl.core.config import get_runtime_config
    from impl.core.context.embedding import BailianEmbeddingProvider

    runtime_config = get_runtime_config()
    if not runtime_config.embedding.enabled:
        raise RuntimeError(
            "Authority Environment requires embedding.enabled=true before ContextUnit initialization"
        )
    runtime_config.require("embedding")
    context_config = dict(spec.verifier_extra_value("context", {}) or {})
    project_policy = (
        context_config.get("policy")
        if isinstance(context_config.get("policy"), Mapping)
        else None
    )
    ctx_limits = runtime_config.context
    # Candidate investigation ContextUnits must never remain searchable by
    # Production after a Draft run.  Keep mode databases isolated.
    data_root = DEFAULT_CONTEXT_DATA_ROOT / (
        "authority-draft" if use_candidate else "authority-production"
    )
    runtime = build_context_runtime(
        project_id=spec.project_id,
        data_root=data_root,
        project_root=resolve_project_package_root(spec, must_exist=False),
        embedding_provider=embedding_provider or BailianEmbeddingProvider(),
        content_resolver=_content_resolver(spec),
        public_policy={
            "default": {
                "enabled": True,
                "allowed_roles": [role],
                "allowed_statuses": ["active"],
                "candidate_limit": ctx_limits.candidate_limit,
                "load_limit": ctx_limits.load_limit,
                "content_char_budget": ctx_limits.content_char_budget,
                "query_limit": ctx_limits.query_limit,
                "top_k_per_query": ctx_limits.top_k_per_query,
            }
        },
        project_policy=project_policy,
    )
    run_args = {
        "role": role,
        "operation": "authority",
        "trace_id": str(trace_id or ""),
        "case_id": str(case_id or ""),
    }
    run = runtime.start_run(run_id="authority-env", **run_args)
    return runtime, run
def _materialize_sliced_yaml_records(
    *,
    ref_id: str,
    resolved: Path,
    slice_spec: Mapping[str, Any],
    base_tags: Mapping[str, str],
    project_id: str,
    role: str,
) -> list[ContextUnitRecord]:
    """把声明了 slice 的大 YAML 按字段切片物化为多个可寻址单元（EvidenceSpace）。

    slice_spec 由 investigation manifest 的 EvidenceRef.metadata.slice 声明
    （适配层数据），切片机制本身宿主无关：
      - mode: "field"（按字段切片）
      - list_key: 文档内待切片的列表键（如 intents / rules）
      - field_key: 列表元素中标识字段的键（如 field）
      - carry: 每个切片需一并携带的公共键（如 pattern_vars），保证切片自解释
    每个字段一个 ContextUnitRecord（content 内联，content_ref 为空），tags 保留
    ref_id / 源文件 sha256 / field / slice=field，可溯源且可被 search 召回。
    """
    import yaml

    mode = str(slice_spec.get("mode") or "")
    if mode != SLICE_MODE_FIELD:
        raise ValueError(f"unsupported EvidenceRef slice mode {mode!r}: {ref_id}")
    list_key = str(slice_spec.get("list_key") or "").strip()
    field_key = str(slice_spec.get("field_key") or "").strip()
    if not list_key or not field_key:
        raise ValueError(f"EvidenceRef slice spec requires list_key and field_key: {ref_id}")
    carry = [str(key) for key in (slice_spec.get("carry") or []) if str(key).strip()]
    try:
        with resolved.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"EvidenceRef slice YAML parse failed (fail-closed): {ref_id} -> {resolved}: {exc}"
        ) from exc
    if not isinstance(document, dict) or list_key not in document:
        raise ValueError(f"EvidenceRef slice document lacks list key {list_key!r}: {ref_id}")
    items = document[list_key]
    if not isinstance(items, list):
        raise ValueError(f"EvidenceRef slice list key {list_key!r} is not a list: {ref_id}")
    fields: dict[str, list[Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not str(item.get(field_key) or "").strip():
            raise ValueError(f"EvidenceRef slice item lacks field key {field_key!r}: {ref_id}")
        fields.setdefault(str(item[field_key]).strip(), []).append(item)

    records: list[ContextUnitRecord] = []
    for field_name in sorted(fields):
        group = fields[field_name]
        slice_doc: dict[str, Any] = {list_key: group}
        for key in carry:
            if key in document:
                slice_doc[key] = document[key]
        content = json.dumps(slice_doc, ensure_ascii=False, sort_keys=True, default=str)
        unit_id = "authority-ref-" + hashlib.sha256(
            f"{ref_id}:{resolved}:field:{field_name}".encode("utf-8")
        ).hexdigest()[:16]
        operators = sorted({
            str(item.get("operator") or "")
            for item in group
            if str(item.get("operator") or "").strip()
        })
        ops_text = f"，操作符：{'/'.join(operators)}" if operators else ""
        tags = dict(base_tags)
        tags.update({"field": field_name, "slice": "field"})
        records.append(ContextUnitRecord(
            id=unit_id,
            name=f"Evidence {ref_id} · {field_name}",
            description=(
                f"Evidence {ref_id} 按字段切片：{field_name}"
                f"（{len(group)} 条 {list_key}{ops_text}）。来源文件：{resolved.name}"
            ),
            content=content,
            content_ref=None,
            project_id=project_id,
            scope=SCOPE_PROJECT_STATIC,
            roles=(role,),
            unit_type="evidence_ref",
            source_type="investigation_manifest",
            tags=tags,
        ))
    return records


def _materialize_yaml_mapping_field_records(
    *,
    ref_id: str,
    resolved: Path,
    slice_spec: Mapping[str, Any],
    base_tags: Mapping[str, str],
    project_id: str,
    role: str,
) -> list[ContextUnitRecord]:
    """把顶层 ``field -> definition`` YAML 映射按字段切片。

    适用于枚举、映射等没有统一 list_key 的配置。切片规则由调查 manifest 显式
    声明；每个顶层键物化为独立 Evidence unit，使 Authority 可用一次 Search→Load
    精确取得目标字段，而不是加载整份大文件或依赖摘要猜测。
    """
    import yaml

    mode = str(slice_spec.get("mode") or "")
    if mode != SLICE_MODE_YAML_MAPPING_FIELD:
        raise ValueError(f"unsupported EvidenceRef slice mode {mode!r}: {ref_id}")
    try:
        with resolved.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"EvidenceRef slice YAML parse failed (fail-closed): {ref_id} -> {resolved}: {exc}"
        ) from exc
    if not isinstance(document, dict) or not document:
        raise ValueError(f"EvidenceRef yaml_mapping_field requires a non-empty mapping: {ref_id}")

    records: list[ContextUnitRecord] = []
    for field_name, definition in sorted(document.items(), key=lambda item: str(item[0])):
        field_name = str(field_name).strip()
        if not field_name:
            raise ValueError(f"EvidenceRef yaml_mapping_field contains an empty key: {ref_id}")
        content = json.dumps(
            {field_name: definition}, ensure_ascii=False, sort_keys=True, default=str
        )
        unit_id = "authority-ref-" + hashlib.sha256(
            f"{ref_id}:{resolved}:yaml_mapping_field:{field_name}".encode("utf-8")
        ).hexdigest()[:16]
        tags = dict(base_tags)
        tags.update({"field": field_name, "slice": SLICE_MODE_YAML_MAPPING_FIELD})
        records.append(ContextUnitRecord(
            id=unit_id,
            name=f"Evidence {ref_id} · {field_name}",
            description=(
                f"Evidence {ref_id} 的字段映射切片：{field_name}。"
                f"来源文件：{resolved.name}。"
            ),
            content=content,
            content_ref=None,
            project_id=project_id,
            scope=SCOPE_PROJECT_STATIC,
            roles=(role,),
            unit_type="evidence_ref",
            source_type="investigation_manifest",
            tags=tags,
        ))
    return records


def _materialize_chunked_yaml_list_records(
    *,
    ref_id: str,
    resolved: Path,
    slice_spec: Mapping[str, Any],
    base_tags: Mapping[str, str],
    project_id: str,
    role: str,
) -> list[ContextUnitRecord]:
    """把超大 YAML 标量列表切成可检索、可独立 Load 的证据单元。

    大枚举文件常见形态为 ``<root_key>: {<list_key>: [...]}``。整文件注册会让
    单个 ContextUnit 超过运行时 content budget，Authority 即使只 Load 一个候选
    也必然失败。这里由 Investigation manifest 显式声明切片方式；每块的描述包含
    本块完整标量值，使 exact-name 查询能召回包含该值的块，完整内容仍保留来源
    sha256 与 chunk 地址，不做截断或摘要替代。
    """
    import yaml

    mode = str(slice_spec.get("mode") or "")
    if mode != SLICE_MODE_YAML_LIST_CHUNK:
        raise ValueError(f"unsupported EvidenceRef slice mode {mode!r}: {ref_id}")
    root_key = str(slice_spec.get("root_key") or "").strip()
    list_key = str(slice_spec.get("list_key") or "").strip()
    try:
        chunk_size = int(slice_spec.get("chunk_size") or 256)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"EvidenceRef slice chunk_size must be an integer: {ref_id}") from exc
    if not root_key or not list_key:
        raise ValueError(
            f"EvidenceRef yaml_list_chunk requires root_key and list_key: {ref_id}"
        )
    if chunk_size < 1 or chunk_size > 1000:
        raise ValueError(
            f"EvidenceRef slice chunk_size must be between 1 and 1000: {ref_id}"
        )
    try:
        with resolved.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"EvidenceRef slice YAML parse failed (fail-closed): {ref_id} -> {resolved}: {exc}"
        ) from exc
    if not isinstance(document, dict) or not isinstance(document.get(root_key), dict):
        raise ValueError(f"EvidenceRef slice document lacks mapping root {root_key!r}: {ref_id}")
    values = document[root_key].get(list_key)
    if not isinstance(values, list):
        raise ValueError(
            f"EvidenceRef slice root {root_key!r} lacks list key {list_key!r}: {ref_id}"
        )
    if any(isinstance(item, (dict, list)) for item in values):
        raise ValueError(f"EvidenceRef yaml_list_chunk only accepts scalar values: {ref_id}")

    records: list[ContextUnitRecord] = []
    total_chunks = max(1, (len(values) + chunk_size - 1) // chunk_size)
    for chunk_index, offset in enumerate(range(0, len(values), chunk_size), start=1):
        chunk = values[offset : offset + chunk_size]
        content = json.dumps(
            {root_key: {list_key: chunk}},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        unit_id = "authority-ref-" + hashlib.sha256(
            f"{ref_id}:{resolved}:yaml_list_chunk:{chunk_index}".encode("utf-8")
        ).hexdigest()[:16]
        searchable_values = "、".join(str(item) for item in chunk)
        tags = dict(base_tags)
        tags.update({
            "root_key": root_key,
            "list_key": list_key,
            "slice": SLICE_MODE_YAML_LIST_CHUNK,
            "chunk": str(chunk_index),
            "slice_start": str(offset),
            "slice_end": str(offset + len(chunk) - 1),
        })
        records.append(ContextUnitRecord(
            id=unit_id,
            name=f"Evidence {ref_id} · {root_key} · {chunk_index}/{total_chunks}",
            description=(
                f"Evidence {ref_id} 的 {root_key}.{list_key} 枚举块 "
                f"{chunk_index}/{total_chunks}（{len(chunk)} 项）：{searchable_values}"
            ),
            content=content,
            content_ref=None,
            project_id=project_id,
            scope=SCOPE_PROJECT_STATIC,
            roles=(role,),
            unit_type="evidence_ref",
            source_type="investigation_manifest",
            tags=tags,
        ))
    return records


def _materialize_manifest_evidence_refs(
    spec: Any,
    runtime: ContextRuntime,
    *,
    role: str,
    use_candidate: bool,
    business_source_staleness_policy: str = "strict",
) -> tuple[list[ContextUnitRecord], list[dict[str, str]], list[dict[str, str]]]:
    """把 investigation manifest 的 evidence_refs 物化为 ContextUnitRecord（§13.3）。

    - unit_id 由代码生成，稳定可复现；
    - content_ref 指向原始文件（content 由 ContentResolver 惰性解析）；
    - ref_id 存 tags 作来源别名，不直接作为运行时引用；
    - 已有 EvidenceRef 找不到原始来源 → fail-closed（raise），不进业务层。
    """
    selected = [
        item
        for item in resolve_role_assets(spec, role, use_candidate=use_candidate)
        if item["mapping"].kind == "investigation"
    ]
    if len(selected) != 1:
        return [], [], []
    pkg_path = Path(selected[0]["path"])
    manifest_path = pkg_path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Authority Environment requires investigation manifest: {manifest_path}"
        )
    manifest = load_investigation_manifest(manifest_path)
    records: list[ContextUnitRecord] = []
    errors: list[dict[str, str]] = []
    staleness_warnings: list[dict[str, str]] = []
    project_root = resolve_project_package_root(spec, must_exist=False)
    for ref in manifest.evidence_refs:
        ref_id = str(ref.ref_id or "").strip()
        location_ref = ref.location_ref
        if location_ref is None:
            errors.append({
                "ref_id": ref_id,
                "stage": "missing_location_ref",
                "reason": "EvidenceRef has no location_ref",
            })
            continue
        location = str(location_ref.location or "").strip()
        scope = location_ref.location_scope
        scope_value = getattr(scope, "value", None) or str(scope or "")
        if not location:
            errors.append({"ref_id": ref_id, "stage": "empty_location", "reason": "empty location"})
            continue
        # project_package 相对项目根；artifact_package 相对调查资产目录；
        # business_source 相对业务源根。
        if scope_value == "project_package":
            candidate = project_root / location
        elif scope_value == "artifact_package":
            candidate = pkg_path / location
        elif scope_value == "business_source":
            candidate = resolve_project_source_root(spec) / location
        else:
            errors.append({
                "ref_id": ref_id,
                "stage": "unsupported_scope",
                "reason": f"unsupported location_scope: {scope_value}",
            })
            continue
        resolved = candidate.expanduser().resolve()
        if not resolved.is_file():
            # fail-closed：找不到原始来源 → Environment 构造失败
            raise FileNotFoundError(
                f"Authority EvidenceRef source not found (fail-closed): {ref_id} -> {resolved}"
            )
        actual_sha256 = _validate_declared_source_hash(
            ref_id,
            resolved,
            str(location_ref.sha256 or ""),
            business_source_staleness_policy=business_source_staleness_policy,
            staleness_warnings=staleness_warnings,
        )
        revision = str(location_ref.revision or "") if location_ref.revision else ""
        tags = {
            "ref_id": ref_id,
            "source": str(ref.source or ""),
            "kind": str(ref.kind or ""),
            "stage": str(ref.stage or ""),
        }
        if revision:
            tags["revision"] = revision
        if location_ref.sha256:
            # Under warn drift the unit carries the hash actually loaded so the
            # runtime identity is honest about what content is in scope.
            tags["sha256"] = actual_sha256
        if isinstance(ref.metadata, Mapping) and ref.metadata.get("key_index"):
            # 调查层声明：该切片资料需要值级 key-index（字段枚举来自业务源，
            # 运行时才知道最新字段，因此索引由运行时从已物化内容确定性投影）。
            tags["key_index"] = json.dumps(
                ref.metadata["key_index"], ensure_ascii=False, sort_keys=True
            )
        slice_spec = ref.metadata.get("slice") if isinstance(ref.metadata, Mapping) else None
        if slice_spec:
            # 大文件声明切片时不再注册整文件单元（整文件会超出 Load 预算且无法引用），
            # 只物化为字段级可寻址切片。
            try:
                mode = str(slice_spec.get("mode") or "")
                materializer = (
                    _materialize_sliced_yaml_records
                    if mode == SLICE_MODE_FIELD
                    else _materialize_yaml_mapping_field_records
                    if mode == SLICE_MODE_YAML_MAPPING_FIELD
                    else _materialize_chunked_yaml_list_records
                    if mode == SLICE_MODE_YAML_LIST_CHUNK
                    else None
                )
                if materializer is None:
                    raise ValueError(f"unsupported EvidenceRef slice mode {mode!r}: {ref_id}")
                records.extend(materializer(
                    ref_id=ref_id,
                    resolved=resolved,
                    slice_spec=slice_spec,
                    base_tags=tags,
                    project_id=spec.project_id,
                    role=role,
                ))
            except Exception as exc:  # noqa: BLE001
                errors.append({
                    "ref_id": ref_id,
                    "stage": "slice_materialization",
                    "reason": str(exc),
                })
            continue
        unit_id = "authority-ref-" + hashlib.sha256(
            f"{ref_id}:{resolved}".encode("utf-8")
        ).hexdigest()[:16]
        try:
            records.append(ContextUnitRecord(
                id=unit_id,
                name=f"Evidence {ref_id}",
                description=str(ref.summary or ref_id),
                content=None,
                content_ref=resolved.as_uri(),
                project_id=spec.project_id,
                scope=SCOPE_PROJECT_STATIC,
                roles=(role,),
                unit_type="evidence_ref",
                source_type="investigation_manifest",
                tags=tags,
            ))
        except ContextValidationError as exc:
            errors.append({"ref_id": ref_id, "stage": "context_unit_validation", "reason": str(exc)})
    if staleness_warnings:
        logger.warning(
            "[authority_environment] business-source drift recorded under warn policy: %s",
            "; ".join(
                f"{item.get('ref_id')}({item.get('expected_sha256', '')[:12]}->"
                f"{item.get('actual_sha256', '')[:12]})"
                for item in staleness_warnings
            ),
        )
    return records, errors, staleness_warnings


def _invalidate_stale_evidence_refs(
    runtime: ContextRuntime,
    project_id: str,
    role: str,
    *,
    active_ids: set[str],
) -> list[str]:
    """把已登记过、但不再属于当前证据空间的单元置 inactive。

    authority 证据空间（authority.md §4.2）= 当前 manifest 物化单元 + 本次
    Tool 物化结果。构建时本次 Tool 结果尚未登记，因此凡不在当前 manifest
    单元集合内、且属于证据空间来源（manifest evidence_ref / role_asset /
    历史 runtime_tool）的 active 单元都确定性置为 inactive：manifest 重命名/
    移除 ref 后的旧单元、旧代码注册的 role assets、旧 case 的工具结果都不会
    残留进当前 authority 搜索空间。
    """
    invalidated: list[str] = []
    for entry in runtime.registry.list_entries(project_id):
        record = entry.get("record")
        if record is None:
            continue
        if record.id in active_ids:
            continue
        if (
            record.source_type
            not in {"investigation_manifest", "role_asset", "runtime_tool"}
            or tuple(record.roles) != (role,)
        ):
            continue
        try:
            runtime.invalidate_context_unit(record.id, status="inactive")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[authority_environment] stale evidence-space unit invalidation failed %s: %s",
                record.id,
                exc,
            )
            continue
        invalidated.append(record.id)
    if invalidated:
        logger.info(
            "[authority_environment] invalidated %d stale evidence-space units",
            len(invalidated),
        )
    return invalidated


_LIST_RANGE_LOCATOR = re.compile(
    r"(?P<path>[A-Za-z0-9_.-]+)\[(?P<start>\d+):(?P<end>\d+)\]"
)
_MAX_RESOLVED_LOAD_TARGETS = 8


def _project_field_slice_value_text(value: Any) -> str:
    """把字段切片内容确定性投影为可检索纯文本（叶子标量串联）。

    与 planfullname chunk 索引的 search_text 同构：只保留值级检索投影，
    不保留 JSON 结构、键名或格式噪音，使值名/别名的查询能命中对应切片。
    """
    parts: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for sub in item.values():
                visit(sub)
        elif isinstance(item, (list, tuple)):
            for sub in item:
                visit(sub)
        elif item is None:
            return
        else:
            text = str(item).strip()
            if text:
                parts.append(text)

    visit(value)
    return " ".join(parts)


def _project_field_slice_evidence_indexes(
    records: Sequence[ContextUnitRecord],
) -> list[InvestigationKeyIndex]:
    """从已物化字段级切片投影 evidence_locator key-index（§8.3，声明驱动）。

    CG-ENG-006：mapping 切片把整字段内容塞进 description 换取值级召回，导致每次
    Search 的候选元数据上下文膨胀。修复：值级检索由 key-index 的 search_text
    （确定性投影，不进入模型上下文）承担，description 只保留摘要。

    触发条件由调查层显式声明（EvidenceRef.metadata.key_index）：字段枚举来自业务
    源，运行时才知道最新字段，因此索引在运行时从已物化切片确定性投影，而不是
    写死进 manifest；没有声明的 ref 不投影（§14：Index 策略是调查项，core 不做
    隐式决策）。field / yaml_mapping_field 两种字段级切片共用同一投影。
    """
    from urllib.parse import quote

    grouped: dict[str, list[ContextUnitRecord]] = {}
    for record in records:
        ref_id = str(record.tags.get("ref_id") or "").strip()
        if not ref_id:
            continue
        if record.tags.get("slice") not in {
            SLICE_MODE_FIELD,
            SLICE_MODE_YAML_MAPPING_FIELD,
        }:
            continue
        if not record.tags.get("key_index"):
            continue
        grouped.setdefault(ref_id, []).append(record)

    indexes: list[InvestigationKeyIndex] = []
    for ref_id, group in sorted(grouped.items()):
        entries: list[InvestigationKeyEntry] = []
        for record in sorted(
            group, key=lambda item: str(item.tags.get("field") or "")
        ):
            field = str(record.tags.get("field") or "").strip()
            if not field:
                continue
            entries.append(InvestigationKeyEntry(
                key=field,
                name=f"Evidence {ref_id} · {field}",
                search_text=(
                    f"{field} {_project_field_slice_value_text(record.content)}"
                ),
                target_ref=(
                    f"evidence-navigation://{ref_id}/{quote(field, safe='')}"
                ),
            ))
        if entries:
            indexes.append(InvestigationKeyIndex(
                index_key=f"authority.evidence.{ref_id}",
                collection_ref=ref_id,
                target_kind="evidence_locator",
                entry_granularity="field",
                entries=tuple(entries),
            ))
    return indexes


def _enrich_material_decision_index_with_values(
    indexes: Sequence[InvestigationKeyIndex],
    records: Sequence[ContextUnitRecord],
) -> list[InvestigationKeyIndex]:
    """把物化切片的值级内容投影进 material-decisions 索引（运行时值检索面）。

    证明力分类合同（哪个资料是 normative_rule/inlive_boundary/current_behavior）
    决定 authority 对同一证据的证明力判断；但 manifest 冻结的 decision search_text
    只有决策声明文本，没有具体口语值/枚举值，导致按值（如「孤儿单」）检索
    material decision 恒为空。切片内容来自运行时物化（字段枚举来自业务源，运行时
    才知道最新值），因此值级投影在运行时确定性完成，与字段切片的 key-index 投影
    同一机制。
    """
    records_by_ref: dict[str, list[str]] = {}
    for record in records:
        ref_id = str(record.tags.get("ref_id") or "").strip()
        content = str(record.content or "").strip()
        if ref_id and content:
            records_by_ref.setdefault(ref_id, []).append(content)
    if not records_by_ref:
        return list(indexes)
    enhanced: list[InvestigationKeyIndex] = []
    for index in indexes:
        if index.index_key != MATERIAL_DECISION_INDEX_KEY or not index.entries:
            enhanced.append(index)
            continue
        new_entries = []
        for entry in index.entries:
            key = str(entry.key or "")
            source_ref_id = key.split(".decision-", 1)[0]
            values = records_by_ref.get(source_ref_id)
            if not values:
                new_entries.append(entry)
                continue
            value_text = " ".join(
                part for part in values if str(part or "").strip()
            )
            if not value_text:
                new_entries.append(entry)
                continue
            # 每条 decision 追加值级检索面。search_text 只用于词法匹配，不进模型
            # 上下文（key-index 检索面），截断上限只需防止极端膨胀，不能按字典序
            # 截掉目标值（如孤儿单在 value-mappings 33 个切片里排后）。
            suffix = f" 证据值域：{value_text[:30000]}"
            if suffix not in str(entry.search_text or ""):
                new_entries.append(replace(
                    entry,
                    search_text=f"{entry.search_text or ''}{suffix}",
                ))
            else:
                new_entries.append(entry)
        enhanced.append(replace(index, entries=tuple(new_entries)))
    return enhanced


def _build_evidence_load_target_resolver(
    records: Sequence[ContextUnitRecord],
    run: ContextRun,
) -> Callable[[str, str], Mapping[str, Any]]:
    """Build a deterministic source_ref/locator -> run-scoped load-target resolver."""
    records_by_ref: dict[str, list[ContextUnitRecord]] = {}
    for record in records:
        ref_id = str(record.tags.get("ref_id") or "").strip()
        if ref_id:
            records_by_ref.setdefault(ref_id, []).append(record)

    def resolve(source_ref_id: str, locator: str) -> Mapping[str, Any]:
        ref_id = str(source_ref_id or "").strip()
        locator_text = str(locator or "").strip()
        candidates = records_by_ref.get(ref_id, [])
        matched: list[ContextUnitRecord] = []
        strategy = ""

        if len(candidates) == 1:
            matched = list(candidates)
            strategy = "single-materialized-unit"
        elif candidates:
            range_match = _LIST_RANGE_LOCATOR.search(locator_text)
            if range_match:
                path = range_match.group("path")
                target_start = int(range_match.group("start"))
                target_end = int(range_match.group("end"))
                for record in candidates:
                    tags = record.tags
                    if tags.get("slice") != SLICE_MODE_YAML_LIST_CHUNK:
                        continue
                    record_path = ".".join(
                        part
                        for part in (
                            str(tags.get("root_key") or "").strip(),
                            str(tags.get("list_key") or "").strip(),
                        )
                        if part
                    )
                    if record_path and not path.endswith(record_path):
                        continue
                    try:
                        record_start = int(str(tags.get("slice_start") or ""))
                        record_end = int(str(tags.get("slice_end") or ""))
                    except ValueError:
                        continue
                    if record_start <= target_end and target_start <= record_end:
                        matched.append(record)
                strategy = "yaml-list-range-overlap"
            else:
                # 投影索引的 target_ref 是精确字段名；子串匹配会把
                # "polNo" 误配到 "polNoInfo.applicantname"，导致精确定位失败。
                # 先做精确匹配，失败才回退唯一子串匹配。
                exact_matches = [
                    record
                    for record in candidates
                    if record.tags.get("slice") in {
                        SLICE_MODE_FIELD,
                        SLICE_MODE_YAML_MAPPING_FIELD,
                    }
                    and str(record.tags.get("field") or "").strip()
                    and str(record.tags.get("field") or "").strip() == locator_text
                ]
                if len(exact_matches) == 1:
                    matched = exact_matches
                    strategy = "field-locator"
                else:
                    field_matches = [
                        record
                        for record in candidates
                        if record.tags.get("slice") in {
                            SLICE_MODE_FIELD,
                            SLICE_MODE_YAML_MAPPING_FIELD,
                        }
                        and str(record.tags.get("field") or "").strip()
                        and str(record.tags.get("field") or "").strip() in locator_text
                    ]
                    if len(field_matches) == 1:
                        matched = field_matches
                        strategy = "field-locator-substring"

        if len(matched) > _MAX_RESOLVED_LOAD_TARGETS:
            return {
                "load_targets": [],
                "status": "too_broad",
                "strategy": strategy,
                "matched_unit_count": len(matched),
                "reason": (
                    "locator covers more units than one Context Load call permits; "
                    "use a narrower key-index target"
                ),
            }
        load_targets = run.selection_refs_for_context_units(
            [record.id for record in matched]
        ) if matched else ()
        return {
            "load_targets": list(load_targets),
            "status": "resolved" if load_targets else "unresolved",
            "strategy": strategy or "no-deterministic-match",
            "matched_unit_count": len(matched),
        }

    return resolve


def _tool_fingerprint(tool: Any) -> str:
    tool_id = str(getattr(tool, "tool_id", "") or getattr(tool, "name", "") or "")
    description = str(getattr(tool, "description", "") or "")
    return f"{tool_id}:{description}"


def _materialize_tool_result(
    runtime: ContextRuntime,
    run: ContextRun,
    *,
    project_id: str,
    role: str,
    tool_id: str,
    result: ToolResult,
    trace_id: str = "",
    case_id: str = "",
) -> Optional[str]:
    """把一次业务 Tool 执行结果物化为 case-scoped ContextUnit（Materializer 动态通道）。

    authority.md §4.2：Agent 新调用的业务 Tool 结果必须先物化为当前 Authority
    证据空间可见的 ContextUnit，再允许进入 basis_evidence_ref_ids。物化后自动
    Load 进当前 run，使 authority 可以在 basis 中引用其 unit_id（ref 校验要求
    已实际 Load 且 hash 未变）。

    物化/注册/加载失败不阻塞工具结果返回：LLM 仍能看到工具结果，但该结果无法
    被引用为 basis（返回 None），避免把基础设施问题伪装成业务 unresolved。
    """
    try:
        content = json.dumps(
            to_dict(result),
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError) as exc:
        logger.warning(
            "[authority_environment] tool result serialization failed tool=%s: %s",
            tool_id,
            exc,
        )
        return None
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    unit_id = f"authority-case-{digest}"
    tags = {
        "tool_id": tool_id,
        "scope": SCOPE_CASE,
    }
    if trace_id:
        tags["trace_id"] = trace_id
    if case_id:
        tags["case_id"] = case_id
    try:
        record = ContextUnitRecord(
            id=unit_id,
            name=f"Authority Tool {tool_id}",
            description=f"authority 业务工具 {tool_id} 本轮执行结果（case-scoped 物化）",
            content=content,
            content_ref=None,
            project_id=project_id,
            scope=SCOPE_CASE,
            roles=(role,),
            unit_type="tool_result",
            source_type="runtime_tool",
            tags=tags,
        )
        runtime.register_context_unit(record)
        run.load_context_units([unit_id])
        return unit_id
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[authority_environment] tool result materialization failed tool=%s: %s",
            tool_id,
            exc,
        )
        return None


def _contextualize_gateway_tools(
    env_factory: Callable[[], tuple[ContextRuntime, ContextRun]],
    tools: Iterable[VerifiableTool],
    *,
    project_id: str,
    role: str,
    trace_id: str = "",
    case_id: str = "",
) -> list[Any]:
    """包装 gateway VerifiableTool：执行后自动物化结果，供 Authority 引用 basis。

    ToolGateway Port（authority.md §4.2）：执行结果自动回填物化。包装在
    execute_fn 外层：先执行原工具，再把 ToolResult 物化为 case-scoped
    ContextUnit 并自动 Load，把物化 unit_id 追加进工具结果文本，LLM 即可在
    basis_evidence_ref_ids 中引用该地址。
    """
    wrapped: list[VerifiableTool] = []
    for tool in tools:
        execute = tool.execute_fn
        if execute is None:
            raise ValueError(f"VerifiableTool.execute_fn is required: {tool.tool_id}")

        def execute_and_materialize(
            _execute=execute,
            _tool=tool,
            **kwargs: Any,
        ) -> ToolResult:
            result = _execute(**kwargs)
            unit_id = _materialize_tool_result(
                *(env_factory()),
                project_id=project_id,
                role=role,
                tool_id=_tool.tool_id,
                result=result,
                trace_id=trace_id,
                case_id=case_id,
            )
            if unit_id:
                marker = f"\n[authority-evidence] materialized unit_id: {unit_id}"
                result.evidence = f"{result.evidence}{marker}".strip()
                runtime_metadata = getattr(result, "runtime_metadata", None)
                if isinstance(runtime_metadata, dict):
                    runtime_metadata["authority_evidence"] = {
                        "registered": True,
                        "unit_id": unit_id,
                        "scope": SCOPE_CASE,
                    }
            return result

        wrapped.append(VerifiableTool(
            tool_id=tool.tool_id,
            description=tool.description
            + " 执行结果会自动物化为可寻址证据单元，可直接在 basis_evidence_ref_ids 引用其 unit_id。",
            applicable_scenario=tool.applicable_scenario,
            parameters=tool.parameters,
            execute_fn=execute_and_materialize,
        ))
    return build_agno_tools(wrapped)


class AuthorityContextTools(GuardedContextTools):
    """Authority Agent 专用绑定：限制候选宽度并让 Load 暴露证据地址。

    主 LLM 上下文仍使用 GuardedContextTools（selection_ref 遮罩，防止主 LLM 传播
    物理 ID）；Authority Agent 是 Core 自有会话，其 basis_evidence_ref_ids 必须
    回到物化 unit_id（authority.md §4.2 EvidenceSpace/单条物化通道），因此 Load
    返回物化地址，Search 仍只返回候选 selection_ref。
    """

    def search_context_units(
        self,
        queries: Annotated[list[str], Field(min_length=1, max_length=4)],
    ):
        """Search compact Authority candidates with a fixed three-hit cap.

        Authority is a narrow decision subcall rather than an open-ended investigator.
        Candidate width is runtime-owned so the model cannot expand context or misspell
        tuning parameters; callers only provide the atomic information needs.
        """

        return search_context_units_tool(
            self._context_run, queries, top_k_per_query=3
        )

    def load_context_units(
        self, unit_ids: Annotated[list[str], Field(min_length=1, max_length=8)]
    ):
        """Load 1-8 exact ContextUnit IDs/selection_refs; results expose materialized unit_id."""

        return load_context_units_tool(
            self._context_run, unit_ids, expose_materialized_ids=True
        )


def build_authority_environment(
    spec: Any,
    *,
    role: str = "judge",
    use_candidate: bool = False,
    gateway_tools: Iterable[Any] = (),
    embedding_provider: Any = None,
    trace_id: str = "",
    case_id: str = "",
    business_source_staleness_policy: str = "strict",
) -> AuthorityEnvironment:
    """Core-owned AuthorityEnvironment 构造器。

    主 LLM 不能选择或扩大该空间。permission_boundary 由 ProjectSpec + Role +
    Draft/Production 资产选择确定性组合；snapshot 覆盖项目、Role、资产来源、
    资料 revision 与工具指纹。
    """
    runtime, run = _build_context_runtime(
        spec,
        role=role,
        use_candidate=use_candidate,
        embedding_provider=embedding_provider,
        trace_id=trace_id,
        case_id=case_id,
    )
    manifest_records, materialize_errors, staleness_warnings = _materialize_manifest_evidence_refs(
        spec,
        runtime,
        role=role,
        use_candidate=use_candidate,
        business_source_staleness_policy=business_source_staleness_policy,
    )
    if materialize_errors:
        raise AuthorityEnvironmentInvalid(materialize_errors)
    if manifest_records:
        runtime.register_context_units(manifest_records)
    _invalidate_stale_evidence_refs(
        runtime, spec.project_id, role, active_ids={r.id for r in manifest_records}
    )

    evidence_records_by_ref: dict[str, list[ContextUnitRecord]] = {}
    for record in manifest_records:
        ref_id = str(record.tags.get("ref_id") or "").strip()
        if ref_id:
            evidence_records_by_ref.setdefault(ref_id, []).append(record)
    evidence_unit_ids = {
        ref_id: records[0].id
        for ref_id, records in evidence_records_by_ref.items()
        if len(records) == 1
    }
    navigation_tools: list[Any] = []
    if role == "judge":
        selected_investigations = [
            item
            for item in resolve_role_assets(spec, role, use_candidate=use_candidate)
            if item["mapping"].kind == "investigation" and item.get("available")
        ]
        if len(selected_investigations) == 1:
            report_path = Path(selected_investigations[0]["path"]) / "docs/authority-investigation-report.json"
            if report_path.is_file():
                report = load_authority_investigation_report(report_path)
                investigation_manifest = load_investigation_manifest(
                    Path(selected_investigations[0]["path"]) / "manifest.json"
                )
                projected_evidence_indexes = (
                    _project_field_slice_evidence_indexes(manifest_records)
                )
                manifest_indexes = _enrich_material_decision_index_with_values(
                    list(investigation_manifest.key_indexes),
                    manifest_records,
                )
                # manifest 显式登记优先；投影跳过已登记的 index_key，避免重复注册。
                known_index_keys = {item.index_key for item in manifest_indexes}
                navigation_tools = list(create_authority_navigation_tools(
                    report,
                    evidence_unit_ids=evidence_unit_ids,
                    indexes=[
                        *manifest_indexes,
                        *(
                            item
                            for item in projected_evidence_indexes
                            if item.index_key not in known_index_keys
                        ),
                    ],
                    load_target_resolver=_build_evidence_load_target_resolver(
                        manifest_records, run
                    ),
                ))

    raw_tools = list(gateway_tools or [])
    tools = _contextualize_gateway_tools(
        lambda: (runtime, run),
        raw_tools,
        project_id=spec.project_id,
        role=role,
        trace_id=trace_id,
        case_id=case_id,
    ) if raw_tools else []
    permission_boundary = {
        "project_id": spec.project_id,
        "caller_role": role,
        "asset_source": "candidate" if use_candidate else "production",
        "context_unit_count": len(manifest_records),
        "gateway_tool_count": len(tools),
        "navigation_tool_count": len(navigation_tools),
        "context_policy": run.debug_snapshot()["context_debug"]["policy"],
    }

    evidence_fingerprints = _registered_context_fingerprints(
        runtime, manifest_records
    )
    tool_fingerprints = sorted(_tool_fingerprint(tool) for tool in [*tools, *navigation_tools])
    snapshot = _sha256({
        "protocol_version": AUTHORITY_RUNTIME_PROTOCOL_VERSION,
        "project_id": spec.project_id,
        "caller_role": role,
        "use_candidate": bool(use_candidate),
        "evidence_fingerprints": evidence_fingerprints,
        "tool_fingerprints": tool_fingerprints,
        "permission_boundary": permission_boundary,
    })
    logger.info(
        "[authority_environment] snapshot=%s project=%s role=%s evidence=%d tools=%d",
        snapshot[:12], spec.project_id, role, len(manifest_records), len(tools),
    )
    return AuthorityEnvironment(
        spec=spec,
        project_id=spec.project_id,
        caller_role=role,
        trace_id=str(trace_id or ""),
        case_id=str(case_id or ""),
        governance_mode="draft" if use_candidate else "production",
        context_run=run,
        context_runtime=runtime,
        gateway_tools=tools,
        navigation_tools=navigation_tools,
        permission_boundary=permission_boundary,
        environment_snapshot_sha256=snapshot,
        registration_errors=list(materialize_errors),
    )


def _resolve_system_prompt(env: AuthorityEnvironment) -> str:
    prompt = (
        "你是通用 Authority Agent，负责确定一个完整业务问题的可靠结论。\n\n"
        "## 判断顺序\n"
        "1. 校验 decision_question 是否只包含一个业务决定问题，并识别其中会改变答案的业务条件；\n"
        "2. 根据问题中明确的上下游、版本、渠道、产品或其他条件排除明显不适用的资料；\n"
        "3. 通过已绑定的证据空间加载当前项目允许的资料（使用 search/load 工具）；\n"
        "4. 信息不足时按需调用检索或业务验证工具；\n"
        "5. 对每份决定性资料识别其来源、业务定位、适用条件和上下游消费关系；\n"
        "6. 严格按资料定位判断证明力：normative_rule / external_fact > "
        "inlive_boundary（仅在项目已登记信任模型时）> current_behavior；"
        "证明力档位随担保定：若 MaterialDecision 显式声明 warrant_tier（导航内容的 "
        "proof_power 字段即最终档位），以该担保档位为准；未声明时按 conclusion_kind "
        "缺省映射（两者不一致时以 proof_power 为准，不得自行升降档）。"
        "current_behavior 只说明系统现在如何做，永远不能单独裁决正式业务口径、正确映射或应然规则。"
        "尤其是问题包含‘应、正确、正式、业务语义’等规范性含义时，即使当前配置只有唯一映射/规则，"
        "也不能把‘当前唯一实现’升级为‘正式正确结论’；缺少 normative_rule/external_fact 时必须 unresolved。"
        "MaterialDecision 虽不是事实证据，却是调查层给出的证明范围合同：加载原始资料后，也只能按该 "
        "decision 的 conclusion_kind、governs、conditions、scenario 和 limitations 使用；不得因为原文中出现"
        "规则、notes、示例、operator 或映射表，就自行把它升级成 normative_rule / external_fact；"
        "特别是：M1/inlive_boundary 只可作为已登记信任模型下的边界代理，证明字段/枚举空间的可承载性，"
        "不能证明某个具体口语、别名或输入值应当映射到哪个归一值，也不能覆盖 MaterialDecision 对该具体选择"
        "标注的 conclusion_kind=current_behavior 或 limitations（例如‘只能说明当前 parser 做法、不能证明正式正确性’）。"
        "若问题要求正式业务口径、正确映射或应然规则，且相关已加载/导航到的决定性资料只有 current_behavior 或"
        "inlive_boundary，而没有明确 governing 的 normative_rule/external_fact，则必须返回 unresolved；"
        "不得把当前唯一实现、唯一配置或 M1 边界代理升级成正式正确答案；\n"
        "7. 判断是否存在能够在问题明确条件内唯一决定问题的证据；\n"
        "8. 能确定时返回 resolved；仍冲突或缺少决定性证据时返回 unresolved。\n\n"
        "## Context Search→Load 顺序与预算（硬协议）\n"
        "- 第一轮工具调用只能调用一次 search_context_units：把 1-4 个原子信息需求放进同一个 queries 数组；禁止在这一轮并行调用 investigation_search_index、investigation_load_entry 或其他工具；\n"
        "- Search 只要返回至少一个可能决定答案的原始资料候选，下一步必须立即 Load：紧接着的一轮只能调用一次 load_context_units，并批量加载最小充分候选；在完成这次 Load 前禁止第二次 Search、不得连续改写同义词搜索；\n"
        "- Search 未返回任何候选时，下一轮可用 investigation_search_index 做值级/字段级检索：把具体枚举值、别名、字段名或操作符作为 query，优先在已注册的内部对象索引（authority.evidence.*）按值定位字段切片；命中后必须紧跟 investigation_load_entry 取得 load_targets，再立即 load_context_units，不得停留在导航结果；\n"
        "- Search 已返回候选时必须先 Load 确认（不得以“候选不决定性”跳过）；Load 后仍缺决定性证据时，才可导航内部对象索引精确定位，导航后同样必须 Load；\n"
        "- 只有完成第一次原始资料 Load 后，仍需要确认资料的证明范围或冲突登记时，才可调用 investigation_load_entry 读取 MaterialDecision/coverage gap（该用途的 load_entry 受此时序限制）；用于内部对象索引（authority.evidence.*）的 load_entry 是值级检索流程的一部分，不受此限制；任何 load_entry 返回 load_targets 后，下一轮必须立即 Load；\n"
        "- MaterialDecision/coverage gap 只限定证明范围。若导航已给出原始资料候选，优先 Load 原始资料；不要为了重复确认管辖关系耗尽原始证据的 Load 预算；\n"
        "- 每次 load_context_units 最多 8 个 selection_ref，优先只加载 1-2 个最可能决定答案的候选；\n"
        "- 不得提交 9 个或更多 ID；候选很多时先加载最强来源，只有仍缺决定性证据才继续加载；\n"
        "- 大枚举已按块物化。查询精确名称时只加载包含该名称的枚举块，不得尝试加载全量枚举。\n\n"
        "## resolved 的最低要求\n"
        "- statement 非空；reason 非空并说明为什么当前资料对问题中的业务条件具有决定性；\n"
        "- basis_evidence_ref_ids 非空，且只能引用本会话中 load_context_units 或工具结果\n"
        "  实际返回的物化 unit_id（authority-ref-* / authority-case-*）；禁止凭记忆拼写、\n"
        "  猜测或按格式编造 unit_id，只有 Load/工具结果文本中真实出现的 unit_id 才有效；\n"
        "  引用时必须逐字符原样复制完整 unit_id，不得改动任何字符（一个字符抄错就会导致\n"
        "  引用核验失败并按依据不充分处理）；search 只返回候选 selection_ref，必须再 Load\n"
        "  拿到物化 unit_id 才能引用；禁止填写 C1/C2、资料标题、文件名等未物化标识；\n"
        "- 如果存在冲突，必须说明为什么某份资料在当前条件下具有决定性，而不是只声明'优先级更高'；\n"
        "- 如果导航结果包含与 decision_question 匹配的 coverage_gap，必须加载并检查它。若当前已加载依据"
        "仅来自该 gap 的 basis_source_ref_ids，且没有找到 required_evidence 所要求类型的新决定性证据，"
        "必须 unresolved；不得从这些已登记为不足或冲突的资料中重新挑一份宣布 resolved。coverage_gap 本身"
        "仍只是调查定位合同，不能写入 basis_evidence_ref_ids；basis 应引用实际 Load 到的冲突/不足资料。\n\n"
        "## 能力/职责边界类问题的 statement 约束（authority.md §5/§8.2）\n"
        "当 decision_question 是能力/职责边界问题（<产品/模块> 是否支持 <某能力>？"
        "或 <事项> 是否属于 <产品> 职责？）时，resolved 的 statement 必须以"
        "「职责外：」「职责内能力缺失：」「职责内正常：」之一开头（冒号为中文全角），"
        "且只能以这三个前缀之一开头，再写结论内容：\n"
        "- 职责外：产品没有该能力 / 不在职责范围；\n"
        "- 职责内能力缺失：应具备但未实现 / 表达不了；\n"
        "- 职责内正常：属于职责且能力可用。\n"
        "不能只写“可以确定”这类无内容的话。结论类型通过 statement 前缀表达，"
        "gate 按前缀确定性消费（职责外→not_evaluable；职责内能力缺失→not_fulfilled），"
        "不新增 schema 字段。\n\n"
        "## unresolved 的最低要求\n"
        "- statement 为空；reason 具体说明冲突、证据不足或问题业务条件不明；\n"
        "- required_evidence 非空，说明缺少哪类决定性证据；\n"
        "- 如果已经发现资料或冲突，必须进入 basis_evidence_ref_ids（同样必须是 Load 返回的\n"
        "  物化 unit_id，规则同 resolved）。\n\n"
        "## 禁止事项\n"
        "- 不比较全局资料优先级；不做'当前输出对不对'的判断（那是 Judge 的职责）；\n"
        "- 不编造资料来源、版本或验证结果；找不到决定性证据必须 unresolved；\n"
        "- 分析文字必须使用中文。\n"
    )
    navigation_hints = []
    for tool in getattr(env, "navigation_tools", []) or []:
        logical_tool_id = str(getattr(tool, "tool_id", "") or getattr(tool, "name", "") or "")
        description = str(getattr(tool, "description", "") or "")
        if logical_tool_id:
            navigation_hints.append(
                f"- {runtime_tool_name(logical_tool_id)}：{description}"
            )
    if navigation_hints:
        prompt += (
            "\n## 可用调查导航工具\n"
            "这些工具只用于导航定位（MaterialDecision 证明范围，或 authority.evidence.* 内部"
            "对象的字段/值级检索），不是事实证据。命中不等于事实，"
            "未命中不等于不存在或 unresolved。首次未命中时，必须至少改写一次 query（改用字段名、"
            "值名、事项名或更短的关键表达）重试；仍未命中则回到 Context Search/Load 检索真实资料。"
            "只有完成上述检索且决定性证据仍不足，才可 unresolved。load_entry 返回的 decision 也不能直接写入 "
            "basis_evidence_ref_ids；若 load_entry 顶层返回 load_targets，必须优先逐字使用这些 "
            "selection_ref 执行 Context Load，不得对同一 locator 无理由退回模糊 Search；只有未返回 "
            "load_targets 或精确加载失败时，才按 evidence_unit_id（若有）或 evidence_search_hint "
            "继续 Context Search/Load。只有实际加载的真实资料才能引用。\n"
            + "\n".join(navigation_hints)
            + "\n"
        )
    tool_hints = []
    for tool in getattr(env, "gateway_tools", []) or []:
        logical_tool_id = str(getattr(tool, "tool_id", "") or getattr(tool, "name", "") or "")
        description = str(getattr(tool, "description", "") or "")
        if logical_tool_id:
            tool_hints.append(
                f"- {runtime_tool_name(logical_tool_id)}：{description}"
            )
    if tool_hints:
        prompt += (
            "\n## 可用业务验证工具\n"
            "下列工具执行结果会自动物化为可寻址证据单元（authority-case-*）。调用工具后，\n"
            "工具结果文本会附带 [authority-evidence] materialized unit_id；若该结果对结论\n"
            "具有决定性，必须在 basis_evidence_ref_ids 中逐字符原样复制该 unit_id（规则同\n"
            "Load 返回的物化 unit_id，禁止填写工具名、字段名等未物化标识）。\n"
            + "\n".join(tool_hints)
            + "\n"
        )
    return prompt


@dataclass(frozen=True)
class _AuthorityClaimComparison:
    """担保模式第二阶段的窄域比对输出；不得生成新的业务结论或依据。"""

    status: str
    reason: str


def _normalize_independent_resolution(
    env: AuthorityEnvironment,
    data: Mapping[str, Any],
) -> AuthorityIndependentResolution:
    """校验并归一化盲查阶段结果，保持原 resolved/unresolved 语义。"""
    if data.get("error"):
        raise RuntimeError(
            "authority.resolve LLM 请求失败："
            f"{data.get('error')} {data.get('raw_text') or ''}".strip()
        )

    status = str(data.get("status") or "").strip()
    if status not in {"resolved", "unresolved"}:
        raise ValueError(
            f"AuthorityResolution.status must be resolved|unresolved: {status!r}"
        )
    statement = str(data.get("statement") or "").strip()
    reason = str(data.get("reason") or "").strip()
    raw_basis = tuple(
        str(item)
        for item in (data.get("basis_evidence_ref_ids") or [])
        if str(item).strip()
    )
    required = tuple(
        str(item)
        for item in (data.get("required_evidence") or [])
        if str(item).strip()
    )

    # basis 只能引用当前 run 实际 Load 且 hash 未变的物化证据。
    materialized_basis: list[str] = []
    invalid_basis: list[str] = []
    for ref in raw_basis:
        unit_id = env.context_run.materialized_unit_id_for_selection_ref(ref) or ref
        if not env.ref_loaded_unchanged(unit_id):
            invalid_basis.append(ref)
            continue
        materialized_basis.append(unit_id)
    basis = tuple(dict.fromkeys(materialized_basis))

    if status == "resolved":
        if not statement or not reason:
            missing = "statement" if not statement else "reason"
            status = "unresolved"
            statement = ""
            reason = (
                f"resolved 结论缺少 {missing}，无法提供可消费的定论，按依据不充分处理。"
                f"{reason}".strip()
            )
        elif not basis:
            status = "unresolved"
            statement = ""
            origin = f"（引用均无法核验：{invalid_basis}）" if invalid_basis else ""
            reason = (
                f"resolved 结论缺少可核验的 basis 依据{origin}，按依据不充分处理。"
                f"{reason}".strip()
            )

    if status == "unresolved":
        if statement:
            reason = f"{statement} {reason}".strip()
            statement = ""
        if invalid_basis:
            reason = (
                "引用的依据无法核验（不在当前证据空间或本 run 未 Load）："
                f"{invalid_basis}。{reason}".strip()
            )
        if not required:
            required = ("补充可裁决该判断点的权威资料（当前依据不充分，无法定论）",)
        if not reason:
            reason = "依据不充分：当前资料无法唯一决定该判断点。"

    return AuthorityIndependentResolution(
        status=status,
        statement=statement,
        reason=reason,
        basis_evidence_ref_ids=basis,
        required_evidence=required,
    )


def _claim_comparison_prompt() -> str:
    return (
        "你是 Authority 担保比对器。独立裁决已经在看不到 claim 的阶段完成；"
        "你只能比较该独立裁决与待担保 claim，不得搜索、加载、调用工具、补充依据、"
        "改写或推翻独立裁决。\n"
        "若 independent_resolution.status=resolved，只能返回 supported（结论一致）"
        "或 contradicted（结论冲突）。\n"
        "若 independent_resolution.status=unresolved，只能返回 ungoverned（当前证据空间"
        "没有资料管辖该主题）或 gap_only（存在管辖资料/覆盖声明，但资料不足、冲突或"
        "缺少决定性条件）。\n"
        "context_coverage 是第一阶段检索的确定性 trace 派生信号："
        "has_candidate 与 has_loaded 均为 false 时分类为 ungoverned；"
        "存在候选或已 Load 证据但仍不足以裁决时分类为 gap_only。\n"
        "reason 只解释比对或缺口分类，不得产生新的业务事实。"
    )


def _derive_context_coverage(run: ContextRun | None) -> dict[str, Any]:
    """从 run 的确定性 trace 派生 coverage 信号，不依赖模型自述。

    区分 ungoverned（证据空间无任何候选/加载）与 gap_only（有管辖资料但不足）
    需要结构化信号：检索是否发生、候选宽度、实际 Load 宽度。全部来自
    ContextRun 的 debug snapshot（loaded/candidate trace），比对角色只消费投影，
    不能再搜索或加载。
    """
    if run is None:
        return {}
    debug = run.debug_snapshot().get("context_debug") or {}
    candidate_ids = list(debug.get("candidate_ids") or [])
    loaded_ids = list(debug.get("loaded_ids") or [])
    return {
        "searched": bool(debug.get("search_queries")),
        "candidate_count": len(candidate_ids),
        "loaded_count": len(loaded_ids),
        "has_candidate": bool(candidate_ids),
        "has_loaded": bool(loaded_ids),
    }


def _compare_claim(
    client: Any,
    request: AuthorityRequest,
    independent: AuthorityIndependentResolution,
    *,
    env: AuthorityEnvironment,
    authority_call_id: str,
) -> _AuthorityClaimComparison:
    """第二阶段只做 claim 比对；输入明确冻结第一阶段结论。"""
    from impl.core.structured_output import StructuredOutputSpec

    assert request.claim is not None
    client._caller = "authority-claim-compare"
    output_spec = StructuredOutputSpec.from_dataclass(
        _AuthorityClaimComparison,
        required_nonempty=["status", "reason"],
        description="authority.resolve 担保模式的独立结论比对结果",
    )
    system = _claim_comparison_prompt()
    # 比对角色只需要独立结论本身；basis 地址与 required_evidence 是第一阶段
    # 的证据地址，对 supported/contradicted/ungoverned/gap_only 分类无决策价值，
    # 不注入，避免无关 token 噪音。
    independent_view = {
        "status": independent.status,
        "statement": independent.statement,
        "reason": independent.reason,
    }
    user = json.dumps(
        {
            "independent_resolution": independent_view,
            "claim": to_dict(request.claim),
            "context_coverage": _derive_context_coverage(
                getattr(env, "context_run", None)
            ),
        },
        ensure_ascii=False,
    )
    from impl.core.context_governance import configure_context_governance
    configure_context_governance(
        client,
        config={
            "enabled": True,
            "mode": env.governance_mode,
            "role": "authority",
            "stage": "claim_compare",
            "trace_id": env.trace_id,
            "case_id": env.case_id,
            "call_id": authority_call_id,
            "compiler_source": "core://authority/claim-compare",
            "user_source": "trace://authority/independent-resolution-and-claim",
        },
        project_id=env.project_id,
        system=system,
        user=user,
        output_spec=output_spec,
        tools=[],
    )
    data = client.complete_json(
        system,
        user,
        trace_id=env.trace_id or "authority-resolve-claim-compare",
        output_spec=output_spec,
        # CG-ENG-008：注入路径下 comparison_client 可能与第一阶段同一 client，
        # 工具 schema 仍暴露；比对阶段必须在模型边界强制无工具，不只靠 prompt。
        tools_override=[],
    )
    if data.get("error"):
        raise RuntimeError(
            "authority.resolve claim 比对请求失败："
            f"{data.get('error')} {data.get('raw_text') or ''}".strip()
        )
    status = str(data.get("status") or "").strip()
    reason = str(data.get("reason") or "").strip()
    allowed = (
        {"supported", "contradicted"}
        if independent.status == "resolved"
        else {"ungoverned", "gap_only"}
    )
    if status not in allowed:
        raise ValueError(
            "Authority claim comparison status incompatible with independent "
            f"resolution {independent.status!r}: {status!r}; allowed={sorted(allowed)}"
        )
    if not reason:
        raise ValueError("Authority claim comparison reason is required")
    return _AuthorityClaimComparison(status=status, reason=reason)


def _validate_claim(request: AuthorityRequest) -> None:
    claim = request.claim
    if claim is None:
        return
    missing = []
    if not str(claim.claim_statement or "").strip():
        missing.append("claim_statement")
    if claim.subject is None or claim.subject == "" or claim.subject == {} or claim.subject == []:
        missing.append("subject")
    if not str(claim.conclusion_kind or "").strip():
        missing.append("conclusion_kind")
    if not str(claim.intended_use or "").strip():
        missing.append("intended_use")
    if missing:
        raise ValueError(f"AuthorityRequest.claim missing required fields: {missing}")
    try:
        json.dumps(to_dict(claim), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("AuthorityRequest.claim must be JSON serializable") from exc


def resolve_authority(
    env: AuthorityEnvironment,
    request: AuthorityRequest,
    *,
    llm: Any = None,
    authority_call_id: str = "",
) -> AuthorityResolution:
    """authority.resolve 的 Agent 入口（提问模式 + claim 担保模式）。

    担保模式仍是一次 Tool 调用，但内部严格分两阶段：先在不暴露 claim 的情况下
    独立裁决，再以无工具窄域任务比对 claim。执行失败与业务结果始终分开。
    """
    from impl.core.llm_client import project_llm_client
    from impl.core.structured_output import StructuredOutputSpec

    question = str(request.decision_question or "").strip()
    if not question:
        raise ValueError("AuthorityRequest.decision_question is required")
    _validate_claim(request)

    if env.spec is None:
        raise ValueError("AuthorityEnvironment.spec is required for resolve")
    search_tool = AuthorityContextTools(env.context_run)
    navigation_functions = build_agno_tools(env.navigation_tools)
    tools = [
        search_tool.search_context_units,
        search_tool.load_context_units,
        *navigation_functions,
        *env.gateway_tools,
    ]
    if llm is None:
        client = project_llm_client(
            env.spec,
            role=env.caller_role,
            knowledge=None,
            tools=tools,
            # Authority 是 Judge 的窄域子调用。预算必须至少容纳一次治理导航与
            # 两组直接 Evidence Search→Load；更高层 prompt 禁止同义词扩搜。
            tool_call_limit=AUTHORITY_INTERNAL_TOOL_CALL_LIMIT,
        )
        # 比对阶段必须在真正无工具的 client 上运行，不能只靠 prompt 约束。
        comparison_client = project_llm_client(
            env.spec,
            role=env.caller_role,
            knowledge=None,
            tools=[],
        )
    else:
        # 测试/宿主注入的 client 由宿主保证隔离；若提供 without_tools，则强制使用。
        client = llm
        without_tools = getattr(llm, "without_tools", None)
        comparison_client = without_tools() if callable(without_tools) else llm

    # 第一阶段请求刻意不含 claim；这是可由 audit/测试验证的信息隔离边界。
    # 注入路径下 client 与 comparison_client 可能是同一对象，_caller 必须在
    # 各自调用点设置，否则第一阶段 audit 记录会被第二阶段 caller 覆盖。
    client._caller = "authority"
    output_spec = StructuredOutputSpec.from_dataclass(
        AuthorityIndependentResolution,
        required_nonempty=["status", "reason"],
        description="authority.resolve 独立裁决的结构化结果",
    )
    system = _resolve_system_prompt(env)
    user = json.dumps(
        {
            "decision_question": question,
            "environment_snapshot_sha256": env.environment_snapshot_sha256,
        },
        ensure_ascii=False,
    )
    from impl.core.context_governance import configure_context_governance
    configure_context_governance(
        client,
        config={
            "enabled": True,
            "mode": env.governance_mode,
            "role": "authority",
            "stage": "independent_resolution",
            "trace_id": env.trace_id,
            "case_id": env.case_id,
            "call_id": authority_call_id,
            "compiler_source": "core://authority/independent-resolution",
            "user_source": "trace://authority/decision-question",
        },
        project_id=env.project_id,
        system=system,
        user=user,
        output_spec=output_spec,
        tools=tools,
    )
    independent_data = client.complete_json(
        system,
        user,
        trace_id=env.trace_id or "authority-resolve",
        output_spec=output_spec,
    )
    _validate_authority_tool_sequence(
        independent_data.get("_tool_call_log") or independent_data.get("tool_call_log") or []
    )
    independent = _normalize_independent_resolution(env, independent_data)

    if request.claim is None:
        return AuthorityResolution(
            status=independent.status,
            statement=independent.statement,
            reason=independent.reason,
            basis_evidence_ref_ids=independent.basis_evidence_ref_ids,
            required_evidence=independent.required_evidence,
        )

    comparison = _compare_claim(
        comparison_client,
        request,
        independent,
        env=env,
        authority_call_id=authority_call_id,
    )
    required = independent.required_evidence
    statement = independent.statement
    # ungoverned/gap_only 的 statement 恒为空（§5 unresolved 要求）；
    # required_evidence 已由 _normalize_independent_resolution 在 unresolved 时
    # 兜底补默认，这里不再重复分支（AUTH-R17-003 死代码清理）。
    if comparison.status in ("ungoverned", "gap_only"):
        statement = ""

    return AuthorityResolution(
        status=comparison.status,
        statement=statement,
        reason=comparison.reason,
        basis_evidence_ref_ids=independent.basis_evidence_ref_ids,
        required_evidence=required,
        independent_resolution=independent,
    )
