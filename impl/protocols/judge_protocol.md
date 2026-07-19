# Judge Protocol

`JudgeResult` evaluates whether the current run fulfills the project's business expectations under an explicit project-defined boundary. The primary output is fulfillment: `intent_model`, `consumer_contract`, `business_expectations`, `fulfillment_assessments`, and `overall_fulfillment`. The `verdict` and `score` fields are **not** authored by the LLM — they are derived deterministically by the verifier from `overall_fulfillment.status` and `boundary_decision` via a single-point function (`_compute_verdict` / `_compute_score` in `impl/core/judge.py`). Judges must never write `verdict` or `score` directly.

Judge must first rebuild the current user intent, downstream consumer contract, business expectations, and project boundary, then compare expected-vs-actual under that boundary. The boundary protocol is not a substitute for judge logic; it constrains how judge decides which unmet expectations are in-scope fulfillment gaps and which are uncontrollable capability gaps.

Inputs:

- project evaluation spec
- project judge boundary spec
- optional project judge standard
- current `RunTrace`
- optional expected intent supplied by the user or case data

Fields:

- `intent_model`: 意图优先的核心对象，包含 raw_user_request、explicit_intents、implicit_business_intents、constraints、success_definition、blocking_requirements、intent_evidence。judge 必须先构建 intent_model，再从 intent_model 派生 business_expectations。
- `consumer_contract`: who consumes the output and what business contract the current run must satisfy
- `business_expectations`: expectation-level units rebuilt from user intent, project docs, case reference, and downstream contract. Every expectation must declare `blocking` before actual-output comparison; only a missing core user outcome, safety floor, or project hard contract is blocking.
- `fulfillment_assessments`: one assessment per business expectation with status `fulfilled`, `not_fulfilled`, or `not_evaluable` — these three values are the only allowed status vocabulary. Assessments must not contain or redefine `blocking`.
- `overall_fulfillment`: verifier-derived aggregate `status` and `blocking_expectations`. Any blocking `not_fulfilled` yields `not_fulfilled`; otherwise any blocking `not_evaluable` or missing blocking assessment yields `not_evaluable`; otherwise status is `fulfilled`. Non-blocking gaps remain visible but do not fail the overall user goal.
- `verdict`: derived compatibility summary computed by the verifier from `overall_fulfillment.status` and `boundary_decision.within_evaluable_scope`. Mapping: `fulfilled` → `correct`; `not_fulfilled` with in-scope blocking → `incorrect`; `not_evaluable` / out-of-scope → `uncertain`. The judge LLM must omit this field.
- `score`: derived from fulfillment_assessments by `_compute_score`. Returns `None` only when no evaluable assessments exist. The judge LLM must omit this field.
- `confidence`: optional, judge-emitted self-assessment of evidence quality (0-1)
- `probability`: optional probability-style confidence for pages or projects that need it
- `reconstructed_intent`: rebuilt current user intent summary
- `judge_basis`: concise statement of the sources and standards used for the verdict
- `expected`: expected output under the active project boundary. When the input or case does not provide a reference answer, judge should reconstruct a reference here in the same general shape as the adapter-normalized `RunTrace.extracted_output` so frontend `Reference` can show a judge-generated reference instead of an empty field. When input/case data provides a reference, the system should still align it to the evaluated output shape before exposing it as `expected` or frontend reference.
- `actual`: current actual output extracted from `RunTrace`
- `judge_method`: how the verdict was produced, such as current-case LLM judge, deterministic local comparison, or unavailable fallback
- `intent_decomposition`: current-query intent broken into evaluable requirements with evidence sources
- `condition_assessments`: optional per expected requirement/condition comparison against current actual output. New code paths prefer `fulfillment_assessments`; `condition_assessments` remains for projects that still expose per-condition diffs (e.g. client_search wrong/missing/extra).
- `semantic_equivalence_checks`: representation-difference checks that explain why two forms are equivalent or not equivalent under project docs
- `reference_generation_basis`: how judge generated or aligned `expected`, including current query/reference/project-doc sources
- `verdict_derivation`: explicit derivation from assessments, boundary decision, and unresolved evidence gaps. The final `verdict` itself is computed by the verifier; this field records the LLM's reasoning, blocking gaps, and any project deterministic evidence that fed into the assessments.
- `boundary_decision`: whether unmet requirements are within evaluable scope or uncontrollable limits; when the application/project adapter provides an `application_boundary`, judge must consume that boundary instead of independently re-litigating external service availability in every verdict. Boundary metadata belongs here rather than in repeated user-facing evidence unless the boundary itself is the evaluated output.
- `evaluation_boundary`: the final evaluation standard used to decide the verdict. It is loaded from the project judge boundary document and `project.yaml.frontend_extensions.implementation_standard.judge_boundary`.
- `primary_assessment`: assessment under `evaluation_boundary` (legacy compatibility view; new code prefers `fulfillment_assessments` + `overall_fulfillment`)
- `contrast_assessments`: optional explanatory assessments under non-primary standards
- `missing`, `wrong`, `extra`: optional per-item diff lists when the project produces structured per-item comparisons (e.g. client_search). Not required when fulfillment assessments already capture the gap.
- `evidence`
- `reasoning_summary`
- `quality_flags`: structural markers such as `self_check_failed`, `llm_call_failed`, `<project>_contract_gate_failed`, `marketing_planning_contract_mismatch`, etc.
- `needs_human_review`: set to `true` when self-check failed or LLM call failed; signals downstream agents and UI to flag the case.

