"""Observe this replay without making model requests or changing runtime state."""
import collections
import datetime
import json
from pathlib import Path
import time
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
if len(sys.argv) > 1:
    time.sleep(int(sys.argv[1]))
manifest = json.loads((OUT / 'manifest.json').read_text())
run = manifest['run_id']
cursor = OUT / 'observation-offsets.json'
offsets = json.loads(cursor.read_text()) if cursor.exists() else manifest['gateway_offsets']
new_rows = []
for relative, offset in offsets.items():
    path = ROOT / relative
    if not path.exists():
        continue
    with path.open('rb') as stream:
        stream.seek(offset if path.stat().st_size >= offset else 0)
        while True:
            position = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.endswith(b'\n'):
                stream.seek(position)
                break
            if run.encode() not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('run_id') == run:
                new_rows.append(row)
        offsets[relative] = stream.tell()
with (OUT / 'gateway-events.jsonl').open('a') as stream:
    for row in new_rows:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
cursor.write_text(json.dumps(offsets, indent=2) + '\n')
rows = [json.loads(line) for line in (OUT / 'gateway-events.jsonl').read_text().splitlines()]
rows.sort(key=lambda x: x['ts'])
contexts = []
for path in sorted((OUT / 'contexts').rglob('*.json')):
    ctx = json.loads(path.read_text())
    runtime = (ctx.get('response') or {}).get('runtime') or {}
    contexts.append({'file': str(path.relative_to(OUT)), 'stage': runtime.get('stage'),
                     'elapsed_ms': ctx.get('elapsed_ms'), 'prompt_chars': ctx.get('prompt_size'),
                     'error': str(ctx.get('error') or '')[:600]})
summary = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'events': dict(collections.Counter(r['event'] for r in rows)),
           'contexts': contexts,
           'recent': [{k: r.get(k) for k in ('event', 'ts', 'call_id', 'stage', 'gateway', 'latency_ms')}
                      for r in rows[-6:]]}
if (OUT / 'summary.json').exists():
    summary['result'] = json.loads((OUT / 'summary.json').read_text())
(OUT / 'observation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({**summary, 'context_count': len(contexts), 'contexts': contexts[-4:]}, ensure_ascii=False, indent=2))
