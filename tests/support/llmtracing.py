"""llmtracing 采集形态的最小离线 trace（两次模型调用、一次工具调用）。"""
from impl.core.schema import RunTrace


def make_trace(provider='llmtracing'):
    system = {'role': 'system', 'content': 'Only report known device state.'}
    user = {'role': 'user', 'content': 'Check device A.'}
    response = {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'tool-1', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{}'}}]}
    result = {'role': 'tool', 'tool_call_id': 'tool-1', 'content': 'state unknown'}
    calls = [{'call_id': 'a', 'pre': {'protocol': 'chat_completions', 'messages': [system, user]},
              'outcome': {'event': 'success', 'response': {'choices': [{'message': response}]}}},
             {'call_id': 'b', 'pre': {'protocol': 'chat_completions', 'messages': [system, user, response, result]},
              'outcome': {'event': 'success', 'response': {'choices': [{'message': {
                  'role': 'assistant', 'content': 'state unknown'}}]}}}]
    snapshot = {'provider': provider, 'status': 'succeeded', 'records': {'calls': calls}}
    return RunTrace(trace_id='local-case', project_id='llm_probe', case_id='case',
                    normalized_request={'capability_ref': 'insurance-llmtracing', 'body': {'message': 'Check device A.'}},
                    raw_response={'answer': 'state unknown'}, extracted_output={'output_text': 'state unknown'},
                    project_fields={'business_trace': snapshot})
