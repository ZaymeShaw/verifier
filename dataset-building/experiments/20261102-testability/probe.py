"""Run frozen read-only probes; append immutable responses for inspection."""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent
MCP_ROOT = Path('/Users/xiaozijian/WorkSpace/package/insurance_qa_agent/insurance-tools-mcp')
ALLOWED = {'product_knowledge', 'benefit_info', 'general_qa', 'policy_search', 'customer_search'}

async def main():
    plan = json.loads((ROOT / 'probe-plan.json').read_text())
    selected = set(sys.argv[1:])
    if selected:
        plan = [p for p in plan if p['probe_id'] in selected]
    env = {**os.environ, 'ENV_TYPE': 'dev', 'ITOOLS_AGENT_ID': 'pi',
           'ITOOLS_USER_ID': '1050900009', 'ITOOLS_EMPNO': '1050900009',
           'ITOOLS_AGENTNO': '1050900009', 'PYTHONDONTWRITEBYTECODE': '1'}
    params = StdioServerParameters(command=str(MCP_ROOT / '.venv/bin/python'),
                                   args=['-m', 'itools'], cwd=str(MCP_ROOT), env=env)
    with (ROOT / 'probe-stderr.log').open('a') as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                (ROOT / 'tool-schema.json').write_text(listed.model_dump_json(indent=2))
                sem = asyncio.Semaphore(3)
                async def run(p):
                    target = ROOT / 'evidence' / (p['probe_id'] + '.json')
                    if target.exists():
                        return
                    assert p['tool'] in ALLOWED
                    async with sem:
                        start = time.monotonic()
                        row = {**p, 'started_utc': datetime.now(timezone.utc).isoformat()}
                        try:
                            result = await asyncio.wait_for(session.call_tool(p['tool'], p['arguments']), 90)
                            row['response'] = result.model_dump(mode='json')
                        except Exception as exc:
                            row['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
                        row['elapsed_s'] = round(time.monotonic() - start, 3)
                        target.write_text(json.dumps(row, ensure_ascii=False, indent=2))
                        print(json.dumps({'probe': p['probe_id'], 'elapsed_s': row['elapsed_s'],
                                          'exception': row.get('exception', {}).get('type')}, ensure_ascii=False), flush=True)
                await asyncio.gather(*(run(p) for p in plan))

if __name__ == '__main__':
    asyncio.run(main())
