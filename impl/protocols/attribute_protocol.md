# Attribute Protocol

`AttributeResult` explains the causal chain behind each business expectation’s fulfillment status. It must bind analysis to `expectation_attributions`: fulfilled expectations can produce `no_issue` attribution, while partially fulfilled, not fulfilled, not evaluable, or contested expectations require evidence-backed causal analysis or an explicit blocked reason. Legacy `failure_category` and `failure_stage` are compatibility summaries only.

Inputs:

- project attribution spec
- current `RunTrace`
- `JudgeResult`
- available code, config, log, prompt, or runtime evidence

Fields:

- `case_id`: optional case-pool identity preserved from batch/mock/uploaded datasets
- `expectation_attributions`: one attribution per relevant business expectation with `expectation_id`, `fulfillment_status`, `- `severity` — 归因严重程度（如 blocking/normal/low）
- `primary_error_type` — 主错误类型标签
- causal_category`, evidence, and improvement direction
- `causal_category`: primary aggregate category such as `no_issue`, `implementation_bug`, `model_capability_gap`, `boundary_limitation`, `unclear_contract`, or `insufficient_evidence`
- `probe_results`: deterministic or documented probes supporting the attribution, or blocked-probe reasons
- `failure_category`: compatibility summary derived from expectation attribution when old callers need it
- `failure_stage`: compatibility summary derived from earliest divergence when old callers need it
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

- Attribute is a runtime script agent: after judge produces current fulfillment assessments, verifier code invokes attribution for the current case; per-case attribution must not depend on a Claude Code subagent.
- Attribute may implement project-specific evidence collectors, trace-node mappers, local probes, and result normalization inside the attribute capability boundary; fulfillment assessment and boundary reconciliation remain owned by judge.
- Attribute should target business expectations, not only failures. If an expectation is fulfilled, produce a minimal `no_issue` attribution when aggregation needs positive evidence. If evidence is unavailable, mark the expectation attribution incomplete instead of inventing a root cause.
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
- Attribute normalizes each result to one status: `supported_root_cause`, `insufficient_evidence`, or `next_verification_step`.
- Field/config/enum/label mapping claims must be grounded in the current query, expected/actual gap, project docs/config, execution trace, or local verification evidence. Without that grounding, leave `suspected_locations` empty and return a next verification step instead of a formal root cause.
- Vague module-only root causes such as “adapter failed” are rejected unless current-case chain-node evidence supports the module/location claim.
- Source-file catalog must be narrowed by current trace signals (failed/suspicious `execution_trace` stages, `attribution_targets`, or stage-prefix maps), not by exposing the full external repository. Adapters should publish at most ~8 ext_repo entries per case in `source_config_paths`; project documentation entries (`project_doc:source_*`) and the project adapter itself are not counted toward this cap.
- Tool calls that fetch source content must respect a per-case aggregate byte budget (see `tool_protocol.md`). When the budget is exhausted, the attribute agent must finalise with `incomplete_reason` rather than chase additional files.
