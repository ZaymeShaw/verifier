# Quality Gated Evidence Protocol

Quality gates are generic process and evidence sufficiency checks that control state transitions and finalization. They are not project business correctness rules.

Project-specific correctness belongs in project standards, state declarations, adapter hooks, or subagent contracts. Generic gates only check whether the required evidence and process decisions exist, are non-contradictory, and are grounded.

## Gate declaration

A gate declaration defines:

- `gate_id`
- `gate_type`
- `required_inputs`
- `recoverable`
- `on_pass`
- `on_fail`
- `recommended_transition`
- `human_review_on_failure`

Generic gate types include:

- `required_evidence`
- `expected_actual_coverage`
- `boundary_decision_present`
- `contradiction_free`
- `unsupported_claims_absent`
- `probe_available_or_incomplete`
- `finalization_ready`
- `compliance_evidence_present`

## Gate decision

Each gate evaluation emits:

- `gate_id`
- `gate_type`
- `passed`
- `checked_inputs`
- `missing_evidence`
- `unsupported_claims`
- `contradictions`
- `recoverable`
- `recommended_transition`
- `reason`

Gate decisions must be stored in state history and exposed to CLI/API/frontend payloads.

## Judge gate presets

Judge-oriented gate presets check process completeness for:

- reconstructed intent presence,
- expected-vs-actual comparison coverage,
- active boundary decision availability,
- verdict derivation support,
- contradiction-free critique.

A judge gate may block confident verdict finalization when these artifacts are missing.

## Attribution gate presets

Attribution-oriented gate presets check process completeness for:

- inspectable judge gap,
- chain node coverage,
- probe or local verification evidence,
- earliest divergence or explicit unknown marker,
- suspected location support,
- verification steps,
- minimal patch direction tied to a producing mechanism.

If evidence is unavailable, attribution must stop incomplete or request more evidence instead of inventing locations, logs, tests, or fixes.

## Compliance gate

The compliance gate uses `openspec/changes/multi-agent-trace-state-machine/harness/compliance-matrix.md` as the acceptance ledger. A relevant row cannot be treated as complete unless it records implementation artifacts and verification evidence.

The compliance gate fails when demand, project demand, implementation standard, or check-agent requirements remain unsupported, are hardcoded into the wrong layer, or only change display artifacts without fixing the producing mechanism.
