from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .base import to_dict


TRACE_GRAPH_SUFFIX = ".trace.json"


@dataclass
class TraceData:
    data_id: str
    description: str
    schema_ref: str = ""
    evidence_ref_ids: list[str] = field(default_factory=list)
    tool_requirement_ids: list[str] = field(default_factory=list)
    observation_gap: str = ""

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceData":
        return cls(
            data_id=str(value.get("data_id") or ""),
            description=str(value.get("description") or ""),
            schema_ref=str(value.get("schema_ref") or ""),
            evidence_ref_ids=_string_list(value.get("evidence_ref_ids"), "TraceData.evidence_ref_ids"),
            tool_requirement_ids=_string_list(
                value.get("tool_requirement_ids"),
                "TraceData.tool_requirement_ids",
            ),
            observation_gap=str(value.get("observation_gap") or ""),
        )


@dataclass
class TraceNode:
    node_id: str
    responsibility: str
    input_data_ids: list[str]
    outputs: list[TraceData]
    evidence_ref_ids: list[str]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceNode":
        raw_outputs = value.get("outputs") or []
        if not isinstance(raw_outputs, list):
            raise TypeError("TraceNode.outputs must be a list")
        return cls(
            node_id=str(value.get("node_id") or ""),
            responsibility=str(value.get("responsibility") or ""),
            input_data_ids=_string_list(value.get("input_data_ids"), "TraceNode.input_data_ids"),
            outputs=[TraceData.from_dict(_mapping(item, "TraceNode.outputs item")) for item in raw_outputs],
            evidence_ref_ids=_string_list(value.get("evidence_ref_ids"), "TraceNode.evidence_ref_ids"),
        )


@dataclass
class TraceEdge:
    source_node_id: str
    target_node_id: str
    transferred_data_ids: list[str]
    condition: str = ""
    evidence_ref_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceEdge":
        return cls(
            source_node_id=str(value.get("source_node_id") or ""),
            target_node_id=str(value.get("target_node_id") or ""),
            transferred_data_ids=_string_list(
                value.get("transferred_data_ids"),
                "TraceEdge.transferred_data_ids",
            ),
            condition=str(value.get("condition") or ""),
            evidence_ref_ids=_string_list(value.get("evidence_ref_ids"), "TraceEdge.evidence_ref_ids"),
        )


@dataclass
class TraceGraph:
    graph_id: str
    scope: str
    nodes: list[TraceNode]
    edges: list[TraceEdge]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceGraph":
        raw_nodes = value.get("nodes") or []
        raw_edges = value.get("edges") or []
        if not isinstance(raw_nodes, list):
            raise TypeError("TraceGraph.nodes must be a list")
        if not isinstance(raw_edges, list):
            raise TypeError("TraceGraph.edges must be a list")
        return cls(
            graph_id=str(value.get("graph_id") or ""),
            scope=str(value.get("scope") or ""),
            nodes=[TraceNode.from_dict(_mapping(item, "TraceGraph.nodes item")) for item in raw_nodes],
            edges=[TraceEdge.from_dict(_mapping(item, "TraceGraph.edges item")) for item in raw_edges],
        )

    def as_dict(self) -> dict[str, Any]:
        return to_dict(self)


def load_trace_graph(path: Path) -> TraceGraph:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return TraceGraph.from_dict(_mapping(raw, "TraceGraph document"))


