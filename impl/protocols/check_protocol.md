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
- Flag judge results without expected-vs-actual evidence.
- Flag attribution results without evidence chain, executable trace analysis, root-cause hypothesis, verification steps, or patch direction.
- Flag frontend outputs that are static or disconnected from current API results.
- Flag implementation/frontend additions that are not represented in `impl/protocols` when they introduce reusable protocol concepts.
