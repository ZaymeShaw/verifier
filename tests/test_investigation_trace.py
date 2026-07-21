from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from impl.core.investigation import _validate_trace_companions, validate_investigation_package
from impl.core.schema import EvidenceRef, InvestigationManifest, ToolRequirement, dump_investigation_manifest
from impl.core.schema.investigation_trace import (
    TraceData,
    TraceEdge,
    TraceGraph,
    TraceNode,
    dump_trace_graph,
    load_trace_graph,
    validate_trace_graph,
)


def _graph() -> TraceGraph:
    return TraceGraph(
        graph_id="main",
        scope="A request enters the parser and produces business conditions.",
        nodes=[
            TraceNode(
                node_id="INPUT",
                responsibility="Accept the business query.",
                input_data_ids=[],
                outputs=[TraceData(
                    data_id="request.query",
                    description="The original business query.",
                    evidence_ref_ids=["flow-source"],
                )],
                evidence_ref_ids=["flow-source"],
            ),
            TraceNode(
                node_id="CORE",
                responsibility="Convert the query into business conditions.",
                input_data_ids=["request.query"],
                outputs=[TraceData(
                    data_id="core.conditions",
                    description="Conditions produced by the parser core.",
                    evidence_ref_ids=["flow-source"],
                    tool_requirement_ids=["demo.replay"],
                )],
                evidence_ref_ids=["flow-source"],
            ),
        ],
        edges=[TraceEdge(
            source_node_id="INPUT",
            target_node_id="CORE",
            transferred_data_ids=["request.query"],
            evidence_ref_ids=["flow-source"],
        )],
    )


def test_trace_graph_json_round_trip_and_reference_validation(tmp_path: Path):
    path = tmp_path / "main.trace.json"
    original = _graph()

    dump_trace_graph(original, path)
    loaded = load_trace_graph(path)
    validate_trace_graph(
        loaded,
        evidence_ref_ids={"flow-source"},
        tool_requirement_ids={"demo.replay"},
    )

    assert loaded == original


def test_trace_graph_rejects_duplicate_data_and_unknown_references():
    graph = _graph()
    graph.nodes[1].outputs[0].data_id = "request.query"
    with pytest.raises(ValueError, match="duplicate TraceData.data_id"):
        validate_trace_graph(
            graph,
            evidence_ref_ids={"flow-source"},
            tool_requirement_ids={"demo.replay"},
        )

    graph = _graph()
    graph.nodes[1].input_data_ids = ["missing.data"]
    with pytest.raises(ValueError, match="unknown TraceData"):
        validate_trace_graph(
            graph,
            evidence_ref_ids={"flow-source"},
            tool_requirement_ids={"demo.replay"},
        )

    graph = _graph()
    graph.nodes[1].outputs[0].tool_requirement_ids = ["missing.tool"]
    with pytest.raises(ValueError, match="unknown IDs: missing.tool"):
        validate_trace_graph(
            graph,
            evidence_ref_ids={"flow-source"},
            tool_requirement_ids={"demo.replay"},
        )


def test_trace_graph_rejects_duplicate_nodes_edges_and_unknown_evidence():
    graph = _graph()
    graph.nodes.append(deepcopy(graph.nodes[0]))
    with pytest.raises(ValueError, match="duplicate TraceNode.node_id"):
        validate_trace_graph(
            graph,
            evidence_ref_ids={"flow-source"},
            tool_requirement_ids={"demo.replay"},
        )

    graph = _graph()
    graph.edges.append(deepcopy(graph.edges[0]))
    with pytest.raises(ValueError, match="duplicate TraceEdge"):
        validate_trace_graph(
            graph,
            evidence_ref_ids={"flow-source"},
            tool_requirement_ids={"demo.replay"},
        )

    graph = _graph()
    graph.nodes[1].outputs[0].evidence_ref_ids = ["invented-source"]
    with pytest.raises(ValueError, match="unknown IDs: invented-source"):
        validate_trace_graph(
            graph,
            evidence_ref_ids={"flow-source"},
            tool_requirement_ids={"demo.replay"},
        )


def test_trace_graph_rejects_edges_that_do_not_match_data_flow():
    graph = _graph()
    graph.edges[0].transferred_data_ids = ["core.conditions"]
    with pytest.raises(ValueError, match="source does not produce or receive data"):
        validate_trace_graph(
            graph,
            evidence_ref_ids={"flow-source"},
            tool_requirement_ids={"demo.replay"},
        )

    graph = _graph()
    graph.nodes[1].input_data_ids = []
    with pytest.raises(ValueError, match="target does not consume data"):
        validate_trace_graph(
            graph,
            evidence_ref_ids={"flow-source"},
            tool_requirement_ids={"demo.replay"},
        )


