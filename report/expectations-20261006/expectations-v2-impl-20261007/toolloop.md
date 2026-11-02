# ToolLoop six-axis v2 handoff

Status: both owned entries migrated; **71 owned tests passed, 1 failed on a coordinator-owned shared-validator blocker**. No live model/business calls; no git commit; no demand/spec/shared-module changes.

## Remaining shared blocker — coordinator action required

Failing test:

```text
tests/test_process_v2_entrypoints.py::test_candidate_necessity_preserved_and_unresolved_actions_not_lost[satisfied]
```

`process_output.expand` intentionally gives a satisfied candidate empty checks/rules while retaining its source `criterion_refs` / `expectation_ids`. `expectation_projection.bind_results` still requires `expectation_checks` to cover those IDs, and rejects it with:

```text
每条引用需求必须有独立核对结果
```

Per UNIT_SYSTEM, satisfied must have empty checks/rules and no business issue. Please exempt `discharged` rows from that equality check while retaining E identity validation and empty-check requirements. Required and unknown candidate cases already pass. The entries do not work around shared validation or change the model's decision. I left the failing test active, not skipped/xfail. A 300-second wait and rerun confirmed this is still present.

## Owned changes

- `impl/projects/llm_probe/process_loop/evaluation.py`
  - Uses shared `OUTPUT`, `UNIT_SYSTEM`, `UNIT_CONSUMER`, `build_units`, `validate_submission`.
  - Axis cases/briefings carry short unit/criterion maps and complete `original_blocks`.
  - Keeps same-batch receipt isolation and dossier provider-boundary validation after shared validation.
  - Adds explicit validation that derived pass/fail endpoints were actually read; filtered-away unread/missing endpoints cannot silently produce pass.
  - Upstream issues are available only from previous-batch accepted receipts.
- `impl/projects/llm_probe/process_loop/llmtracing.py`
  - Uses exactly the same shared schema and validator, then transcript-specific evidence validation.
  - Deletes old grouped submission validator and transcript-placeholder position substitution.
  - Program-owned runtime links and units cover every model response × obligation and all observable per-event units in other axes.
  - Supplies whole candidate blocks with the initial briefing; these do not grant a whole-record reading receipt.
  - `prepare(..., tools=...)` receives only typed tool blocks from the first recorded call per turn, not later runtime tools, responses, or tool results.
- `impl/projects/llm_probe/process_loop/__init__.py`
  - Uses `project_design(trace)` and passes only tools-component blocks to pre-run preparation.
- `impl/projects/llm_probe/business_trace/providers/llmtracing_evidence.py`
  - Enumerates runtime boundaries from real transcript records and exact call-input membership.
  - Tool execution original outputs remain absent. Received tool messages can represent received data, never independent tool-side original returns.
  - Context links retain response → replayed assistant, missing-origin tool arrival, per-call input assembly, and final delivery boundaries; repeated shared prefixes do not inflate the same transfer count.
  - Original-response aliases in `call.input_refs` remain transfer provenance; ordinary model/intent/planning input endpoints use the actual request-message records rather than duplicate historical response aliases. This also prevents inheriting an earlier removed system rule via its replayed response.
  - Validated `design:` identities are recognized only when explicitly passed after shared quote validation. Original quote refs are independently checked against the target model call's actual input members.
  - Preserves original-response-only model outputs, HTTP final provenance, complete-read pagination/alias receipts, source-based E membership, and context two-end restrictions.
- Migrated `tests/test_process_loop.py` and `tests/test_llmtracing_tool_loop.py` without dropping business guards.
- Added `tests/test_process_v2_entrypoints.py`: 32 v2 tests, including both entries' shared API identity, quote/coverage/identity rejection, design-only criteria with separate conditions, read gates, collection-version rejection, exact multi-event coverage, E underlying-source membership, necessity states, runtime-match rejection, upstream batch isolation, and pre-run tool-only preparation.

`eval_axes/adapters/transcript_axes.py` required no change. No compatibility aliases or old schema paths remain in owned entries.

## Validation

All commands used `/Users/xiaozijian/miniconda3/envs/agno/bin/python` and the supplied offline guard.

Latest owned run:

```text
python report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py \
  -q tests/test_process_v2_entrypoints.py tests/test_process_loop.py tests/test_llmtracing_tool_loop.py --disable-warnings
1 failed, 71 passed in 3.37s
```

- Migrated existing owned tests: 40/40 pass, including real local fake-server/SDK ToolLoop runs, nested Agno analysis, retries, isolation, budget failure without partial results, completion hooks, and business evidence guards.
- New v2 tests: 31/32 pass; sole failure is the shared satisfied-candidate blocker above.
- Owned modules and tests compile successfully.
- Search confirms owned entries no longer reference `ProcessAssessment`, `_expand`, `CONSUMER_PROMPT`, `attach_criteria`, `called_tools`, or `validate_groups`.
- Exploratory run with `test_business_trace_llmtracing.py` and `test_design_rule_blocks.py` plus migrated tests: 80 passed, 2 failed. Both failures are old tests' `prepare` monkeypatches lacking `tools=` and old payloads; those non-owned tests were not edited.
- `test_transcript_evidence_boundary.py` likewise still contains legacy payloads/`prepare` mocks; exploratory run stopped after its first 3 failures. Coordinator should migrate these tests, not add a compatibility path.
- Full repository and live/semantic validation not claimed.

## Additional shared inventory observation

`design_rules.transcript_blocks` currently discovers owners from all input/output response endpoints. A caller that supplies a historical response alias as an ordinary input can therefore inherit that earlier call's rules. The owned entries now model actual request-message endpoints without those duplicate aliases, and the removed-rule regression passes. It remains worth making the shared inventory itself target-call-specific for other callers. No shared file was modified here.
