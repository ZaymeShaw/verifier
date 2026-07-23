from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from impl.tools.protocol import ToolResult, VerifiableTool, build_agno_tools

from .schema import InvestigationManifest, load_investigation_manifest, validate_investigation_manifest
from .schema.investigation_trace import (
    TRACE_GRAPH_SUFFIX,
    load_trace_graph,
    trace_graph_basename,
    validate_trace_graph,
)
from .path_contract import LogicalPathRef, PathContractError, PathResolver, PathRoots


_MERMAID_HEADER = re.compile(r"^(?:flowchart|graph)\s+(?:TB|TD|BT|RL|LR)\b")
_MERMAID_NODE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*(?:\[|\(|\{|-->|---)")
_PATH_LIKE_KINDS = {"source", "document", "trace", "replay", "test", "function"}
_REVISION_KEYS = {"source_revision", "revision", "commit", "sha256", "content_hash"}
_ATTRIBUTE_TRACE_SECTIONS = (
    "## How to use this trace map",
    "## Operational index",
    "## Investigation procedure",
)


def validate_investigation_package(
    package_dir: Path,
    *,
    project_root: Path,
    expected_project_id: str = "",
    expected_role: str = "",
    role_contract_root: Optional[Path] = None,
    execute_tools: bool = False,
    tool_module_overrides: Optional[Mapping[str, Path]] = None,
    tool_test_inputs: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    source_root: Optional[Path] = None,
    expected_source_revision: str = "",
) -> Dict[str, Any]:
    if tool_test_inputs is not None and not execute_tools:
        raise ValueError("tool_test_inputs requires execute_tools=True")
    package = Path(package_dir).resolve()
    project = Path(project_root).resolve()
    source = Path(source_root).resolve() if source_root else None
    _assert_under(package, project, "investigation package")
    if source is not None and not source.is_dir():
        raise FileNotFoundError(f"business source repository not found: {source}")
    manifest_path = package / "manifest.json"
    overview_path = package / "overview.md"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"investigation manifest not found: {manifest_path}")
    if not overview_path.is_file() or not overview_path.read_text(encoding="utf-8").strip():
        raise ValueError(f"investigation overview is missing or empty: {overview_path}")

    manifest = load_investigation_manifest(manifest_path)
    validate_investigation_manifest(manifest)
    detected_revision = str(expected_source_revision or "").strip()
    if source is not None and not detected_revision:
        detected_revision = detect_source_revision(source)
    if detected_revision and manifest.source_revision != detected_revision:
        raise ValueError(
            "investigation source_revision does not match the configured business source repository: "
            f"manifest={manifest.source_revision}, current={detected_revision}"
        )
    if expected_project_id and manifest.project_id != expected_project_id:
        raise ValueError(
            f"manifest project_id {manifest.project_id!r} does not match expected {expected_project_id!r}"
        )
    if expected_role and manifest.role != expected_role:
        raise ValueError(f"manifest role {manifest.role!r} does not match expected {expected_role!r}")
    if package.name != manifest.role:
        raise ValueError(f"investigation directory {package.name!r} must match manifest role {manifest.role!r}")

    if role_contract_root is not None:
        role_contract = Path(role_contract_root) / manifest.role / "ROLE.md"
        if not role_contract.is_file():
            raise FileNotFoundError(f"Draft role contract not found: {role_contract}")

    artifact_paths: list[str] = []
    artifact_by_relative: Dict[str, Path] = {}
    mermaid_nodes: Dict[str, list[str]] = {}
    trace_artifacts: list[tuple[str, Path]] = []
    for relative_ref, _purpose in _manifest_artifacts(manifest):
        if isinstance(relative_ref, LogicalPathRef):
            artifact = _resolve_logical_ref(
                relative_ref,
                package=package,
                project=project,
                source=source,
                field_path="InvestigationArtifactRef.location",
                expected_type="file",
            )
            relative = relative_ref.location
        else:
            relative = relative_ref
            artifact = _resolve_relative(package, relative, project, "artifact")
        if not artifact.is_file():
            raise FileNotFoundError(f"investigation artifact not found: {artifact}")
        artifact_paths.append(str(artifact))
        normalized_relative = Path(relative).as_posix()
        artifact_by_relative[normalized_relative] = artifact
        if artifact.name.endswith(TRACE_GRAPH_SUFFIX):
            trace_artifacts.append((normalized_relative, artifact))
        if artifact.suffix == ".mmd":
            nodes = _validate_mermaid(artifact)
            mermaid_nodes[str(artifact)] = nodes
            if manifest.role == "attribute":
                companion = artifact.with_suffix(".md")
                if not companion.is_file():
                    raise FileNotFoundError(f"Attribute Mermaid companion document not found: {companion}")
                companion_text = companion.read_text(encoding="utf-8")
                missing = [node for node in nodes if not _documents_node(companion_text, node)]
                if missing:
                    raise ValueError(
                        f"Attribute Mermaid nodes missing from {companion.name}: {', '.join(missing)}"
                    )
                missing_sections = [
                    heading
                    for heading in _ATTRIBUTE_TRACE_SECTIONS
                    if heading not in companion_text
                ]
                if missing_sections:
                    raise ValueError(
                        f"Attribute trace companion lacks operational sections in {companion.name}: "
                        + ", ".join(missing_sections)
                    )
                operational_index = _markdown_section(
                    companion_text,
                    "## Operational index",
                )
                unindexed = [
                    node
                    for node in nodes
                    if not re.search(
                        rf"(?<![A-Za-z0-9_-]){re.escape(node)}(?![A-Za-z0-9_-])",
                        operational_index,
                    )
                ]
                if unindexed:
                    raise ValueError(
                        f"Attribute Mermaid nodes missing from Operational index in {companion.name}: "
                        + ", ".join(unindexed)
                    )

    for relative, artifact in tuple(artifact_by_relative.items()):
        if artifact.suffix != ".mmd":
            continue
        sidecar = artifact.with_name(f"{artifact.stem}{TRACE_GRAPH_SUFFIX}")
        sidecar_relative = Path(relative).with_name(sidecar.name).as_posix()
        if sidecar.is_file() and sidecar_relative not in artifact_by_relative:
            raise ValueError(
                f"TraceGraph sidecar exists but is not registered in "
                f"InvestigationManifest.artifacts: {sidecar_relative}"
            )

    trace_graphs: Dict[str, Dict[str, Any]] = {}
    evidence_ids = {str(evidence.ref_id) for evidence in _all_evidence(manifest)}
    tool_ids = {str(requirement.tool_id) for requirement in manifest.tool_requirements}
    for relative, artifact in trace_artifacts:
        graph = load_trace_graph(artifact)
        validate_trace_graph(
            graph,
            evidence_ref_ids=evidence_ids,
            tool_requirement_ids=tool_ids,
        )
        graph_basename = trace_graph_basename(artifact)
        if graph.graph_id != graph_basename:
            raise ValueError(
                f"TraceGraph.graph_id must match artifact basename: "
                f"path={relative}, graph_id={graph.graph_id!r}, expected={graph_basename!r}"
            )
        sidecar_path = Path(relative)
        mmd_relative = sidecar_path.with_name(f"{graph_basename}.mmd").as_posix()
        md_relative = sidecar_path.with_name(f"{graph_basename}.md").as_posix()
        mmd_path = artifact_by_relative.get(mmd_relative)
        md_path = artifact_by_relative.get(md_relative)
        if mmd_path is None:
            raise FileNotFoundError(
                f"TraceGraph Mermaid companion is not registered in InvestigationManifest.artifacts: "
                f"{mmd_relative}"
            )
        if md_path is None:
            raise FileNotFoundError(
                f"TraceGraph Markdown companion is not registered in InvestigationManifest.artifacts: "
                f"{md_relative}"
            )
        _validate_trace_companions(graph, mmd_path=mmd_path, md_path=md_path)
        if graph.graph_id in trace_graphs:
            raise ValueError(f"duplicate TraceGraph.graph_id in investigation artifacts: {graph.graph_id}")
        trace_graphs[graph.graph_id] = {
            "artifact": str(artifact),
            "mermaid": str(mmd_path),
            "markdown": str(md_path),
            "nodes": [node.node_id for node in graph.nodes],
            "data_ids": [data.data_id for node in graph.nodes for data in node.outputs],
        }

    evidence_files: list[str] = []
    for evidence in _all_evidence(manifest):
        if not any(str(evidence.metadata.get(key) or "").strip() for key in _REVISION_KEYS):
            raise ValueError(f"EvidenceRef lacks source revision/hash metadata: {evidence.ref_id}")
        located = _resolve_evidence_location(
            evidence,
            package,
            project,
            source_root=source,
        )
        if located is not None:
            if source is not None and located.is_relative_to(source):
                evidence_revision = str(
                    evidence.metadata.get("source_revision")
                    or evidence.metadata.get("revision")
                    or evidence.metadata.get("commit")
                    or ""
                ).strip()
                if not evidence_revision:
                    raise ValueError(
                        f"business-source EvidenceRef lacks source revision metadata: {evidence.ref_id}"
                    )
                if evidence_revision != manifest.source_revision:
                    raise ValueError(
                        f"EvidenceRef source revision differs from manifest: {evidence.ref_id}; "
                        f"evidence={evidence_revision}, manifest={manifest.source_revision}"
                    )
            _validate_evidence_integrity(evidence, located)
            evidence_files.append(str(located))

    tools = []
    implemented_tool_ids = {
        requirement.tool_id
        for requirement in manifest.tool_requirements
        if requirement.implementation is not None
    }
    if execute_tools and tool_test_inputs is not None:
        unknown_tool_ids = sorted(set(tool_test_inputs) - implemented_tool_ids)
        if unknown_tool_ids:
            raise ValueError(
                "Tool smoke inputs reference unknown or unimplemented tool_id: "
                + ", ".join(unknown_tool_ids)
            )
    for requirement in manifest.tool_requirements:
        if requirement.implementation is None:
            continue
        implementation = requirement.implementation
        module_path = _resolve_module_path(
            implementation.module_ref or implementation.module_path,
            package,
            project,
            overrides=tool_module_overrides,
        )
        tool = _load_tool(module_path, implementation.factory)
        if tool.tool_id != requirement.tool_id:
            raise ValueError(
                f"VerifiableTool.tool_id {tool.tool_id!r} does not match requirement {requirement.tool_id!r}"
            )
        if tool.description.strip() != requirement.description.strip():
            raise ValueError(f"VerifiableTool.description does not match requirement: {requirement.tool_id}")
        if tool.applicable_scenario.strip() != requirement.applicable_scenario.strip():
            raise ValueError(f"VerifiableTool.applicable_scenario does not match requirement: {requirement.tool_id}")
        if dict(tool.parameters or {}) != dict(requirement.parameters or {}):
            raise ValueError(f"VerifiableTool.parameters do not match requirement: {requirement.tool_id}")
        build_agno_tools([tool])
        execution = "not_requested"
        execution_count = 0
        argument_requirement = _argument_requirement(tool.parameters or {})
        if execute_tools:
            supplied_cases = None if tool_test_inputs is None else tool_test_inputs.get(tool.tool_id)
            if supplied_cases is None:
                if argument_requirement:
                    raise ValueError(
                        f"--execute-tools requires smoke inputs for {tool.tool_id}: "
                        f"{argument_requirement}"
                    )
                cases: Sequence[Mapping[str, Any]] = ({},)
            else:
                if not isinstance(supplied_cases, Sequence) or isinstance(supplied_cases, (str, bytes)):
                    raise TypeError(f"Tool smoke inputs must be a list of objects: {tool.tool_id}")
                if not supplied_cases:
                    raise ValueError(f"Tool smoke inputs cannot be empty: {tool.tool_id}")
                cases = supplied_cases
            for index, case in enumerate(cases, start=1):
                if not isinstance(case, Mapping):
                    raise TypeError(f"Tool smoke input must be an object: {tool.tool_id}[{index}]")
                try:
                    result = tool.execute_fn(**dict(case)) if tool.execute_fn is not None else None
                except Exception as exc:
                    raise RuntimeError(
                        f"VerifiableTool smoke execution raised: {tool.tool_id}[{index}]: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                if not isinstance(result, ToolResult):
                    raise TypeError(f"VerifiableTool must return ToolResult: {tool.tool_id}[{index}]")
                status = str(result.status or "").strip().lower()
                if status not in {"succeeded", "passed"}:
                    raise RuntimeError(
                        f"VerifiableTool smoke execution did not succeed: {tool.tool_id}[{index}]: "
                        f"status={status or '<empty>'}, error={result.error or '<none>'}"
                    )
                execution_count += 1
            execution = "succeeded"
        tools.append({
            "tool_id": tool.tool_id,
            "module_path": str(module_path),
            "execution": execution,
            "execution_count": execution_count,
            "module_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
        })

    return {
        "ok": True,
        "project_id": manifest.project_id,
        "role": manifest.role,
        "source_revision": manifest.source_revision,
        "manifest": str(manifest_path),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "source_root": str(source) if source is not None else "",
        "source_revision_verified": bool(detected_revision),
        "overview": str(overview_path),
        "artifacts": artifact_paths,
        "evidence_files": evidence_files,
        "mermaid_nodes": mermaid_nodes,
        "trace_graphs": trace_graphs,
        "tools": tools,
        "tool_execution_requested": execute_tools,
        "unresolved_reason": manifest.unresolved_reason,
    }


def load_role_investigation_tools(
    spec: Any,
    *,
    role: str,
    use_candidate: bool,
) -> list[VerifiableTool]:
    """Load implemented requirements through the Role's authoritative asset map.

    ToolImplementationRef keeps the stable production-relative module path. During
    Draft, RoleAssetMapping redirects that logical path to the candidate bytes, so
    Promote can move files without rewriting the investigation manifest.
    """
    from .project_loader import (
        resolve_project_package_root,
        resolve_project_source_root,
        resolve_role_assets,
    )

    if use_candidate:
        from .investigation_validation import require_investigation_validation_receipt

        require_investigation_validation_receipt(spec, role)

    selected = resolve_role_assets(spec, role, use_candidate=use_candidate)
    tool_aliases = {
        str(item["mapping"].production_path): Path(item["path"])
        for item in selected
        if item["mapping"].kind == "tool" and item["available"]
    }
    packages = [
        Path(item["path"])
        for item in selected
        if item["mapping"].kind == "investigation" and item["available"]
    ]
    tools: list[VerifiableTool] = []
    seen: set[str] = set()
    for package in packages:
        manifest = load_investigation_manifest(package / "manifest.json")
        validate_investigation_package(
            package,
            project_root=resolve_project_package_root(spec),
            expected_project_id=spec.project_id,
            expected_role=role,
            tool_module_overrides=tool_aliases,
            source_root=(resolve_project_source_root(spec) if spec.has_business_source else None),
        )
        for requirement in manifest.tool_requirements:
            implementation = requirement.implementation
            if implementation is None:
                continue
            module_key = (
                str(implementation.module_ref.prefixed_path)
                if implementation.module_ref is not None
                else implementation.module_path
            )
            if module_key not in tool_aliases:
                raise ValueError(
                    "implemented ToolRequirement is not enabled by role_assets: "
                    f"{module_key}"
                )
            tool = _load_tool(tool_aliases[module_key], implementation.factory)
            if tool.tool_id in seen:
                raise ValueError(f"duplicate investigation Tool ID for role={role}: {tool.tool_id}")
            seen.add(tool.tool_id)
            tools.append(tool)
    return tools


def _argument_requirement(parameters: Mapping[str, Any]) -> str:
    required = [str(item) for item in parameters.get("required") or [] if str(item)]
    if required:
        return ",".join(required)
    for keyword in ("anyOf", "oneOf"):
        alternatives = []
        for branch in parameters.get(keyword) or []:
            if not isinstance(branch, Mapping):
                continue
            branch_required = [str(item) for item in branch.get("required") or [] if str(item)]
            if branch_required:
                alternatives.append("+".join(branch_required))
        if alternatives:
            return f"{keyword}({'|'.join(alternatives)})"
    if int(parameters.get("minProperties") or 0) > 0:
        return f"minProperties={int(parameters['minProperties'])}"
    return ""


def _all_evidence(manifest: InvestigationManifest) -> Iterable[Any]:
    yield from manifest.evidence_refs
    for requirement in manifest.tool_requirements:
        yield from requirement.evidence_refs


def _resolve_relative(package: Path, value: str, project: Path, label: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path must be relative to the investigation package: {value}")
    resolved = (package / relative).resolve()
    _assert_under(resolved, package, label)
    _assert_under(resolved, project, label)
    return resolved


def _assert_under(path: Path, root: Path, label: str) -> None:
    if not path.is_relative_to(root):
        raise ValueError(f"{label} escapes allowed root {root}: {path}")


def _validate_mermaid(path: Path) -> list[str]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines or not _MERMAID_HEADER.match(lines[0].strip()):
        raise ValueError(f"unsupported or missing Mermaid flow header: {path}")
    nodes = []
    for line in lines[1:]:
        match = _MERMAID_NODE.match(line)
        if match and match.group(1) not in nodes:
            nodes.append(match.group(1))
    if not nodes:
        raise ValueError(f"Mermaid flow contains no stable node IDs: {path}")
    return nodes


def _documents_node(text: str, node_id: str) -> bool:
    return bool(re.search(rf"(?im)^##\s+Node:\s*`?{re.escape(node_id)}`?\b", text))


def _validate_trace_companions(graph: Any, *, mmd_path: Path, md_path: Path) -> None:
    mermaid_text = mmd_path.read_text(encoding="utf-8")
    markdown_text = md_path.read_text(encoding="utf-8")
    mermaid_nodes = set(_validate_mermaid(mmd_path))
    graph_nodes = {node.node_id for node in graph.nodes}
    if mermaid_nodes != graph_nodes:
        raise ValueError(
            f"TraceGraph and Mermaid node IDs differ for {graph.graph_id}: "
            f"missing_in_mermaid={sorted(graph_nodes - mermaid_nodes)}, "
            f"missing_in_trace={sorted(mermaid_nodes - graph_nodes)}"
        )

    graph_edge_pairs = {(edge.source_node_id, edge.target_node_id) for edge in graph.edges}
    mermaid_edge_pairs = _mermaid_edge_pairs(mermaid_text, graph_nodes)
    if mermaid_edge_pairs != graph_edge_pairs:
        raise ValueError(
            f"TraceGraph and Mermaid edges differ for {graph.graph_id}: "
            f"missing_in_mermaid={sorted(graph_edge_pairs - mermaid_edge_pairs)}, "
            f"missing_in_trace={sorted(mermaid_edge_pairs - graph_edge_pairs)}"
        )

    operational_index = _markdown_section(markdown_text, "## Operational index")
    missing_nodes = [node_id for node_id in sorted(graph_nodes) if not _documents_identifier(operational_index, node_id)]
    if missing_nodes:
        raise ValueError(
            f"TraceGraph nodes missing from Operational index in {md_path.name}: "
            + ", ".join(missing_nodes)
        )
    data_ids = [data.data_id for node in graph.nodes for data in node.outputs]
    missing_data = [data_id for data_id in data_ids if not _documents_identifier(operational_index, data_id)]
    if missing_data:
        raise ValueError(
            f"TraceData IDs missing from Operational index in {md_path.name}: "
            + ", ".join(missing_data)
        )

    lines_by_pair = _mermaid_edge_lines(mermaid_text, graph_nodes)
    for edge in graph.edges:
        lines = lines_by_pair.get((edge.source_node_id, edge.target_node_id), [])
        if not any(any(data_id in line for data_id in edge.transferred_data_ids) for line in lines):
            raise ValueError(
                f"TraceEdge Mermaid label must include at least one transferred_data_id: "
                f"{graph.graph_id}:{edge.source_node_id}->{edge.target_node_id}"
            )


def _documents_identifier(text: str, identifier: str) -> bool:
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(identifier)}(?![A-Za-z0-9_.-])",
            text,
        )
    )


def _mermaid_edge_pairs(text: str, node_ids: set[str]) -> set[tuple[str, str]]:
    return set(_mermaid_edge_lines(text, node_ids))


def _mermaid_edge_lines(text: str, node_ids: set[str]) -> Dict[tuple[str, str], list[str]]:
    result: Dict[tuple[str, str], list[str]] = {}
    ordered = sorted(node_ids, key=len, reverse=True)
    for line in text.splitlines():
        if not any(token in line for token in ("-->", "---", ".->")):
            continue
        present = [
            node_id
            for node_id in ordered
            if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(node_id)}(?![A-Za-z0-9_-])", line)
        ]
        if len(present) < 2:
            continue
        positions = sorted((line.find(node_id), node_id) for node_id in present)
        pair = (positions[0][1], positions[-1][1])
        result.setdefault(pair, []).append(line)
    return result


