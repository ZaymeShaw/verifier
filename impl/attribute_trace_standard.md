# Attribute Trace Standard

Attribute results must explain a current-case failure through evidence that a developer can verify. The attribute agent owns root-cause analysis, evidence-chain normalization, and next-verification-step reporting after judge has produced an inspectable non-correct verdict.

## Required evidence chain

Each attribution must reconstruct and record:

1. current query or input intent;
2. judge expected-vs-actual gap;
3. normalized project API flow or adapter flow;
4. major trace nodes from request construction through output extraction;
5. local chain-test evidence when available;
6. suspected location only when supported by current-case code, config, prompt, document, or runtime evidence;
7. expected behavior and actual behavior at the earliest divergence;
8. patch direction that changes the source generator, mapping, prompt, config, adapter, or post-processing path rather than one displayed result.

## Statuses

Normalized attribute quality has exactly one actionable status:

- `supported_root_cause`: current query, expected, actual, execution trace, and location evidence support the root-cause hypothesis.
- `insufficient_evidence`: the result contains a root-cause or suspected location that is not supported by current-case evidence, or a vague module-only root cause with no chain node evidence.
- `next_verification_step`: the current gap is clear and the next check is actionable, but local code/config/project-doc evidence is still missing.

## Mapping grounding

Field/config/enum/label mapping claims require grounding in the current case. A mapping attribution must include the relevant field or label from current expected/actual output and at least one of:

- project config or enum evidence;
- prompt or evaluation document evidence;
- execution trace node evidence;
- local verification result reading or calling project code/config.

If that evidence is not present, leave `suspected_locations` empty, mark the status as `next_verification_step` or `insufficient_evidence`, and list the exact verification step needed.

## Rejection rules

The normalizer must reject or downgrade:

- vague module-only root causes such as “adapter failed” without current-case evidence;
- historical fields, labels, enum values, or patches not present in the current query/expected/actual/project docs;
- patch directions that edit frontend display or one saved result instead of the generating mechanism;
- root-cause claims when judge was blocked, stale, unavailable, or missing expected-vs-actual evidence.
