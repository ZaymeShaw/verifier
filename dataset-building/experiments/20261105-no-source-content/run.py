"""One frozen batch; credentials stay in memory. No source lookups or data deletion."""
import getpass
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

HERE = Path(__file__).resolve().parent
BASE_URL = 'https://api.kimi.com/coding/v1'


def write_json(name, value):
    path = HERE / name
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main():
    if (HERE / 'raw-response.json').exists():
        raise RuntimeError('Existing run must not be overwritten')
    key = os.environ.get('KIMI_API_KEY') or getpass.getpass('Kimi API key (hidden): ')
    client = OpenAI(base_url=BASE_URL, api_key=key, timeout=300, max_retries=0)
    try:
        models = client.models.list()
        write_json('models.json', models.model_dump(mode='json'))
        print('Available model IDs:', ', '.join(m.id for m in models.data), flush=True)
        model = input('Exact model ID to use: ').strip()
        if not model:
            raise ValueError('Model must be specified')
        ping = client.chat.completions.create(model=model, messages=[{'role':'user','content':'Return only the word OK.'}], max_tokens=512, reasoning_effort='low')
        write_json('connectivity.json', ping.model_dump(mode='json'))
        if not (ping.choices[0].message.content or '').strip():
            raise RuntimeError('Connectivity probe returned no visible content')
        print('Connectivity OK; returned model:', ping.model, flush=True)
        sample = json.loads((HERE / 'sample.json').read_text(encoding='utf-8'))
        prompt = (HERE / 'prompt.txt').read_text(encoding='utf-8')
        payload = {
            'model': model,
            'messages': [
                {'role':'system','content':prompt},
                {'role':'user','content':json.dumps({'cases':[{'id':r['id'],'turns':r['turns']} for r in sample]},ensure_ascii=False)},
            ],
            'reasoning_effort':'high',
            'max_tokens':24000,
            'response_format':{'type':'json_object'},
        }
        write_json('request.json', payload)
        started = datetime.now(timezone.utc).isoformat()
        tick = time.monotonic()
        response = client.chat.completions.create(**payload)
        elapsed = round(time.monotonic() - tick, 3)
        write_json('raw-response.json', response.model_dump(mode='json'))
        if len(response.choices)!=1 or response.choices[0].finish_reason!='stop':
            raise ValueError('Incomplete completion; raw response retained, no labels emitted')
        result = json.loads(response.choices[0].message.content or '')
        if set(result)!={'items'} or not isinstance(result['items'],list):
            raise ValueError('Wrong response object shape')
        items = result['items']
        for item in items:
            if not isinstance(item,dict) or set(item)!={'id','verdict','reason'}:
                raise ValueError('Wrong item shape')
            if not isinstance(item['id'],str) or item['verdict'] not in {'确定不可测','不确定'}:
                raise ValueError('Invalid id or verdict')
            if not isinstance(item['reason'],str) or not item['reason'].strip():
                raise ValueError('Missing reason')
        expected = {r['id'] for r in sample}
        actual = [r['id'] for r in items]
        if len(actual)!=len(expected) or len(set(actual))!=len(actual) or set(actual)!=expected:
            raise ValueError('Missing, duplicate, or unexpected case IDs; no labels emitted')
        by_id = {item['id']:item for item in items}
        write_json('labels.json', [by_id[r['id']] for r in sample])
        write_json('run-summary.json', {
            'started_utc':started,'elapsed_s':elapsed,'base_url':BASE_URL,
            'requested_model':model,'returned_model':response.model,
            'condition':'all_source_contents_unavailable_to_evaluator',
            'counts':dict(Counter(r['verdict'] for r in items)),
            'usage':response.usage.model_dump(mode='json') if response.usage else None,
            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
            'sample_sha256':hashlib.sha256((HERE/'sample.json').read_bytes()).hexdigest(),
            'request_sha256':hashlib.sha256((HERE/'request.json').read_bytes()).hexdigest(),
            'ids_complete_unique':True,
        })
        print(json.dumps({'elapsed_s':elapsed,'counts':dict(Counter(r['verdict'] for r in items))},ensure_ascii=False),flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