def _markdown_section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    body_start = start + len(heading)
    next_heading = re.search(r"(?m)^##\s+", text[body_start:])
    body_end = body_start + next_heading.start() if next_heading else len(text)
    return text[body_start:body_end]


def _resolve_evidence_location(
    evidence: Any,
    package: Path,
    project: Path,
    *,
    source_root: Optional[Path],
) -> Optional[Path]:
    kind = str(evidence.kind)
    location = str(evidence.location or "")
    if evidence.location_ref is not None:
        return _resolve_logical_ref(
            evidence.location_ref,
            package=package,
            project=project,
            source=source_root,
            field_path=f"EvidenceRef.{evidence.ref_id}.location",
            expected_type="file",
        )
    if not location or kind not in _PATH_LIKE_KINDS:
        return None
    file_part = location.split(":", 1)[0] if kind == "function" else location
    candidate = Path(file_part)
    if candidate.is_absolute():
        if not candidate.is_file():
            raise FileNotFoundError(f"EvidenceRef location not found: {candidate}")
        resolved = candidate.resolve()
        allowed_roots = [project, *([source_root] if source_root is not None else [])]
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            raise ValueError(
                "EvidenceRef absolute path is outside the verifier project and configured "
                f"business source repository: {resolved}"
            )
        return resolved
    candidates = [(package / candidate).resolve(), (project / candidate).resolve()]
    if source_root is not None:
        candidates.append((source_root / candidate).resolve())
    existing = [item for item in candidates if item.is_file()]
    if len(existing) > 1 and existing[0] != existing[1]:
        raise ValueError(f"ambiguous EvidenceRef location base: {location}")
    if existing:
        return existing[0]
    raise FileNotFoundError(f"EvidenceRef location not found under package or project: {location}")


