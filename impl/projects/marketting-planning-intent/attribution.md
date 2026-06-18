# Attribution

Attribution starts only after judge reports an incorrect, uncertain, or suspicious intent-recognition result for the current trace.

Trace nodes:

1. request_normalization
2. intent_api_call
3. adapter_extraction
4. label_mapping
5. judge
6. attribution

A supported root cause must tie the current query, actual intent, expected intent, trace node evidence, and any code/config/prompt location together. If that evidence is missing, attribution must return insufficient evidence or the next verification step.
