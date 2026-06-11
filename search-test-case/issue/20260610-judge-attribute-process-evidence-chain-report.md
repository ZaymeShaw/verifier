# 2026-06-10 judge/attribute process evidence-chain protocol report

## Scope

- User asked to compare the older `search-test-case/llm_attribution_server.py` judge/attribute mechanisms with the current generic `impl` agents.
- The conclusion had to be recorded under `impl/demand`, then implemented in the generic protocol/runtime without adding project-specific hardcoded rules.

## Findings

- [x] Current generic judge was too result-structure oriented.
  - Evidence: `JudgeResult` had expected/actual/boundary/verdict fields, but no required visible process for intent decomposition, condition-level comparison, semantic-equivalence checks, or verdict derivation.
  - Fix: `impl/protocols/judge_protocol.md`, `impl/core/schema.py`, and `impl/core/judge.py` now require and preserve `judge_method`, `intent_decomposition`, `condition_assessments`, `semantic_equivalence_checks`, `reference_generation_basis`, and `verdict_derivation`.

- [x] Current generic attribute was too summary-structure oriented.
  - Evidence: `AttributeResult` required evidence chain and patch direction, but did not force a chain-node walkthrough, earliest divergence, local verification, or quality gate.
  - Fix: `impl/protocols/attribute_protocol.md`, `impl/core/schema.py`, and `impl/core/attribute.py` now require and preserve `analysis_method`, `chain_nodes`, `local_verifications`, `earliest_divergence`, `evidence_coverage`, `analysis_quality`, and `incomplete_reason`.

- [x] Check needed to audit process evidence, not only field presence.
  - Evidence: overfit/stale attribution cannot be solved safely by field blacklists; it has to fail when the current-case evidence chain is missing.
  - Fix: `impl/protocols/check_protocol.md` and `impl/core/check.py` now flag incorrect/uncertain judge or attribute outputs that lack process evidence, current-case grounding, verdict derivation, earliest divergence, or explicit incomplete reason.

- [x] Conclusions were recorded in demand.
  - Evidence: `impl/demand/judge_attribute_process_evidence_chain.md` records the useful old-server mechanisms, current generic gaps, and required protocol adjustments.

- [x] Fallback and batch error paths were aligned.
  - Evidence: fallback/error constructors can otherwise produce old-shape results that bypass new protocol expectations.
  - Fix: `impl/projects/QA/adapter.py` and `impl/core/pipeline.py` now populate process fields for deterministic fallback and batch error results.

- [x] Attribution taxonomy output was constrained to project taxonomy.
  - Evidence: live QA smoke exposed a model-created `missing_key_details` error type outside the QA taxonomy.
  - Fix: `impl/core/attribute.py` now passes allowed taxonomy to the LLM prompt and filters returned `error_types` to the project taxonomy, falling back to `needs_human_review` for unknown primary types when available.

## Verification

- [x] `python -m compileall -q impl` passed.
- [x] `python -m impl.cli projects` returned `QA` and `client_search`.
- [x] QA mock `run-chain` produced judge process fields, attribute process fields, and `check.passed=true`.
- [x] Verifier server was restarted on port 8020 and `GET /health` returned `status=ok`.
- [x] QA batch API smoke returned `check.passed=true` after taxonomy filtering.
- [x] client_search mock chain for `有生存金未领取的客户` returned `judge_verdict=correct`, populated judge process fields, `attribute_stage=none`, `check.passed=true`, and downstream status `unavailable` rather than fake success.
- [x] client_search batch API smoke with two cases returned `total=2`, per-run judge process fields, `check.passed=true`, and no issues.

## Remaining note

- The downstream customer-search service on port 8081 is still unavailable locally. The verifier preserves that as downstream evidence and keeps the boundary-aware judge behavior instead of pretending result-set verification succeeded.
