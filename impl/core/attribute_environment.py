"""Internal Attribute capability assembly.

This module deliberately does not introduce a public protocol object.  It binds
the capabilities already authorized by ProjectSpec to one Attribute execution
and gives the main run and the independent reviewer equivalent, isolated tool
surfaces.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from impl.tools.protocol import VerifiableTool, build_agno_tools
from impl.tools.source_retrieval import (
    ProjectSourceFileProvider,
    create_source_retrieval_tools,
    create_source_search_tools,
)

from .context.adapters import (
    initialize_context_adapters,
    load_configured_context_adapter,
    load_project_context_adapter,
)
from .context.bootstrap import DEFAULT_CONTEXT_DATA_ROOT, build_context_runtime
from .context.embedding import BailianEmbeddingProvider
from .context.errors import ContextValidationError
from .context.resolvers import CompositeContentResolver, FileContentResolver
from .context.tools import GuardedContextTools
from .context.models import ContextUnitRecord
from .context.project import role_asset_context_records
from .schema import AttributionFinding, EvidenceRef, to_dict


_ATTRIBUTE_CONTEXT_POLICY = {
    "default": {
        "enabled": True,
        "allowed_roles": ["attribute"],
        "allowed_statuses": ["active"],
        "candidate_limit": 20,
        "load_limit": 8,
        "content_char_budget": 100_000,
        "query_limit": 4,
        "top_k_per_query": 5,
    }
}

ATTRIBUTE_FINALIZATION_PROMPT_CHAR_BUDGET = 160_000
ATTRIBUTE_REVIEW_PROMPT_CHAR_BUDGET = 180_000


def normalize_attribute_tools(tools: Iterable[Any]) -> list[Any]:
    """Strictly normalize project/common tools to objects accepted by Agno."""
    normalized: list[Any] = []
    verifiable: list[VerifiableTool] = []
    for tool in list(tools or []):
        if isinstance(tool, VerifiableTool):
            verifiable.append(tool)
            continue
        if callable(tool) or (
            getattr(tool, "name", None) and getattr(tool, "entrypoint", None) is not None
        ):
            normalized.append(tool)
            continue
        # Agno Toolkits expose a tools collection and are valid Agent tools.
        if getattr(tool, "tools", None) is not None:
            normalized.append(tool)
            continue
        raise TypeError(
            "Attribute tools must be VerifiableTool, Agno Function/Toolkit, or callable; "
            f"received {type(tool).__name__}"
        )
    if verifiable:
        normalized.extend(build_agno_tools(verifiable))
    return _deduplicate_tools(normalized)


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", None) or getattr(tool, "__name__", None) or type(tool).__name__)


def _deduplicate_tools(tools: Iterable[Any]) -> list[Any]:
    result = []
    names = set()
    for tool in tools:
        name = _tool_name(tool)
        if name in names:
            raise ValueError(f"duplicate Attribute tool name: {name}")
        names.add(name)
        result.append(tool)
    return result


def _configured_context(spec: Any) -> bool:
    extra = getattr(spec, "extra", {}) or {}
    context_config = extra.get("context") if isinstance(extra, Mapping) else None
    if isinstance(context_config, Mapping) and context_config:
        return True
    if any(
        mapping.enabled
        and "attribute" in mapping.roles
        and mapping.kind in {"context", "investigation"}
        for mapping in (getattr(spec, "role_assets", None) or [])
    ):
        return True
    root_text = str(getattr(spec, "root", "") or "")
    if root_text and (Path(root_text) / "context_adapter.py").is_file():
        return True
    database = DEFAULT_CONTEXT_DATA_ROOT / str(getattr(spec, "project_id", "") or "") / "context.sqlite3"
    return database.is_file()


def _content_resolver(spec: Any) -> CompositeContentResolver:
    roots = []
    for candidate in (
        getattr(spec, "root", ""),
        getattr(spec, "source_project", ""),
        (getattr(spec, "application", {}) or {}).get("external_repo"),
    ):
        if candidate:
            path = Path(str(candidate)).resolve()
            if path.exists() and path not in roots:
                roots.append(path)
    return CompositeContentResolver([FileContentResolver(roots)] if roots else [])


def _build_context_tools(
    spec: Any,
    trace: Any,
    embedding_provider: Any = None,
) -> tuple[list[Any], list[Any], dict[str, Any], Any, Any]:
    context_config = dict((getattr(spec, "extra", {}) or {}).get("context") or {})
    project_policy = context_config.get("policy") if isinstance(context_config.get("policy"), Mapping) else None
    draft_enabled = bool((getattr(spec, "attribute_draft", {}) or {}).get("enabled"))
    # Candidate investigation ContextUnits must never remain searchable by Current
    # after a Draft run.  Keep mode databases isolated while retaining stable IDs.
    context_data_root = DEFAULT_CONTEXT_DATA_ROOT / (
        "attribute-draft" if draft_enabled else "attribute-production"
    )
    runtime = build_context_runtime(
        project_id=spec.project_id,
        data_root=context_data_root,
        project_root=Path(spec.root) if getattr(spec, "root", "") else None,
        embedding_provider=embedding_provider or BailianEmbeddingProvider(),
        content_resolver=_content_resolver(spec),
        public_policy=_ATTRIBUTE_CONTEXT_POLICY,
        project_policy=project_policy,
    )
    adapters = [
        adapter
        for adapter in (load_configured_context_adapter(spec), load_project_context_adapter(spec))
        if adapter is not None
    ]
    asset_records = role_asset_context_records(
        spec,
        role="attribute",
        use_candidate=draft_enabled,
        require_available=False,
    )
    asset_registration = runtime.register_context_units(asset_records) if asset_records else None
    initialization = None
    if adapters:
        initialization = initialize_context_adapters(
            runtime,
            project_spec=spec,
            project_adapters=adapters,
        )

    execution_run_id = f"attribute-{uuid.uuid4().hex}"
    run_args = {
        "role": "attribute",
        "operation": "attribute",
        "trace_id": str(getattr(trace, "trace_id", "") or ""),
        "case_id": str(getattr(trace, "case_id", "") or ""),
    }
    # Static project ContextUnits have no run_id and remain reusable. Dynamic
    # case materials are tagged with this execution id, so rerunning the same
    # trace cannot search or load evidence produced by an earlier Attribute run.
    main_run = runtime.start_run(run_id=execution_run_id, **run_args)
    review_run = runtime.start_run(run_id=execution_run_id, **run_args)
    main_tools = GuardedContextTools(main_run)
    review_tools = GuardedContextTools(review_run)
    metadata = {
        "enabled": True,
        "configured": _configured_context(spec),
        "initialization": initialization,
        "asset_registration": asset_registration,
        "asset_context_unit_ids": [record.id for record in asset_records],
        "execution_run_id": execution_run_id,
    }
    return (
        [main_tools.search_context_units, main_tools.load_context_units, main_tools.context_debug],
        [review_tools.search_context_units, review_tools.load_context_units, review_tools.context_debug],
        metadata,
        main_run,
        runtime,
    )


def _source_capabilities(spec: Any) -> tuple[list[Any], list[Any], list[dict[str, Any]]]:
    # Separate providers preserve per-actor read budgets while exposing the same catalog.
    main_provider = ProjectSourceFileProvider(spec)
    review_provider = ProjectSourceFileProvider(spec)
    catalog = list(main_provider.list_files())
    if not catalog:
        return [], [], []
    main = create_source_retrieval_tools(main_provider) + create_source_search_tools(main_provider)
    review = create_source_retrieval_tools(review_provider) + create_source_search_tools(review_provider)
    # Paths are useful to humans but not needed by the model; file_key is the stable tool input.
    public_catalog = [
        {
            **{key: value for key, value in item.items() if key != "path"},
            "access": "source tools only; this key is not a ContextUnit ID",
        }
        for item in catalog
    ]
    return main, review, public_catalog


def _context_store_capabilities(spec: Any, trace: Any) -> list[Any]:
    """Read-only, current-trace access to existing LLM/tool audit records."""
    project_id = str(getattr(spec, "project_id", "") or "")
    trace_id = str(getattr(trace, "trace_id", "") or "")

    def list_current_context_records(**_kwargs: Any):
        from .context_store import load_contexts_by_trace
        from impl.tools.protocol import ToolResult

        records = load_contexts_by_trace(project_id, trace_id)
        items = [
            {
                "record_id": record.record_id,
                "caller": record.caller,
                "created_at": record.created_at,
                "prompt_size": record.prompt_size,
                "error": record.error,
            }
            for record in records
        ]
        return ToolResult(
            tool_id="context_store.list_current",
            tool_type="context_store",
            status="succeeded" if items else "inconclusive",
            actual={"trace_id": trace_id, "records": items},
            evidence=f"listed {len(items)} Context Store records for the current trace only",
        )

    def load_current_context_record(**kwargs: Any):
        from .context_store import load_contexts_by_trace
        from impl.tools.protocol import ToolResult

        record_id = str(kwargs.get("record_id") or "")
        records = load_contexts_by_trace(project_id, trace_id)
        record = next((item for item in records if item.record_id == record_id), None)
        if record is None:
            return ToolResult(
                tool_id="context_store.load_current",
                tool_type="context_store",
                status="failed",
                error=f"record is not available in current trace: {record_id}",
            )
        payload = to_dict(record)
        messages = list(payload.get("messages") or [])
        payload["messages"] = messages[-30:]
        return ToolResult(
            tool_id="context_store.load_current",
            tool_type="context_store",
            status="succeeded",
            actual=payload,
            evidence=f"loaded Context Store record {record_id} from the current trace",
            boundary_limits=["only the current verifier trace is accessible", "at most the last 30 messages are returned"],
        )

    list_current_context_records.__name__ = "context_store_list_current"
    load_current_context_record.__name__ = "context_store_load_current"
    return build_agno_tools([
        VerifiableTool(
            tool_id="context_store.list_current",
            description="列出当前 trace 已有的 Context Store 调用审计记录，返回 record_id、caller、时间、prompt_size 和 error。只用于发现当前 case 的原始 LLM/Tool 记录，不会搜索其他 case。",
            applicable_scenario="attr",
            parameters={},
            execute_fn=list_current_context_records,
        ),
        VerifiableTool(
            tool_id="context_store.load_current",
            description="按 list_current 返回的精确 record_id 读取当前 trace 的 LLM/Tool 消息审计。返回内容只证明 verifier/agent 发送、接收和调用了什么，不是业务系统内部 trace。",
            applicable_scenario="attr",
            parameters={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "必填。context_store_list_current 返回的当前 trace 精确 record_id。"},
                },
                "required": ["record_id"],
            },
            execute_fn=load_current_context_record,
        ),
    ])


@dataclass
class AttributeExecutionEnvironment:
    main_common_tools: list[Any] = field(default_factory=list)
    review_common_tools: list[Any] = field(default_factory=list)
    source_file_catalog: list[dict[str, Any]] = field(default_factory=list)
    context_status: dict[str, Any] = field(default_factory=dict)
    main_context_run: Any = None
    context_runtime: Any = None
    trace: Any = None
    execution_run_id: str = ""
    registration_errors: list[dict[str, str]] = field(default_factory=list)
    last_context: dict[str, Any] = field(default_factory=dict)

    def _clear_resolved_registration_errors(self, material: str, *stages: str) -> None:
        """Keep the audit fail-closed, but do not report a later-resolved exact material as failed."""
        stage_set = set(stages)
        self.registration_errors[:] = [
            item
            for item in self.registration_errors
            if not (
                item.get("material") == material
                and item.get("stage") in stage_set
            )
        ]

    def _register_dynamic_materials(self, materials: Mapping[str, Any]) -> list[dict[str, str]]:
        if self.context_runtime is None:
            return []
        catalog = []
        for name, value in materials.items():
            if value in (None, "", [], {}):
                continue
            try:
                content = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError) as exc:
                self.registration_errors.append({
                    "material": str(name),
                    "stage": "material_serialization",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                    "attempts": "1",
                })
                continue
            digest = hashlib.sha256(content.encode()).hexdigest()[:16]
            unit_id = f"attribute-{getattr(self.trace, 'trace_id', '')}-{name}-{digest}"
            description = f"当前 case 的 {name} 原始执行材料；只证明该检查或探针实际返回的内容。"
            try:
                record = ContextUnitRecord(
                    id=unit_id,
                    name=f"Attribute {name}",
                    description=description,
                    content=content,
                    content_ref=None,
                    project_id=str(getattr(self.trace, "project_id", "") or ""),
                    scope="case",
                    roles=("attribute",),
                    unit_type=name,
                    source_type="runtime_result",
                    tags={
                        "trace_id": str(getattr(self.trace, "trace_id", "") or ""),
                        "case_id": str(getattr(self.trace, "case_id", "") or ""),
                        "run_id": self.execution_run_id,
                    },
                )
            except ContextValidationError as exc:
                self.registration_errors.append({
                    "material": str(name),
                    "stage": "context_unit_validation",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                    "attempts": "1",
                })
                continue
            try:
                self.context_runtime.register_context_unit(record)
            except Exception as exc:
                failure = {
                    "material": str(name),
                    "stage": "context_unit_registration",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                    "attempts": "1",
                }
                self.registration_errors.append(failure)
                continue
            self._clear_resolved_registration_errors(str(name), "context_unit_registration")
            catalog.append({"id": unit_id, "name": f"Attribute {name}", "description": description})
        return catalog

    def _contextualize_verifiable_tools(self, tools: Iterable[VerifiableTool], actor: str) -> list[Any]:
        wrapped: list[VerifiableTool] = []
        for tool in tools:
            execute = tool.execute_fn
            if execute is None:
                raise ValueError(f"VerifiableTool.execute_fn is required: {tool.tool_id}")

            def execute_and_register(_execute=execute, _tool=tool, **kwargs: Any):
                result = _execute(**kwargs)
                catalog = self._register_dynamic_materials({
                    f"{actor}_tool_{_tool.tool_id.replace('.', '_')}": to_dict(result),
                })
                if catalog:
                    context_unit_id = catalog[0]["id"]
                    # The tool result itself has just exposed the complete registered
                    # material to the actor. Record it as investigated so Finalization
                    # can independently reload it without requiring a duplicate Load.
                    if actor == "main" and self.main_context_run is not None:
                        try:
                            self.main_context_run.load_context_units([context_unit_id])
                            self._clear_resolved_registration_errors(
                                f"{actor}_tool_{_tool.tool_id.replace('.', '_')}",
                                "context_unit_investigation_load",
                            )
                        except Exception as exc:
                            self.registration_errors.append({
                                "material": f"{actor}_tool_{_tool.tool_id.replace('.', '_')}",
                                "stage": "context_unit_investigation_load",
                                "error_type": type(exc).__name__,
                                "reason": str(exc),
                                "attempts": "1",
                            })
                    outputs = getattr(result, "outputs", None)
                    if isinstance(outputs, dict):
                        outputs["context_unit_id"] = context_unit_id
                    actual = getattr(result, "actual", None)
                    if isinstance(actual, dict):
                        actual.setdefault("context_unit_id", context_unit_id)
                else:
                    outputs = getattr(result, "outputs", None)
                    if isinstance(outputs, dict):
                        outputs["evidence_registration_error"] = dict(self.registration_errors[-1])
                return result

            wrapped.append(VerifiableTool(
                tool_id=tool.tool_id,
                description=tool.description + " 完整结果会自动注册为 ContextUnit，并记录为本轮已调查材料；无需重复 Load。",
                applicable_scenario=tool.applicable_scenario,
                parameters=tool.parameters,
                execute_fn=execute_and_register,
            ))
        return build_agno_tools(wrapped)

    def _finalize_tool(self, state: dict[str, Any]):
        def finalize_attribution():
            if self.main_context_run is None:
                raise ValueError("ContextUnit runtime is not configured")
            round_number = int(state.get("context", {}).get("_attribute_round") or 1)
            if state.get("successful_round") == round_number:
                raise ValueError("Finalization already succeeded in this Attribute round")
            before = self.main_context_run.debug_snapshot()["context_debug"]
            requested = sorted(set(before.get("loaded_ids") or []))
            if not requested:
                raise ValueError("Finalization requires at least one investigated ContextUnit")
            load_limit = int((before.get("policy") or {}).get("load_limit") or len(requested))
            content_char_budget = int(
                (before.get("policy") or {}).get("content_char_budget") or 100_000
            )
            units = []
            for offset in range(0, len(requested), load_limit):
                chunk = self.main_context_run.load_context_units(requested[offset:offset + load_limit])
                units.extend(chunk)
            serialized_units = [
                {"id": unit.id, "name": unit.name, "description": unit.description, "content": unit.content}
                for unit in units
            ]
            serialized_content_chars = len(json.dumps(serialized_units, ensure_ascii=False))
            if serialized_content_chars > content_char_budget:
                raise ValueError(
                    "Finalization serialized content size "
                    f"{serialized_content_chars} exceeds policy budget {content_char_budget}"
                )
            after = self.main_context_run.debug_snapshot()["context_debug"]
            state["successful_round"] = round_number
            state["finalized_ids"] = [unit.id for unit in units]
            state["content_hashes"] = dict(after.get("content_hashes") or {})
            return serialized_units

        finalize_attribution.__name__ = "finalize_attribution"
        return finalize_attribution

    def _review_bundle(self, tool_catalog: list[dict[str, str]]):
        def build(result: Any) -> dict[str, Any]:
            cited_ids = list(dict.fromkeys(
                str(evidence.location)
                for finding in getattr(result, "findings", []) or []
                for evidence in getattr(finding, "evidence", []) or []
                if str(getattr(evidence, "location", "") or "")
            ))
            snapshot = self.main_context_run.debug_snapshot()["context_debug"]
            load_limit = int((snapshot.get("policy") or {}).get("load_limit") or len(cited_ids) or 1)
            cited_units = []
            for offset in range(0, len(cited_ids), load_limit):
                cited_units.extend(
                    self.main_context_run.load_context_units(cited_ids[offset:offset + load_limit])
                )
            return {
                "cited_evidence_context_units": [
                    {"context_unit_id": unit.id, "name": unit.name, "description": unit.description, "content": unit.content}
                    for unit in cited_units
                ],
                "available_context_units": list(self.main_context_run.context_unit_catalog()),
                "available_tools": tool_catalog,
                "available_source_resources": list(self.source_file_catalog),
            }
        return build

    def _materializer(self, state: dict[str, Any]):
        def materialize(raw_findings: list[Any], failed_ids: list[str]) -> list[AttributionFinding]:
            finalized_ids = set(state.get("finalized_ids") or [])
            if raw_findings and not finalized_ids:
                raise ValueError("findings require one successful finalize_attribution call")
            allowed = set(failed_ids)
            seen_findings: set[str] = set()
            result: list[AttributionFinding] = []
            for raw in raw_findings:
                if not isinstance(raw, Mapping):
                    raise ValueError("finding must be an object")
                finding_id = str(raw.get("finding_id") or "").strip()
                conclusion = str(raw.get("conclusion") or "").strip()
                affected = list(dict.fromkeys(str(item) for item in raw.get("affected_expectation_ids") or [] if str(item)))
                if not finding_id or finding_id in seen_findings or not conclusion or not affected:
                    raise ValueError("finding_id, unique identity, conclusion and affected_expectation_ids are required")
                if not set(affected).issubset(allowed):
                    raise ValueError(f"finding references non-failed expectations: {set(affected) - allowed}")
                evidence_refs = []
                for index, selection in enumerate(raw.get("evidence") or [], start=1):
                    if not isinstance(selection, Mapping):
                        raise ValueError("finding evidence must contain context_unit_id and reason")
                    unit_id = str(selection.get("context_unit_id") or "").strip()
                    reason = str(selection.get("reason") or "").strip()
                    if unit_id not in finalized_ids or not reason:
                        raise ValueError(f"evidence must reference a finalized ContextUnit with a reason: {unit_id}")
                    entry = self.context_runtime.registry.get(unit_id)
                    if entry is None:
                        raise ValueError(f"ContextUnit disappeared before evidence materialization: {unit_id}")
                    record = entry["record"]
                    source_hash = str(entry.get("source_hash") or "")
                    if source_hash != str((state.get("content_hashes") or {}).get(unit_id) or ""):
                        raise ValueError(f"ContextUnit content changed during Finalization: {unit_id}")
                    digest = hashlib.sha256(f"{finding_id}:{unit_id}:{index}".encode()).hexdigest()[:16]
                    evidence_refs.append(EvidenceRef(
                        ref_id=f"attribute-evidence-{digest}",
                        source="context_unit",
                        kind=record.unit_type,
                        stage=f"attribute-round-{state.get('successful_round')}-finalization",
                        summary=reason,
                        location=unit_id,
                        payload=None,
                        metadata={
                            "context_source_type": record.source_type,
                            "source_hash": source_hash,
                            "trace_id": str(getattr(self.trace, "trace_id", "") or ""),
                            "case_id": str(getattr(self.trace, "case_id", "") or ""),
                            "attribute_session_id": state["session_id"],
                            "executor_run_id": self.execution_run_id,
                            "reason_source": "attribute",
                        },
                    ))
                if not evidence_refs:
                    raise ValueError(f"finding has no finalized evidence: {finding_id}")
                result.append(AttributionFinding(finding_id, affected, conclusion, evidence_refs))
                seen_findings.add(finding_id)
            return result
        return materialize

    def assemble(self, project_context: Optional[dict[str, Any]]) -> dict[str, Any]:
        context = dict(project_context or {})
        context.setdefault("finalization_prompt_char_budget", ATTRIBUTE_FINALIZATION_PROMPT_CHAR_BUDGET)
        context.setdefault("review_prompt_char_budget", ATTRIBUTE_REVIEW_PROMPT_CHAR_BUDGET)
        state = {
            "context": context,
            "session_id": self.execution_run_id,
            "successful_round": 0,
            "finalized_ids": [],
            "content_hashes": {},
        }
        raw_project_tools = list(context.get("tools") or [])
        project_verifiable = [tool for tool in raw_project_tools if isinstance(tool, VerifiableTool)]
        project_other = [tool for tool in raw_project_tools if not isinstance(tool, VerifiableTool)]
        main_project_tools = [*self._contextualize_verifiable_tools(project_verifiable, "main"), *normalize_attribute_tools(project_other)]
        finalize_tool = self._finalize_tool(state)
        context["tools"] = _deduplicate_tools([*self.main_common_tools, *main_project_tools])
        tool_catalog = [
            {"name": _tool_name(tool), "description": str(getattr(tool, "description", None) or getattr(tool, "__doc__", None) or "")}
            for tool in context["tools"]
        ]
        context["_attribute_review_enabled"] = True
        context["_attribute_tool_audit"] = []
        context["_attribute_review_audit"] = []
        context["_attribute_materialize_findings"] = self._materializer(state)
        context["_attribute_finalize"] = finalize_tool
        context["_attribute_review_bundle"] = self._review_bundle(tool_catalog)
        context["_attribute_register_dynamic_materials"] = self._register_dynamic_materials
        context["evidence_registration_errors"] = self.registration_errors
        state["context"] = context
        if self.source_file_catalog:
            context["source_file_catalog"] = self.source_file_catalog
        context["context_unit_status"] = dict(self.context_status)
        self.last_context = context
        return context


def build_attribute_environment(
    spec: Any,
    trace: Any,
    *,
    embedding_provider: Any = None,
) -> AttributeExecutionEnvironment:
    main_context, review_context, context_status, main_run, runtime = _build_context_tools(
        spec, trace, embedding_provider=embedding_provider
    )
    main_source, review_source, catalog = _source_capabilities(spec)
    audit_tools = _context_store_capabilities(spec, trace)
    registration_errors: list[dict[str, str]] = []
    source_wrapper = AttributeExecutionEnvironment(
        context_runtime=runtime,
        main_context_run=main_run,
        trace=trace,
        execution_run_id=str(context_status.get("execution_run_id") or ""),
        registration_errors=registration_errors,
    )
    return AttributeExecutionEnvironment(
        main_common_tools=[*main_context, *source_wrapper._contextualize_verifiable_tools(main_source, "main"), *audit_tools],
        review_common_tools=[*review_context, *source_wrapper._contextualize_verifiable_tools(review_source, "review"), *audit_tools],
        source_file_catalog=catalog,
        context_status=context_status,
        main_context_run=main_run,
        context_runtime=runtime,
        trace=trace,
        execution_run_id=str(context_status.get("execution_run_id") or ""),
        registration_errors=registration_errors,
    )