Boundary decision:

`boundary_decision` should include:

- `within_evaluable_scope`: `true`, `false`, or `null` when evidence is insufficient
- `uncontrollable_limits`: unmet needs caused by external/system constraints outside the current project control boundary
- `evaluable_errors`: unmet needs caused by model, prompt, config, code, mapping, post-processing, or other project-controllable behavior
- `reasoning`: why judge placed the issue inside or outside the evaluable scope

Self-check:

After the LLM returns, the verifier runs `_judge_self_check` to detect invalid status vocabulary, unknown expectation IDs, and missing assessments. `overall_fulfillment.status` is computed deterministically after project reconciliation and never triggers a reprompt. When a reprompt is necessary, it includes the previous complete JSON, exact error paths, and an instruction to preserve unaffected fields.

- adds `self_check_failed` to `quality_flags`
- sets `needs_human_review = true`
- forces `verdict = "uncertain"` and `score = None` regardless of what `_compute_verdict` would otherwise yield

This is the only path where the verifier overrides the single-point derivation, and the override is one-way (toward `uncertain`).

LLM-call failure:

When the underlying LLM call errors out, the verifier returns a minimal honest `JudgeResult` with empty `business_expectations` and `fulfillment_assessments`, `overall_fulfillment.status = "not_evaluable"`, `quality_flags = ["llm_call_failed"]`, `judge_method = "llm_call_failed"`, `needs_human_review = true`, and `verdict` computed from `overall_fulfillment.status = "not_evaluable"` (which yields `uncertain`).

Adapter contract gates:

Project adapters can enforce deterministic contract checks (e.g. `marketting-planning` stage/event/path contracts, `marketting-planning-intent` intent contract, QA gold-answer match) by injecting a blocking business expectation and its fulfillment assessment. They must not write the final overall status. The pattern:

1. The adapter detects a contract failure in `normalize_judge_result(trace, judge_result)`.
2. The adapter appends or updates `BusinessExpectation(expectation_id="<contract>:<requirement>", blocking=True, ...)`.
3. The adapter appends the corresponding assessment without a `blocking` field.
4. After all project reconciliation, the verifier computes `overall_fulfillment.status` once from the complete expectation/assessment pair set.

Rules:

- Judge is a runtime script agent: after application has produced a current `RunTrace`, verifier code invokes judge to evaluate that trace; project setup may update judge standards, but per-case judging must not depend on a Claude Code subagent.
- Judge may implement project-specific boundary gates, semantic equivalence rules, and result normalization inside the judge capability boundary; attribution root-cause localization remains owned by attribute.
- Every project should provide a short judge boundary standard copied from `impl/judge_boundary-template.md` and filled for that project.
- The user-facing boundary document should only answer project-varying boundary questions: what the external/system limits are, what remains within the evaluable system scope, and which sources define that boundary.
- The template should guide the user to distinguish uncontrollable capability gaps from controllable output errors instead of asking for internal judge configuration.
- Fixed judge conflict behavior belongs in the generic template/protocol explanation and judge implementation, not in user-filled project fields.
- The user-facing boundary document only needs to explain the project evaluation boundary in plain language.
- Internal fields such as `evaluation_boundary`, `primary_assessment`, `contrast_assessments`, and `boundary_decision` are judge output fields, not user-filled boundary fields.
- Uncontrollable external limitations must not be expressed as blocking business expectations. Their assessments remain `not_evaluable` evidence without failing an otherwise fulfilled in-scope user goal.
- Evaluable system-responsibility errors remain judge failures even when an external limitation also exists; the boundary classification only excludes pure out-of-boundary limitations.
- The final `verdict` is derived from exactly one primary fulfillment assessment set under exactly one primary boundary, by the single-point `_compute_verdict` function.
- Contrast boundaries are allowed only to explain gaps unless the project boundary explicitly says they affect the fulfillment assessment.
- Rebuild business expectations and expected-vs-actual evidence from the current trace, evaluation spec, judge boundary spec, optional project judge standard, project judge context, and project-owned source references exposed by the project spec.
- For intent/parser projects, judge should compare the final adapter-normalized actual output by business/search semantics rather than mechanically by field/operator surface shape: verify field semantic carrier, operator compatibility with field type, value normalization, query logic, missing/wrong/extra conditions, and documented semantic equivalence rules.
- Keep project-specific judging semantics in project docs/evaluation/boundary specs, not in generic judge code.
- Do not inherit historical cases, UI state, clusters, or prior attribution conclusions.
- If boundary evidence is insufficient, emit `not_evaluable` fulfillment with missing evidence flags; the verifier will derive `uncertain`. Otherwise prefer expectation-level statuses over a direct `correct`/`incorrect` decision (which the LLM no longer authors anyway).
- Judge may provide lightweight suspected issue type, but full expectation-level causal attribution belongs to attribute.
