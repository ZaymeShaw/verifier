"""Read-only probes against the existing clause_kb; never writes ES."""
import json
from pathlib import Path
from impl.projects.llm_probe.eval_axes.sources.es_tools import EsTools

out = Path(__file__).resolve().parent
receipts = []
t = EsTools([{'source': 'es', 'uri': 'es://clause_kb'}], receipts)
cases = [
    ('default_product_substring', '康宁', None),
    ('explicit_keyword_substring', '康宁', ['product']),
    ('explicit_keyword_full', '康宁终身险', ['product']),
    ('explicit_title_substring', '犹豫', ['clause_title']),
    ('explicit_multifield_substring', '犹豫', ['clause_title.kw']),
    ('explicit_multifield_full', '犹豫期', ['clause_title.kw']),
    ('mixed_keywords', '鑫享至尊 犹豫期', None),
    ('absent', '现金价值', None),
    ('english_absent', 'cash value', None),
]
results = {name: {'query': query, 'fields': fields, 'response': t.es_search('clause_kb', query, fields)}
           for name, query, fields in cases}
corpus = t.client.search('clause_kb', {'size': 100, 'query': {'match_all': {}}})
reads = {}
for item in results.values():
    for hit in item['response'].get('hits', []):
        loc = hit['locator']
        if loc not in reads:
            reads[loc] = t.es_read('clause_kb', loc)
payload = {'results': results, 'corpus': corpus, 'reads': reads, 'receipts': receipts}
(out / 'es-field-probes.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
for name, item in results.items():
    response = item['response']
    print(name, len(response.get('hits', [])), response.get('error', ''), flush=True)
