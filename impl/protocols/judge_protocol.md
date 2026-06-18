# Judge Protocol

`JudgeResult` evaluates whether the current run fulfills the project’s business expectations under an explicit project-defined boundary. The primary output is fulfillment: `- `intent_model` — 意图优先的核心对象，包含 raw_user_request、explicit_intents、implicit_business_intents、constraints、success_definition、blocking_requirements、intent_evidence。judge 必须先构建 intent_model，再从 intent_model 派生 business_expectations。
- consumer_contract`, `business_expectations`, `fulfillment_assessments`, and `overall_fulfillment`. The legacy `verdict` is a derived compatibility summary for old callers and must be derived from fulfillment assessments, not treated as the conceptual center.

Judge must first rebuild the current user intent, downstream consumer contract, business expectations, and project boundary, then compare expected-vs-actual under that boundary. The boundary protocol is not a substitute for judge logic; it constrains how judge decides which unmet expectations are in-scope fulfillment gaps and which are uncontrollable capability gaps.

Inputs:

- project evaluation spec
- project judge boundary spec
- optional project judge standard
- current `RunTrace`
- optional expected intent supplied by the user or case data

Fields:

- `consumer_contract`: who consumes the output and what business contract the current run must satisfy
- `business_expectations`: expectation-level units rebuilt from user intent, project docs, case reference, and downstream contract
- `fulfillment_assessments`: one assessment per business expectation with status `fulfilled`, `partially_fulfilled`, `not_fulfilled`, `not_evaluable`, or `contested`
- `overall_fulfillment`: aggregate status, blocking expectations, and downstream impact
- `verdict`: derived compatibility summary: `fulfilled` maps to `correct`; `not_fulfilled` or blocking gaps map to `incorrect`; partial/not-evaluable/contested states map to `uncertain`
- `score`
- `confidence`
- `probability`: optional probability-style confidence for pages or projects that need it
- `reconstructed_intent`: rebuilt current user intent summary
- `judge_basis`: concise statement of the sources and standards used for the verdict
- `expected`: expected output under the active project boundary. When the input or case does not provide a reference answer, judge should reconstruct a reference here in the same general shape as the adapter-normalized `RunTrace.extracted_output` so frontend `Reference` can show a judge-generated reference instead of an empty field. When input/case data provides a reference, the system should still align it to the evaluated output shape before exposing it as `expected` or frontend reference.
- `actual`: current actual output extracted from `RunTrace`
- `judge_method`: how the verdict was produced, such as current-case LLM judge, deterministic local comparison, or unavailable fallback
- `intent_decomposition`: current-query intent broken into evaluable requirements with evidence sources
- `condition_assessments`: per expected requirement/condition comparison against current actual output
- `semantic_equivalence_checks`: representation-difference checks that explain why two forms are equivalent or not equivalent under project docs
- `reference_generation_basis`: how judge generated or aligned `expected`, including current query/reference/project-doc sources
- `verdict_derivation`: explicit derivation from assessments, boundary decision, and unresolved evidence gaps to final `verdict`
- `boundary_decision`: whether unmet requirements are within evaluable scope or uncontrollable limits; when the application/project adapter provides an `application_boundary`, judge must consume that boundary instead of independently re-litigating external service availability in every verdict. Boundary metadata belongs here rather than in repeated user-facing evidence unless the boundary itself is the evaluated output.
- `evaluation_boundary`: the final evaluation standard used to decide the verdict. It is loaded from the project judge boundary document and `project.yaml.frontend_extensions.implementation_standard.judge_boundary`, then normalized before verdict reconciliation.
- `primary_assessment`: assessment under `evaluation_boundary`
- `contrast_assessments`: optional explanatory assessments under non-primary standards
- `missing`
- `wrong`
- `extra`
- `evidence`
- `reasoning_summary`
- `quality_flags`

Boundary decision:

`boundary_decision` should include:

- `within_evaluable_scope`: `true`, `false`, or `null` when evidence is insufficient
- `uncontrollable_limits`: unmet needs caused by external/system constraints outside the current project control boundary
- `evaluable_errors`: unmet needs caused by model, prompt, config, code, mapping, post-processing, or other project-controllable behavior
- `reasoning`: why judge placed the issue inside or outside the evaluable scope

Rules:

- Judge is a runtime script agent: after application has produced a current `RunTrace`, verifier code invokes judge to evaluate that trace; project setup may update judge standards, but per-case judging must not depend on a Claude Code subagent.
- Judge may implement project-specific boundary gates, semantic equivalence rules, and result normalization inside the judge capability boundary; attribution root-cause localization remains owned by attribute.
- Every project should provide a short judge boundary standard copied from `impl/judge_boundary-template.md` and filled for that project.
- The user-facing boundary document should only answer project-varying boundary questions: what the external/system limits are, what remains within the evaluable system scope, and which sources define that boundary.
- The template should guide the user to distinguish uncontrollable capability gaps from controllable output errors instead of asking for internal judge configuration.
- Fixed judge conflict behavior belongs in the generic template/protocol explanation and judge implementation, not in user-filled project fields.
- The user-facing boundary document only needs to explain the project evaluation boundary in plain language.
- Internal fields such as `evaluation_boundary`, `primary_assessment`, `contrast_assessments`, and `boundary_decision` are judge output fields, not user-filled boundary fields.
- Judge applies the structured boundary gate before final verdict reconciliation: uncontrollable external limitations are recorded in `boundary_decision` and must not remain penalized as `incorrect` when no project-controllable error exists.
- Evaluable system-responsibility errors remain judge failures even when an external limitation also exists; the gate only excludes pure out-of-boundary limitations.
- The final `verdict` is derived from exactly one primary fulfillment assessment set under exactly one primary boundary.
- Contrast boundaries are allowed only to explain gaps unless the project boundary explicitly says they affect the fulfillment assessment.
- Rebuild business expectations and expected-vs-actual evidence from the current trace, evaluation spec, judge boundary spec, optional project judge standard, project judge context, and project-owned source references exposed by the project spec.
- For intent/parser projects, judge should compare the final adapter-normalized actual output by business/search semantics rather than mechanically by field/operator surface shape: verify field semantic carrier, operator compatibility with field type, value normalization, query logic, missing/wrong/extra conditions, and documented semantic equivalence rules.
- Keep project-specific judging semantics in project docs/evaluation/boundary specs, not in generic judge code.
- Do not inherit historical cases, UI state, clusters, or prior attribution conclusions.
- If boundary evidence is insufficient, return `not_evaluable` fulfillment with missing evidence flags and derive `uncertain`; otherwise prefer expectation-level statuses over a direct `correct`/`incorrect` decision.
- Judge may provide lightweight suspected issue type, but full expectation-level causal attribution belongs to attribute.
