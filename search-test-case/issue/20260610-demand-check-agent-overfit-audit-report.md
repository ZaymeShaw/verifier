# 2026-06-10 demand/check agent attribution audit report

## Scope

- Latest `demand.md` asks the eval system to keep protocol/code/frontend/data consistent and make attribution useful for developers.
- The audit target is attribution generalization: a new client_search case must be explained from its own query, output, reference, trace, project docs, and verified chain evidence, not from a previous sample or a field blacklist.

## Findings

- [x] Specialized check documentation needed an explicit attribution evidence-chain gate.
  - Evidence: `demand.md` requires check agent to audit generated code and agent outputs for consistency and useful root-cause analysis, and explicitly says overfit handling should not be implemented through rule-like methods.
  - Fix: `.claude/skills/evals/agents/specialized/check.md` now requires auditing whether every field, expected condition, suspected location, and patch direction is grounded in current-case evidence or verified local chain tests.

- [x] Attribute analyzer guidance needed to reject historical-case carryover as a valid root cause.
  - Evidence: attribution is only useful if developers can verify the current executable chain; unrelated fields make the patch direction misleading.
  - Fix: `.claude/skills/evals/agents/specialized/attribute-analyzer.md` now marks unrelated historical fields, prior optimized queries, and absent expected-condition sets as overfit risks only when they lack current-case evidence.

- [x] Runtime attribution prompt needed stronger current-case grounding.
  - Evidence: the attribute LLM could otherwise produce plausible but stale field/fix references.
  - Fix: `impl/core/attribute.py` now tells the attribute agent that every mentioned field, expected condition, and patch direction must be grounded in the current query, actual, expected, execution_trace, or project docs.

- [x] A rule-like runtime overfit detector was removed.
  - Evidence: matching configured markers such as `clientAge/clientSex/annPremSegNum` catches one historical example but violates the `demand.md` requirement to avoid rule-based overfit handling.
  - Fix: removed `frontend_extensions.attribution_overfit_markers` from `impl/projects/client_search/project.yaml` and removed the marker-based attribution detector from `impl/core/check.py`.

- [x] Runtime attribute output now keeps taxonomy fields internally consistent.
  - Evidence: a live smoke run exposed `AttributeResult primary_error_type should appear in error_types`, which is a protocol consistency issue unrelated to overfit detection.
  - Fix: `impl/core/attribute.py` now appends the selected `primary_error_type` into `error_types` when the model omits it.

- [x] Batch/frontend persistence path was rechecked against the previous quota issue.
  - Evidence: `impl/frontend/summary.html` persists only a lightweight case pool through `lightCasePool()` and wraps `sessionStorage.setItem()` in `safeSetSessionJson()`.
  - Result: current implementation keeps full run details in memory for the active page, while browser storage failures do not abort batch polling.

## Verification

- [x] `python -m compileall -q impl` passed after removing the rule-like detector.
- [x] `python -m impl.cli projects` returned `QA` and `client_search`.
- [x] Code scan confirmed `impl/core/check.py` no longer contains `_attribute_overfit_gaps`, `_text_contains_any`, or `attribution_overfit_markers`.
- [x] Live chain smoke for `有生存金未领取的客户` returned `trace_status=ok`, `judge_verdict=correct`, `attribute_stage=none`, and `check_passed=True`.
- [x] Restarted verifier server on port 8020 and `GET /health` returned `status=ok`.
- [x] Batch API smoke with two client_search mock cases returned two runs and `check_passed=True`.

## Remaining note

- The old downstream customer-search service on port 8081 is still not available locally. The verifier now records downstream evidence and uses boundary-aware judge behavior instead of pretending result-set verification succeeded.