def detect_source_revision(source_root: Path) -> str:
    """Return the checked-out Git revision for the configured business source repository."""
    source = Path(source_root).resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot inspect business source revision: {source}: {exc}") from exc
    revision = result.stdout.strip() if result.returncode == 0 else ""
    if not revision:
        raise ValueError(
            "configured business source repository has no readable Git revision: "
            f"{source}: {result.stderr.strip() or 'git rev-parse failed'}"
        )
    return revision


def _validate_evidence_integrity(evidence: Any, path: Path) -> None:
    expected_hash = str(
        evidence.metadata.get("sha256")
        or evidence.metadata.get("content_hash")
        or ""
    ).strip()
    if expected_hash:
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"EvidenceRef content hash changed: {evidence.ref_id}; "
                f"expected={expected_hash}, actual={actual_hash}"
            )
    symbol = (
        evidence.location_ref.symbol
        if evidence.location_ref is not None
        else evidence.location.split(":", 1)[1].strip()
        if evidence.kind == "function" and ":" in evidence.location
        else ""
    )
    if evidence.kind == "function" and symbol:
        leaf = symbol.rsplit(".", 1)[-1]
        if not leaf or not re.search(
            rf"(?m)^\s*(?:async\s+def|def|class)\s+{re.escape(leaf)}\b",
            path.read_text(encoding="utf-8"),
        ):
            raise ValueError(f"EvidenceRef function symbol not found: {evidence.ref_id}: {symbol}")


