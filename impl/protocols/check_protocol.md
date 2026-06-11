# Check Protocol

`CheckReport` audits whether the evaluation system follows the protocol chain and quality gates.

Fields:

- `passed`
- `issues`
- `boundary_violations`
- `protocol_gaps`
- `consistency_gaps`
- `overfit_risks`
- `data_only_patch_risks`
- `verification_results`
- `recommended_fixes`

Rules:

- Check mechanisms, not only generated artifacts.
- Verify source -> analysis -> run -> judge -> attribute -> cluster -> frontend consistency.
- Flag project-specific fields, ports, paths, or cases if they appear in generic core code.
- Flag judge results without current intent decomposition, expected-vs-actual evidence, condition assessments, semantic-equivalence reasoning when representations differ, or verdict derivation for incorrect/uncertain cases.
- Flag attribution results without evidence chain, executable trace analysis, chain-node walkthrough, earliest divergence or explicit incomplete reason, analysis-quality gate, root-cause hypothesis, verification steps, or patch direction.
- Flag frontend outputs that are static or disconnected from current API results.
- Flag implementation/frontend additions that are not represented in `impl/protocols` when they introduce reusable protocol concepts.
