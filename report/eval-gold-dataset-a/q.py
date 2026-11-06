"""只读查数据源（起草 gold 时独立取证用）。用法：python q.py <tool> '<json 参数>'
只放行 5 个只读工具；结果按参数缓存到 facts-cache/，同一查询不重复打远程。"""
import asyncio, hashlib, json, os, sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent
MCP_ROOT = Path('/Users/xiaozijian/WorkSpace/package/insurance_qa_agent/insurance-tools-mcp')
ALLOWED = {'product_knowledge', 'benefit_info', 'general_qa', 'policy_search', 'customer_search', 'policy_detail', 'customer_detail'}


async def main(tool, args):
    assert tool in ALLOWED, f'只读工具白名单：{sorted(ALLOWED)}'
    cache = HERE / 'facts-cache' / (tool + '-' + hashlib.md5(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12] + '.json')
    if cache.exists():
        print(cache.read_text()); return
    env = {**os.environ, 'ENV_TYPE': 'dev', 'ITOOLS_AGENT_ID': 'pi',
           'ITOOLS_USER_ID': '1050900009', 'ITOOLS_EMPNO': '1050900009', 'ITOOLS_AGENTNO': '1050900009',
           'PYTHONDONTWRITEBYTECODE': '1'}
    params = StdioServerParameters(command=str(MCP_ROOT / '.venv/bin/python'), args=['-m', 'itools'], cwd=str(MCP_ROOT), env=env)
    with open(os.devnull, 'w') as err:
        async with stdio_client(params, errlog=err) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await asyncio.wait_for(s.call_tool(tool, args), 90)
    text = '\n'.join(c.text for c in res.content if getattr(c, 'text', None))
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(text)
    print(text)

if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], json.loads(sys.argv[2])))
