# Attribute Protocol

`AttributeResult` explains why an incorrect or suspicious output failed and what a developer should verify next.

Inputs:

- project attribution spec
- current `RunTrace`
- `JudgeResult`
- available code, config, log, prompt, or runtime evidence

Fields:

- `case_id`: optional case-pool identity preserved from batch/mock/uploaded datasets
- `failure_category`
- `failure_stage`
- `analysis_method`: how attribution was produced, such as current-case LLM attribution, deterministic chain probe, local fallback, or incomplete because evidence is missing
- `evidence_chain`
- `trace_analysis`
- `chain_nodes`: ordered executable or documented chain nodes with status `normal`, `suspicious`, `failed`, or `not_verified`
- `local_verifications`: concrete local checks, probe results, imports, logs, config reads, or documented absence of such checks
- `earliest_divergence`: earliest evidence-backed node where expected and actual behavior diverge, or an explicit unknown/incomplete marker
- `evidence_coverage`: which current query/actual/expected/trace/project-doc/code evidence supports each root-cause claim
- `analysis_quality`: quality-gate result, missing evidence list, and whether the attribution is complete enough for a developer to act
- `incomplete_reason`: why attribution is not complete when evidence, judge, chain probe, or local verification is unavailable
- `suspected_locations`
- `root_cause_hypothesis`
- `verification_steps`
- `patch_direction`
- `business_impact`
- `quality_flags`

Rules:

- Attribute should run as a formal root-cause analyzer only after judge has produced a current, inspectable failure verdict. If judge is unavailable, stale, reference-only, or lacks expected-vs-actual evidence, attribution should be blocked or marked incomplete instead of inventing a root cause.
- Every attribution generated from a case-pool or batch run should preserve the originating generic case identity when available.
- Attribute should pass a quality gate before its result is used for clustering or developer action: current query evidence, actual output, judge expected-vs-actual diff, executable/documented chain nodes, earliest divergence, and evidence-backed suspected locations or an explicit incomplete reason must be present.
- Attribute should use the application/project boundary already attached to the trace or judge context; if an external dependency is unavailable and the boundary excludes result-set verification, attribution should focus on in-scope parser/model/config/code evidence instead of repeatedly treating that dependency as the root issue. Project adapters may omit excluded dependencies from `chain_nodes` and expose them only as boundary metadata.
- The goal is solving the problem, not describing it vaguely.
- Reconstruct the current expected-vs-actual gap before looking for causes.
- Walk `RunTrace.execution_trace` and mark each stage as normal, suspicious, failed, or not verified.
- Use project code/config/prompt evidence when available; prefer checks that import or call existing project functions over invented standalone logic.
- `suspected_locations` should name modules/functions/configs only when supported by evidence; otherwise mark them as hypotheses or leave them empty.
- `verification_steps` should be executable enough for a developer to confirm or disprove the hypothesis.
- `patch_direction` should describe the minimal source change likely to fix regeneration, not a one-off output/display edit.
- Do not fabricate file paths, functions, line numbers, logs, or test results.
- Do not reuse fields, expected conditions, or fixes from unrelated historical cases.
- If deeper code-path evidence was not collected, say so explicitly instead of inventing it.
