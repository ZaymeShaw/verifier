"""One bounded provider schema probe; no business execution, no endpoint fallback.

This is a synthetic tool-contract check, not an analysis-quality evaluation.
The actual six analysis tools are provided; no tool is executed by this script.
"""
import json
from pathlib import Path
import time

import httpx
from dotenv import dotenv_values
from openai import OpenAI

from impl.core.llm_tracing import trace_scope, trace_headers
from impl.projects.llm_probe.process_loop.analysis import Analysis
from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import _validate

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUN = 'analysis-submission-split-schema-20261007'
config = dotenv_values(ROOT / '.runtime/instances/inst-16fa340ac786414f/tracing/.env.verifier_primary')
# The empty dossier intentionally has no business facts or findings.
dossier = {'records': [], 'contents': {}, 'sources': [], 'gaps': [], 'coverage': [],
           'current': [], 'history': [], 'observed_at_collection': []}
analysis = Analysis(dossier, None)
request = {
    'model': config['UPSTREAM_MODEL'],
    'messages': [
        {'role': 'system', 'content': '这是空案卷的工具协议核验，不是业务评测。只调用 submit_structure。'},
        {'role': 'user', 'content': '案卷、已有环节表和发现均为空。提交 route=[]，coverage_note="空案卷协议核验"，existing_link_suspects=[]，new_link_suspects=[]。'},
    ],
    'tools': [{'type': 'function', 'function': {'name': tool.tool_id, 'description': tool.description,
                                              'parameters': tool.parameters}} for tool in analysis.loop.tools],
    'tool_choice': {'type': 'function', 'function': {'name': 'submit_structure'}},
    'reasoning_effort': 'low', 'max_tokens': 512, 'temperature': 0, 'stream': False,
}
(OUT / 'provider-probe-request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2) + '\n')
start = time.monotonic()
result = {'run_id': RUN, 'scope': 'synthetic empty-dossier schema probe, not semantic evaluation'}
try:
    with trace_scope(run_id=RUN, project_id='llm_probe', case_id='__schema_probe__',
                     execution_id=RUN + ':0', independent=True):
        with OpenAI(base_url='http://127.0.0.1:' + config['LITELLM_PORT'] + '/v1',
                    api_key=config['LITELLM_MASTER_KEY'], timeout=60, max_retries=0,
                    http_client=httpx.Client(timeout=60, trust_env=False),
                    default_headers=trace_headers(role='protocol_probe', stage='analysis_schema_probe', trace_id=RUN)) as client:
            response = client.chat.completions.create(**request)
    result['response'] = response.model_dump(mode='json')
    calls = response.choices[0].message.tool_calls or []
    if len(calls) != 1 or calls[0].function.name != 'submit_structure':
        raise ValueError('Expected exactly one submit_structure tool call')
    payload = json.loads(calls[0].function.arguments)
    _validate(payload, set())
    if payload['route'] or payload['existing_link_suspects'] or payload['new_link_suspects']:
        raise ValueError('Empty-dossier probe invented findings or route')
    result['status'] = 'accepted'
except Exception as exc:
    text = str(exc)
    for key, value in config.items():
        if 'KEY' in key and value:
            text = text.replace(value, '[REDACTED]')
    result.update(status='not_verified', error_type=type(exc).__name__,
                  http_status=getattr(exc, 'status_code', None), error=text[:2000])
result['elapsed_seconds'] = round(time.monotonic() - start, 3)
(OUT / 'provider-probe-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k != 'response'}, ensure_ascii=False))