def dump_trace_graph(graph: TraceGraph, path: Path) -> None:
    Path(path).write_text(
        json.dumps(graph.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def trace_graph_basename(path: Path) -> str:
    name = Path(path).name
    if not name.endswith(TRACE_GRAPH_SUFFIX):
        raise ValueError(f"TraceGraph artifact must end with {TRACE_GRAPH_SUFFIX}: {path}")
    return name[: -len(TRACE_GRAPH_SUFFIX)]


def validate_trace_graph(
    graph: TraceGraph,
    *,
    evidence_ref_ids: Iterable[str],
    tool_requirement_ids: Iterable[str],
) -> None:
    if not graph.graph_id.strip():
        raise ValueError("TraceGraph.graph_id is required")
    if not graph.scope.strip():
        raise ValueError(f"TraceGraph.scope is required: {graph.graph_id}")
    if not graph.nodes:
        raise ValueError(f"TraceGraph.nodes cannot be empty: {graph.graph_id}")

    known_evidence = {str(item) for item in evidence_ref_ids}
    known_tools = {str(item) for item in tool_requirement_ids}
    nodes: dict[str, TraceNode] = {}
    data_producers: dict[str, str] = {}

    for node in graph.nodes:
        if not node.node_id.strip():
            raise ValueError(f"TraceNode.node_id is required: {graph.graph_id}")
        if node.node_id in nodes:
            raise ValueError(f"duplicate TraceNode.node_id: {graph.graph_id}:{node.node_id}")
        if not node.responsibility.strip():
            raise ValueError(f"TraceNode.responsibility is required: {graph.graph_id}:{node.node_id}")
        if not node.outputs:
            raise ValueError(f"TraceNode.outputs cannot be empty: {graph.graph_id}:{node.node_id}")
        _validate_refs(
            node.evidence_ref_ids,
            known_evidence,
            f"TraceNode.evidence_ref_ids: {graph.graph_id}:{node.node_id}",
        )
        nodes[node.node_id] = node
        for data in node.outputs:
            if not data.data_id.strip():
                raise ValueError(f"TraceData.data_id is required: {graph.graph_id}:{node.node_id}")
            if data.data_id in data_producers:
                raise ValueError(
                    f"duplicate TraceData.data_id: {graph.graph_id}:{data.data_id}; "
                    f"producers={data_producers[data.data_id]},{node.node_id}"
                )
            if not data.description.strip():
                raise ValueError(f"TraceData.description is required: {graph.graph_id}:{data.data_id}")
            _validate_refs(
                data.evidence_ref_ids,
                known_evidence,
                f"TraceData.evidence_ref_ids: {graph.graph_id}:{data.data_id}",
            )
            _validate_refs(
                data.tool_requirement_ids,
                known_tools,
                f"TraceData.tool_requirement_ids: {graph.graph_id}:{data.data_id}",
                required=False,
            )
            data_producers[data.data_id] = node.node_id

    for node in graph.nodes:
        for data_id in node.input_data_ids:
            if data_id not in data_producers:
                raise ValueError(
                    f"TraceNode.input_data_ids references unknown TraceData: "
                    f"{graph.graph_id}:{node.node_id}:{data_id}"
                )

    seen_edges: set[tuple[str, str, tuple[str, ...], str]] = set()
    for index, edge in enumerate(graph.edges):
        edge_label = f"{graph.graph_id}:edges[{index}]"
        if edge.source_node_id not in nodes:
            raise ValueError(f"TraceEdge.source_node_id is unknown: {edge_label}:{edge.source_node_id}")
        if edge.target_node_id not in nodes:
            raise ValueError(f"TraceEdge.target_node_id is unknown: {edge_label}:{edge.target_node_id}")
        if not edge.transferred_data_ids:
            raise ValueError(f"TraceEdge.transferred_data_ids cannot be empty: {edge_label}")
        _validate_refs(edge.evidence_ref_ids, known_evidence, f"TraceEdge.evidence_ref_ids: {edge_label}")
        identity = (
            edge.source_node_id,
            edge.target_node_id,
            tuple(edge.transferred_data_ids),
            edge.condition,
        )
        if identity in seen_edges:
            raise ValueError(f"duplicate TraceEdge: {edge_label}")
        seen_edges.add(identity)

        source = nodes[edge.source_node_id]
        target = nodes[edge.target_node_id]
        source_available = set(source.input_data_ids) | {item.data_id for item in source.outputs}
        target_inputs = set(target.input_data_ids)
        for data_id in edge.transferred_data_ids:
            if data_id not in data_producers:
                raise ValueError(f"TraceEdge references unknown TraceData: {edge_label}:{data_id}")
            if data_id not in source_available:
                raise ValueError(f"TraceEdge source does not produce or receive data: {edge_label}:{data_id}")
            if data_id not in target_inputs:
                raise ValueError(f"TraceEdge target does not consume data: {edge_label}:{data_id}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{label} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise TypeError(f"{label}[{index}] must be a non-empty string")
        result.append(item)
    return result


def _validate_refs(values: list[str], known: set[str], label: str, *, required: bool = True) -> None:
    if required and not values:
        raise ValueError(f"{label} cannot be empty")
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"{label} references unknown IDs: {', '.join(unknown)}")
