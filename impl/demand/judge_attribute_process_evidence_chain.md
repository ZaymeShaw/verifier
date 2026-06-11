# Judge/Attribute process evidence-chain demand

## Background

The older `search-test-case/llm_attribution_server.py` judge and attribute flow is stronger than the current generic `impl` flow in one important way: it does not treat a valid JSON result as enough. It requires the agent to show how the current query was judged or attributed from current evidence.

## Current gap

- Current `impl` judge already has boundary-aware expected-vs-actual fields, but the protocol does not require a visible judging process such as intent decomposition, condition-by-condition assessment, semantic equivalence checks, or verdict derivation.
- Current `impl` attribute already requires evidence chain, trace analysis, suspected locations, verification steps, and patch direction, but it does not require a structured chain-node walkthrough, local verification record, earliest divergence point, or analysis-quality gate.
- Because the protocols are mostly structural, a model can return plausible fields that look complete while still carrying stale historical fields or unsupported fix directions.

## Useful mechanisms from the old server

- Judge rebuilds the expected intent from the current query and actual output instead of trusting historical status, UI state, clusters, attribution, or review labels.
- Judge compares current expected and current actual with explicit semantic-equivalence handling, so harmless representation differences do not become false failures.
- Judge derives the final verdict from the current comparison evidence and marks judge unavailable/uncertain instead of pretending success when evidence is missing.
- Attribute runs after judge identifies a current failure, then walks a deterministic or locally verifiable chain when available.
- Attribute identifies the earliest verifiable divergence point, names only evidence-backed locations, and records whether the analysis quality is sufficient.
- When chain evidence is missing, attribute should say what evidence is missing and what to run next instead of inventing code paths or importing fields from a different case.

## Required adjustment

- Upgrade `JudgeResult` with process fields: `intent_decomposition`, `condition_assessments`, `semantic_equivalence_checks`, `reference_generation_basis`, `verdict_derivation`, and `judge_method`.
- Upgrade `AttributeResult` with process fields: `analysis_method`, `chain_nodes`, `local_verifications`, `earliest_divergence`, `evidence_coverage`, `analysis_quality`, and `incomplete_reason`.
- Update judge/attribute prompts to require these process fields from current-case evidence.
- Update check protocol and runtime checks so incorrect/uncertain judge and attribute outputs without process evidence are treated as incomplete, not as a successful explanation.
- Keep project-specific semantics in project documents and source references. Generic core may require semantic-equivalence evidence, but must not hardcode client_search fields or historical examples.
