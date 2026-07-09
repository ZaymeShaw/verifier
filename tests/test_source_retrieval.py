import pytest
from types import SimpleNamespace

from impl.tools import ToolResult, VerifiableTool, build_agno_tools
from impl.tools.source_retrieval import ProjectSourceFileProvider, create_source_retrieval_tools


def _provider(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text("def wanted():\n    return 'ok'\n\ndef other():\n    return 'large'\n", encoding="utf-8")
    spec = SimpleNamespace(root=str(tmp_path), documents={"source_sample": "sample.py"}, adapter=None, application={}, endpoint_discovery={})
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
