"""直接测 _extract_tool_call_log 在真实 agno result 上能不能工作。"""
import sys
sys.path.insert(0, '/Users/xiaozijian/WorkSpace/projects/claude_code/verifier-branch/verifier')
from impl.core.llm_client import _extract_tool_call_log, LlmClient, project_llm_client
from impl.core.project_loader import load_project, load_adapter
from impl.tools.source_retrieval import ProjectSourceFileProvider, create_source_file_search_tool
from impl.core.attribute import ATTRIBUTE_TOOL_CALL_LIMIT

spec = load_project('client_search')
adapter = load_adapter(spec)
src = ProjectSourceFileProvider(spec, None)
src.list_files()
tool = create_source_file_search_tool(src)
vts = adapter.get_verifiable_tools()
tools = [tool]
for vt in vts:
    if vt.execute_fn is not None:
        fn = vt.execute_fn
        fn.__name__ = vt.tool_id.replace(".", "_")
        if not getattr(fn, "__doc__", None):
            fn.__doc__ = vt.description
        tools.append(fn)

print("tools:", [t.__name__ for t in tools])

client = project_llm_client(spec, role="attribute", knowledge=None, tools=tools, tool_call_limit=ATTRIBUTE_TOOL_CALL_LIMIT)

system = "你是测试 agent。请调用 search_source_file 工具读取文件 'project_adapter:adapter.py'，然后用一句话总结。"
user = "调用 search_source_file(file_key='project_adapter:adapter.py')，读取后总结。"

result = client.complete_json(system, user, trace_id="test-tcl-extract")
print("result keys:", list(result.keys()) if isinstance(result, dict) else type(result))
print("_tool_call_log in result:", "_tool_call_log" in result)
tcl = result.get("_tool_call_log", [])
print("tool_call_log count:", len(tcl))
for e in tcl:
    print("  tool:", e.get("tool_name"))
    print("    args:", str(e.get("arguments"))[:100])
    print("    result:", str(e.get("result"))[:100])
