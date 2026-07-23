import pytest

from impl.core.path_contract import PathResolver, PathRoots
from impl.core.schema import ProjectSpec
from impl.tools import ToolResult, VerifiableTool, build_agno_tools
from impl.tools.source_retrieval import (
    MAX_SOURCE_FULL_FILE_BYTES,
    ProjectSourceFileProvider,
    create_source_retrieval_tools,
)


def _spec(project_root, *, business_root=None, documents=None):
    business = business_root or project_root
    roots = PathRoots(
        verifier_repo=project_root.resolve(),
        business_source=business.resolve(),
        project_package=project_root.resolve(),
        knowledge_route=project_root.resolve(),
        artifact_package=project_root.resolve(),
    )
    document_values = dict(documents or {})
    return ProjectSpec(
        project_id="demo",
        name="demo",
        project={
            "resources": {
                "source": {"repository": "business://.", "paths": {}},
                "documents": {
                    key: f"project://{value}" for key, value in document_values.items()
                },
            }
        },
        verifier={"endpoint_discovery": {"source_roots": []}},
        path_roots=roots,
        path_resolver=PathResolver(roots),
    )


def _provider(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text("def wanted():\n    return 'ok'\n\ndef other():\n    return 'large'\n", encoding="utf-8")
    spec = _spec(tmp_path, documents={"source_sample": "sample.py"})
    return ProjectSourceFileProvider(spec)


def test_source_read_functions_requires_function_names_for_default_call(tmp_path):
    provider = _provider(tmp_path)
    read_tool = create_source_retrieval_tools(provider)[1].execute_fn
    file_key = provider.list_files()[0]["key"]

    result = read_tool(file_key=file_key)

    assert result.status == "inconclusive"
    assert "function_names is required" in result.error


def test_source_read_functions_returns_selected_python_functions(tmp_path):
    provider = _provider(tmp_path)
    read_tool = create_source_retrieval_tools(provider)[1].execute_fn
    file_key = provider.list_files()[0]["key"]

    result = read_tool(file_key=file_key, function_names=["wanted"])

    assert result.status == "succeeded"
    assert "# wanted" in result.actual["content"]
    assert "return 'ok'" in result.actual["content"]
    assert "return 'large'" not in result.actual["content"]


def test_source_read_full_file_rejects_oversized_material_and_points_to_bounded_search(tmp_path):
    source = tmp_path / "large-report.json"
    source.write_text("x" * (MAX_SOURCE_FULL_FILE_BYTES + 1), encoding="utf-8")
    spec = _spec(
        tmp_path,
        documents={"large_report": "large-report.json"},
    )
    provider = ProjectSourceFileProvider(spec)
    read_tool = create_source_retrieval_tools(provider)[1].execute_fn
    file_key = next(item["key"] for item in provider.list_files() if item["path"] == str(source))

    result = read_tool(file_key=file_key, full_file=True)

    assert result.status == "inconclusive"
    assert "full_file_too_large" in result.actual["content"]
    assert "source.search_text" in result.actual["content"]


def test_source_list_symbols_returns_python_function_summaries(tmp_path):
    provider = _provider(tmp_path)
    list_tool = create_source_retrieval_tools(provider)[0].execute_fn
    file_key = provider.list_files()[0]["key"]

    result = list_tool(file_key=file_key)

    assert result.status == "succeeded"
    assert [item["qualified_name"] for item in result.actual["symbols"]] == ["wanted", "other"]


def test_source_tools_expose_agno_function_names(tmp_path):
    provider = _provider(tmp_path)
    tools = build_agno_tools(create_source_retrieval_tools(provider))

    assert [tool.name for tool in tools] == ["source_list_symbols", "source_read_functions"]


def test_source_tools_expose_self_describing_schema(tmp_path):
    provider = _provider(tmp_path)
    tools = build_agno_tools(create_source_retrieval_tools(provider))

    for tool in tools:
        assert tool.description
        assert tool.parameters["type"] == "object"
        for name, schema in tool.parameters["properties"].items():
            assert schema.get("description"), f"{tool.name}.{name} missing description"

    read_tool = next(tool for tool in tools if tool.name == "source_read_functions")
    assert "fixed call order" not in read_tool.description
    assert "qualified_name" in read_tool.parameters["properties"]["function_names"]["description"]


def test_source_catalog_deduplicates_same_business_root_declared_twice(tmp_path):
    business_root = tmp_path / "business"
    business_root.mkdir()
    (business_root / "intent.py").write_text("def route():\n    return 'team'\n", encoding="utf-8")
    spec = _spec(tmp_path, business_root=business_root)

    catalog = ProjectSourceFileProvider(spec).list_files()

    business_entries = [item for item in catalog if item["path"] == str(business_root / "intent.py")]
    assert len(business_entries) == 1
    assert business_entries[0]["key"] == "source_project:intent.py"




def test_build_agno_tools_rejects_parameters_without_description():
    def execute(**kwargs):
        return ToolResult(tool_id="bad.tool")

    bad_tool = VerifiableTool(
        tool_id="bad.tool",
        description="bad tool with incomplete parameter schema",
        parameters={"type": "object", "properties": {"field": {"type": "string"}}, "required": ["field"]},
        execute_fn=execute,
    )

    with pytest.raises(ValueError, match="bad.tool.field"):
        build_agno_tools([bad_tool])


def test_build_agno_tools_normalizes_empty_parameters():
    def execute(**kwargs):
        return ToolResult(tool_id="no.params")

    tool = VerifiableTool(
        tool_id="no.params",
        description="self describing no-parameter tool",
        parameters={},
        execute_fn=execute,
    )

    [agno_tool] = build_agno_tools([tool])

    assert agno_tool.parameters == {"type": "object", "properties": {}, "required": []}


def test_build_agno_tools_rejects_missing_execute_function():
    tool = VerifiableTool(
        tool_id="missing.execute",
        description="declared but not executable",
        parameters={},
        execute_fn=None,
    )

    with pytest.raises(ValueError, match="missing.execute"):
        build_agno_tools([tool])
