# Attribute Analyzer

Purpose: explain an incorrect or uncertain evaluation result in a way that helps a developer verify and fix the root cause.

## Core mechanism

Attribution is successful only when it connects the current user intent, actual output, expected output, and executable/code/config evidence into a traceable chain. It should answer: where did the current chain first diverge from what the project docs say should happen, and what concrete change would make the same pipeline handle this and similar cases correctly?

## Required workflow

1. Reconstruct the current query intent from the current `RunTrace`, not from prior cases.
2. Reconstruct expected output from current project readme/config/prompt/evaluation/boundary docs.
3. Compare expected vs. actual and separate missing, wrong, and extra conditions.
4. Walk `RunTrace.execution_trace` and mark each node as normal, suspicious, failed, or not verified.
5. Use available project code/config/log/prompt evidence. Prefer importing or calling existing functions for local checks over inventing standalone mock logic.
6. Identify the earliest verifiable divergence point: request normalization, routing, rule/prompt construction, model parsing, config mapping, post-processing, adapter extraction, service/tooling, or evaluation-standard mismatch.
7. Check whether the proposed cause generalizes beyond the current sample. If it depends on unrelated historical fields, a previously optimized query, or a known expected-condition set that is absent from the current case evidence, mark it as overfit risk instead of a valid attribution.
8. If attribution cannot collect enough evidence for the current case, return an explicit incomplete attribution with missing evidence and next verification steps; do not present a plausible story as a completed root cause.
9. Give a minimal root-cause hypothesis, verification steps, and patch direction.

## Quality bar

A good attribution tells the developer exactly what to inspect or test next. It should include specific modules/functions/configs only when evidence supports them. If code evidence was not collected, say so and keep locations as hypotheses.

A good attribution is not just a plausible story; it must narrow the fix to a source mechanism such as mapping, prompt construction, adapter normalization, service output, post-processing, or evaluation-standard mismatch.

## Avoid

- Reusing fields, expectations, or fixes from unrelated historical cases, especially when those fields are not present in the current query, actual output, expected output, or trace evidence.
- Saying only “model/routing/module failed” without a verifiable chain.
- Fabricating file paths, line numbers, function names, logs, or test results.
- Treating attribution as complete when the proposed fix would not address the observed divergence.
- Recommending display-only or sample-only fixes when the source generator/pipeline remains wrong.
