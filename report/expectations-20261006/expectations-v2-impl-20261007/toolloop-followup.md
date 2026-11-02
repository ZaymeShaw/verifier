# ToolLoop v2 entry follow-up

Status: **109 owned tests passed** under the supplied offline guard. No live model/business calls, no compatibility layer, no shared-code edits, no git commit.

## Scope and changes

Read `toolloop.md`, `integration-first.log`, current `business_trace/design_rules.py`, shared output/quote contracts, and the design-block follow-up report before editing.

Modified only these owned tests:

- `tests/test_transcript_evidence_boundary.py`
  - Replaced legacy `prepare(*a)` with the explicit `prepare(e, client, trace_id, *, tools)` mock signature.
  - Builds scripted submissions from the real axis briefing using `tests.support.unit_reply.unit_reply`; no invented obligation criteria or transcript placeholder positions.
  - Retains the six-axis `not_evaluable` grades, exact upstream missing-detail assertion, shared evidence-boundary prompt assertion, two-call completion, and ToolLoop execution assertion. Units without applicable criteria retain `missing_criterion`, rather than treating an obligation template as a concrete rule.
  - Replaced the obsolete prompt sentence assertion with the current per-response/per-obligation and actual-input/own-response wording. Added nonempty-results and successful-execution assertions. Main-judge evidence/provenance assertions are unchanged.
- `tests/test_business_trace_llmtracing.py`
  - Both evaluation mocks now accept explicit `tools=` and submit `units`/`blocks` via the existing helper.
  - The transcript-not-dossier regression still requires deterministic zero-LLM analysis, `problematic` planning, `t1.c1.response`, visible tool data, read/submit-only completion, and transcript ToolLoop dispatch. Added explicit checks that the original work-coverage failure and `missing work` issue survive.
  - The unanswered-obligation regression now reads first and submits a new-format empty units list. It still requires budget failure and no salvaged output, and additionally verifies an actual `单位未判` coverage rejection. It no longer passes merely because the read prerequisite was unmet.
  - Provider collection, execution slicing, association headers, mocked transport, multi-turn, scenario, and reader assertions remain unchanged.
- `tests/test_llmtracing_tool_loop.py`
  - Tightened the existing report-dispatch preparation mock to the explicit keyword-only `tools` signature.
- `tests/test_process_v2_entrypoints.py`
  - Tightened the pre-run tool-only preparation mock similarly.
  - Strengthened removed-rule coverage: later-call units must exist, have current blocks, exclude the old rule, and retain the current rule. After reading all evidence, trying to use the earlier call's B ID through `/content` is rejected; replacing only that rule reference with the current call's rule is accepted. Earlier rules remain available to their original call despite response replay.
  - Both entries now test rule quotes with an omitted path, explicit empty path, and `/content`, preserving rule plus condition in the resulting problem. Both reject `/role` when the claimed quote is in content. These exercise the shared optional path field, not an entry-specific fallback.

No implementation files, shared helpers, or non-owned tests were modified. The intentional old-schema rejection fixture remains; positive submissions no longer use the legacy results format.

## Offline verification

Interpreter: `/Users/xiaozijian/miniconda3/envs/agno/bin/python`.

Baseline with the same five owned files: **8 failed, 95 passed**. These were exactly the six boundary parametrizations and two transcript-provider tests listed in `integration-first.log`. The formerly blocked satisfied-candidate test already passed.

Final command:

```sh
/Users/xiaozijian/miniconda3/envs/agno/bin/python \
  report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py \
  -q tests/test_process_v2_entrypoints.py tests/test_process_loop.py \
  tests/test_llmtracing_tool_loop.py tests/test_transcript_evidence_boundary.py \
  tests/test_business_trace_llmtracing.py --disable-warnings
```

Result: **109 passed in 3.37s**. Log: `toolloop-followup-tests.log` in this directory.

A separate guarded rerun of `test_removed_system_rule_is_not_in_later_model_blocks_even_when_response_replayed` and `test_mu_cannot_cite_removed_rule_even_if_earlier_and_read` also passed: **2 passed in 0.27s**.

This includes the satisfied/required/unknown candidate states, both removed-rule guards, quote provenance and coverage rejection, read/same-batch boundaries, original tool-output restrictions, HTTP final provenance, provider dispatch, and local fake-server SDK loops. New coverage adds six parametrized cases to the original 103-test selection. Changed test files also pass `py_compile`; searches find no legacy preparation mocks in owned tests or obsolete entry API references in the owned implementations.

## Shared-code status / limits

No new shared-code blocker was encountered in the owned runs; no assertion was skipped or xfailed and no validator was relaxed.

The separate ninth failure in `integration-first.log` (`test_unselected_model_call_cannot_disappear_from_obligation_scope`, `build_units` handling a `None` turn) is outside this ownership. It was not rerun or modified here, and this report does not claim it fixed.

The earlier handoff's direct shared-inventory ownership caveat is also not claimed fixed: `transcript_blocks` still discovers call owners from supplied endpoints. The owned model entry excludes original-response provenance aliases from ordinary input endpoints, and the strengthened replay/removed-rule test confirms it does not borrow the earlier rule. No shared inventory behavior was changed here.

These are offline wiring/validation regressions, not evidence of live model semantic compliance or full-repository health.
