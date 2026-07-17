# VNext Case Protocol Hard Cutover Implementation Plan

1. Add contract tests for MockCase public transport, strict MockCase-to-runtime conversion, RunTrace input shape, and batch request identity.
2. Make Mock APIs and dataset APIs return MockCase; keep SingleTurnCase/MultiTurnCase internal.
3. Add protocol batch envelopes carrying job_id, request_index, request_key, and request_case_id through events and final runs.
4. Replace frontend legacy case normalization and input deep comparison with MockCase persistence and request-key result association; persist active jobs for reload recovery.
5. Migrate root `data/client_search` datasets, `impl/data/case_pools.json`, core schema fixtures, and test fixtures to MockCase without regenerating business content.
6. Reject obsolete stored/transported `input` cases with explicit protocol errors; preserve `impl/data/context_store` byte-for-byte.
7. Run schema hooks, fixture hooks, API hooks, adapter/protocol compliance, mock-check, focused tests, full regression, and actual 8021 browser UAT.

All edits must preserve unrelated working-tree changes. Historical context-store artifacts are outside the write set.
