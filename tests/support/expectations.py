"""Empty requirement material for tests focused on other protocol boundaries."""
import hashlib
import json


def content_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


E = {'verdict': 'partial', 'expectations': [], 'sources': [], 'missing': [],
     'sha256': content_sha256([]), 'material_sha256': content_sha256({'sources': [], 'missing': []})}
