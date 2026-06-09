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
- `evidence_chain`
- `trace_analysis`
- `suspected_locations`
- `root_cause_hypothesis`
- `verification_steps`
- `patch_direction`
- `business_impact`
- `quality_flags`

Rules:

- Every attribution generated from a case-pool or batch run should preserve the originating generic case identity when available.
- Attribute only when judge is incorrect, uncertain, or the user explicitly requests attribution.
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
