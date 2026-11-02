# F1 atomic evidence boundary regressions

## Result

**The requested F1 regression matrix passes against the coordinator's production fixes.** Added 10 focused offline cases. No incomplete fix was observed in these cases; no assertion was relaxed, no test was skipped/xfail to hide a failure, and no production code was changed.

Validation completed 2026-10-07 21:18 UTC. No live model calls or external services were used.

## Files changed

- **New:** `tests/test_atomic_evidence_boundaries.py` — 10 parametrized cases, synthetic evidence, real shared validators/provider submitters and receipt hooks. Network connections are forbidden by an autouse fixture.
- **Updated:** `tests/test_need_source_boundaries.py` — only `test_even_matching_trace_ref_requires_actual_source_content`: added `expectation_checks` and `criterion_checks` to its direct internal result fixture. Retained all three original provenance counterexamples and their rejection assertion.
- **Report:** this file.

No other source/test files were edited. Existing unrelated working-tree changes were left untouched.

## Coverage

| Cases | Boundary and assertions |
|---:|---|
| 2 | Agno `_make_submit` and transcript `_submitter`: generic atomic `pass` plus design `insufficient_evidence` is rejected without runtime reads. Reading without completing the batch is still rejected. The **same unchanged payload** is accepted after full reads and `post_batch`; persisted total remains `insufficient_evidence`, both atomic outcomes remain intact, and both evidence sides are populated. |
| 4 | Both providers, missing/present actual original request: E `pass` plus generic `insufficient_evidence` must reject when the request is absent and accept when present. Rejection is specifically the provider's actual-input error, not schema/hash/receipt failure. Accepted results retain the E pass, generic gap, weaker total, and matched runtime link. |
| 2 | Both providers: E `input_invalid` plus generic `pass` accepts despite the missing original request, **only after** an actual same-evaluator `context_memory/input_assembled` failure was accepted and its real receipt was recorded through `Call → History → post_batch`. A submission before recording that receipt rejects with the upstream-reference error. The persisted result retains total `pass`, E `input_invalid`, generic `pass`, and upstream IDs on both the unit and invalid criterion. No fabricated issue is inserted into the receipt registry. |
| 2 | Direct batch-path `validate_dossier_expectations`: results first pass the shared validator, then E `pass`/`fail` plus generic `insufficient_evidence` reject when actual source content is absent. Identical E and judgments pass the direct gate when the actual request body contains the source. The E-pass case specifically has total `insufficient_evidence`. |

The existing provenance regression still rejects all three misleading cases: a matching but misbound message ref, source-looking call metadata, and source-looking rendered text. None can replace actual request content.

### Fixture details

- Transcript cases reuse `interleaved_trace()` and `frozen()`: c1 received `Tell me current status.`, c2 only has the earlier request. The missing-source case matches c2, and the positive case matches c1.
- Agno cases reuse `agno_instance('output_faithful')`, build E-derived units with production `required_units`, `criteria_for`, and `build_units`, and use the real `EvidenceIndex` and submitter. The default model input is `Check device A.`, distinct from E's original request. A separate original-request record supports the real context failure comparison.
- The Agno fixture starts from the existing helper rather than running a nested analysis/model loop. The direct dossier tests cover the validator used by batch consumers, not a batch model invocation.
- E identity is derived from actual content by `frozen()` and explicitly verified with `content_sha256`; projection identity and saved result fingerprints are also checked. No stale or placeholder E hashes are introduced.
- Assertions preserve the difficult atomic checks rather than changing their outcomes or deleting them to obtain acceptance.

## Offline validation

Interpreter: `/Users/xiaozijian/miniconda3/envs/agno/bin/python`.

Focused run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/Users/xiaozijian/miniconda3/envs/agno/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_atomic_evidence_boundaries.py tests/test_need_source_boundaries.py
```

**56 passed in 0.37s** (10 new cases plus 46 existing source-boundary cases).

Broader relevant run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/Users/xiaozijian/miniconda3/envs/agno/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_atomic_evidence_boundaries.py \
  tests/test_process_v2_atomic.py tests/test_process_v2_rules.py \
  tests/test_process_unit_output.py tests/test_process_criterion_checks.py \
  tests/test_design_rule_blocks.py tests/test_process_v2_entrypoints.py \
  tests/test_expectations.py tests/test_expectations_v2_need_judge.py \
  tests/test_need_source_boundaries.py tests/test_process_prompt_contract.py \
  tests/test_axis_materials.py tests/test_process_main_judge.py \
  tests/test_process_axes_protocol.py tests/test_llmtracing_tool_loop.py \
  -k 'not test_true_llm_client_and_tool_protocol_work_with_local_fake_server'
```

**613 passed, 1 deselected in 1.38s.** The deselected test opens a local fake HTTP server; no network integration test was run. Unlike the read-only review, this run includes the existing temporary-directory capability-save test.

These are overlapping runs, not 669 unique tests. No full-repository or live acceptance claim is made. Scripted judgments verify mechanical validation and provenance boundaries, not model semantic accuracy.

## Evaluated production snapshot

HEAD: `cde26b13a42dc7c8493d55d99552f0e3ebf420b3`. The working tree contains pre-existing changes, so HEAD alone does not identify the evaluated implementation. SHA-256 values captured alongside the broader run:

| File (relative to `impl/projects/llm_probe/`) | SHA-256 |
|---|---|
| `process_loop/evaluation.py` | `15ad4e412154f3280a442157147bf31c6e5f5023d9e4d203cc657ab71f5169ac` |
| `process_loop/expectation_projection.py` | `0cf00371fd51fb7b05941ef63c952ecc4ee7d077c13b2b3454b818d585f5ced3` |
| `business_trace/providers/llmtracing_evidence.py` | `782df81dc6185ad8ef3e6894d8d6f1a13f12f51629dde2dfef14a16ea6898ba5` |

**Conclusion:** the targeted F1 false-accept/false-reject examples are now guarded by passing regressions, including the retained actual-content provenance check. No production changes are needed based on this focused test run.