def test_investigation_validator_loads_registered_trace_sidecar(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "attribute"
    traces = package / "docs" / "traces"
    traces.mkdir(parents=True)
    (package / "overview.md").write_text("# Investigation\n", encoding="utf-8")
    (traces / "main.mmd").write_text(
        "flowchart LR\n"
        "  INPUT[Business input]\n"
        "  CORE[Parser core]\n"
        "  INPUT -->|request.query| CORE\n",
        encoding="utf-8",
    )
    (traces / "main.md").write_text(
        "# Flow\n\n"
        "## How to use this trace map\nStart from the business request.\n\n"
        "## Operational index\n"
        "| Node | Input data IDs | Output data IDs | Observe or verify | Boundary |\n"
        "|---|---|---|---|---|\n"
        "| INPUT | - | request.query | flow-source | Request only |\n"
        "| CORE | request.query | core.conditions | demo.replay | Parser only |\n\n"
        "## Investigation procedure\nFollow INPUT to CORE.\n\n"
        "## Node: INPUT\nAccepts the query.\n\n"
        "## Node: CORE\nBuilds conditions.\n",
        encoding="utf-8",
    )
    dump_trace_graph(_graph(), traces / "main.trace.json")
    dump_investigation_manifest(
        InvestigationManifest(
            schema_version=1,
            project_id="demo",
            role="attribute",
            source_revision="abc123",
            evidence_refs=[EvidenceRef(
                ref_id="flow-source",
                kind="document",
                location="docs/traces/main.md",
                metadata={"source_revision": "abc123"},
            )],
            tool_requirements=[ToolRequirement(
                tool_id="demo.replay",
                description="Replay the parser core.",
                applicable_scenario="attribute",
                parameters={"type": "object", "properties": {}},
                implementation=None,
                implementation_gap="The replay is not implemented in this fixture.",
            )],
            artifacts={
                "docs/traces/main.mmd": "business flow",
                "docs/traces/main.md": "operational guide",
                "docs/traces/main.trace.json": "structured trace sidecar",
            },
        ),
        package / "manifest.json",
    )

    result = validate_investigation_package(
        package,
        project_root=tmp_path,
        expected_project_id="demo",
        expected_role="attribute",
    )

    assert result["trace_graphs"]["main"]["nodes"] == ["INPUT", "CORE"]
    assert result["trace_graphs"]["main"]["data_ids"] == ["request.query", "core.conditions"]


def test_trace_sidecar_must_be_registered_with_companions(tmp_path: Path):
    package = tmp_path / "draft" / "investigation" / "attribute"
    traces = package / "docs" / "traces"
    traces.mkdir(parents=True)
    (package / "overview.md").write_text("# Investigation\n", encoding="utf-8")
    (traces / "main.mmd").write_text("flowchart LR\n  INPUT[Input]\n", encoding="utf-8")
    (traces / "main.md").write_text(
        "# Flow\n\n"
        "## How to use this trace map\nStart at INPUT.\n\n"
        "## Operational index\n| Node | Verify |\n|---|---|\n| INPUT | request |\n\n"
        "## Investigation procedure\nInspect INPUT.\n\n"
        "## Node: INPUT\nInput boundary.\n",
        encoding="utf-8",
    )
    dump_trace_graph(_graph(), traces / "main.trace.json")
    dump_investigation_manifest(
        InvestigationManifest(
            schema_version=1,
            project_id="demo",
            role="attribute",
            source_revision="abc123",
            artifacts={
                "docs/traces/main.mmd": "business flow",
                "docs/traces/main.md": "operational guide",
            },
        ),
        package / "manifest.json",
    )

    with pytest.raises(ValueError, match="sidecar exists but is not registered"):
        validate_investigation_package(package, project_root=tmp_path)


def test_trace_companions_reject_structural_conflicts(tmp_path: Path):
    mmd = tmp_path / "main.mmd"
    md = tmp_path / "main.md"
    md.write_text(
        "## Operational index\n"
        "| Node | Output |\n|---|---|\n"
        "| INPUT | request.query |\n| CORE | core.conditions |\n",
        encoding="utf-8",
    )
    mmd.write_text(
        "flowchart LR\n  INPUT[Input]\n  WRONG[Wrong]\n  INPUT -->|request.query| WRONG\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="TraceGraph and Mermaid node IDs differ"):
        _validate_trace_companions(_graph(), mmd_path=mmd, md_path=md)

    mmd.write_text(
        "flowchart LR\n  INPUT[Input]\n  CORE[Core]\n  INPUT -->|query payload| CORE\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="label must include at least one transferred_data_id"):
        _validate_trace_companions(_graph(), mmd_path=mmd, md_path=md)