def _resolve_module_path(
    value: str | LogicalPathRef,
    package: Path,
    project: Path,
    *,
    overrides: Optional[Mapping[str, Path]] = None,
) -> Path:
    if isinstance(value, LogicalPathRef):
        for key in (value.location, str(value.prefixed_path)):
            if overrides and key in overrides:
                resolved = Path(overrides[key]).resolve()
                _assert_under(resolved, project, "ToolImplementationRef.module_ref")
                if not resolved.is_file():
                    raise FileNotFoundError(f"Tool module override not found: {resolved}")
                return resolved
        return _resolve_logical_ref(
            value,
            package=package,
            project=project,
            source=None,
            field_path="ToolImplementationRef.module_ref",
            expected_type="file",
        )
    if overrides and value in overrides:
        resolved = Path(overrides[value]).resolve()
        _assert_under(resolved, project, "ToolImplementationRef.module_path")
        if not resolved.is_file():
            raise FileNotFoundError(f"Tool module override not found: {resolved}")
        return resolved
    relative = Path(value)
    if relative.is_absolute():
        resolved = relative.resolve()
        _assert_under(resolved, project, "ToolImplementationRef.module_path")
        if not resolved.is_file():
            raise FileNotFoundError(f"Tool module not found: {resolved}")
        return resolved
    candidates = [(package / relative).resolve(), (project / relative).resolve()]
    candidates = [item for item in candidates if item.is_relative_to(project) and item.is_file()]
    unique = list(dict.fromkeys(candidates))
    if not unique:
        raise FileNotFoundError(f"Tool module not found under package or project: {value}")
    if len(unique) > 1:
        raise ValueError(f"ambiguous ToolImplementationRef.module_path base: {value}")
    return unique[0]


