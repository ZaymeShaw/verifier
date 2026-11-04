"""Second-stage repeat: retain bounded HTTP JSON before tool projection."""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MCP_ROOT = Path('/Users/xiaozijian/WorkSpace/package/insurance_qa_agent/insurance-tools-mcp')
sys.path.insert(0, str(MCP_ROOT))
os.chdir(MCP_ROOT)
os.environ.update(ENV_TYPE='dev', ITOOLS_AGENT_ID='pi', ITOOLS_USER_ID='1050900009',
                  ITOOLS_EMPNO='1050900009', ITOOLS_AGENTNO='1050900009')
from app.tools.real import http

original_post = http.post_json
calls = []

def scrub(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if any(s in k.lower() for s in ('token', 'secret', 'password', 'authorization', 'api_key'))
                else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value

async def record_post(client, url, payload, *, timeout_s):
    # Do not record headers or authentication traffic; leave requests unchanged.
    allowed = urlsplit(url).hostname in {'8.148.158.241', '43.139.190.73', '211.161.232.13'}
    row = {'url': url, 'request': scrub(payload)} if allowed else None
    try:
        result = await original_post(client, url, payload, timeout_s=timeout_s)
        if row is not None:
            row['response'] = scrub(result)
        return result
    except Exception as exc:
        if row is not None:
            row['exception'] = type(exc).__name__
        raise
    finally:
        if row is not None:
            calls.append(row)

http.post_json = record_post
from itools.dispatch import dispatch
from itools.identity import identity_from_env
from itools.runtime import build_backend_runtime_for_process

async def main():
    output = ROOT / 'stage2'
    output.mkdir(exist_ok=True)
    plan = json.loads((ROOT / 'probe-plan.json').read_text())
    selected = {'p06', 'p11', 'p12', 'p14'}
    runtime, _ = await build_backend_runtime_for_process()
    try:
        for p in plan:
            if p['probe_id'] not in selected:
                continue
            target = output / (p['probe_id'] + '.json')
            if target.exists():
                continue
            calls.clear()
            start = time.monotonic()
            row = {**p, 'started_utc': datetime.now(timezone.utc).isoformat()}
            try:
                result = await asyncio.wait_for(dispatch(p['tool'], p['arguments'],
                    identity=identity_from_env(), backend_client=runtime.client), 90)
                row['envelope'] = json.loads(result)
            except Exception as exc:
                row['exception'] = type(exc).__name__
            row['http_calls'] = list(calls)
            row['elapsed_s'] = round(time.monotonic() - start, 3)
            target.write_text(json.dumps(row, ensure_ascii=False, indent=2))
            print(p['probe_id'], row.get('envelope', {}).get('status'), len(calls), flush=True)
    finally:
        await runtime.aclose()

asyncio.run(main())