def _manifest_artifacts(manifest: Any):
    for relative, purpose in manifest.artifacts.items():
        yield relative, purpose
    for artifact in manifest.artifact_refs:
        yield artifact.location, artifact.purpose


def _resolve_logical_ref(
    reference: LogicalPathRef,
    *,
    package: Path,
    project: Path,
    source: Optional[Path],
    field_path: str,
    expected_type: str,
) -> Path:
    verifier_repo = project.parents[2] if len(project.parents) >= 3 else project
    roots = PathRoots(
        verifier_repo=verifier_repo,
        business_source=source,
        project_package=project,
        artifact_package=package,
    )
    try:
        return reference.resolve(
            PathResolver(roots),
            field_path=field_path,
            expected_type=expected_type,
        ).physical
    except PathContractError as exc:
        raise ValueError(str(exc)) from exc


def _load_tool(module_path: Path, factory_name: str) -> VerifiableTool:
    digest = hashlib.sha256(str(module_path).encode("utf-8")).hexdigest()[:12]
    module_spec = importlib.util.spec_from_file_location(f"investigation_tool_{digest}", module_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"cannot import Tool module: {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    factory = getattr(module, factory_name, None)
    if not callable(factory):
        raise TypeError(f"Tool factory is missing or not callable: {module_path}:{factory_name}")
    tool = factory()
    if not isinstance(tool, VerifiableTool):
        raise TypeError(f"Tool factory must return VerifiableTool: {module_path}:{factory_name}")
    return tool
