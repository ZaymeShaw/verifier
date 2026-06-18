# Multi-Agent Trace State Machine Harness Constraints

This harness is the implementation guardrail for `openspec/changes/multi-agent-trace-state-machine`. Any implementation under this change must satisfy this file before it can be called complete.

## Source documents

Implementation must read and apply the current versions of:

- `demand/demand.md`
- `.claude/skills/evals/agents/specialized/check.md`
- `impl/project_implementation_standard-template.md`
- `impl/projects/*/implementation_standard.md`
- `impl/projects/*/project.yaml`
- `projects/QA/QA-demand.md`
- `projects/marketting-planning/marketplan-demand.md`
- `projects/marketting-planning-intent/marketplan-demand.md`
- Any future `projects/*/demand.md`, `projects/*/*demand*.md`, or `impl/projects/*/demand.md` discovered during implementation

If a source document is missing, record that in the compliance matrix with the search command used and the fallback source used.

## Explicit source-derived requirements

### A. Total demand requirements from `demand/demand.md`

The change must preserve and implement these total-demand constraints:

1. **Core capabilities**: the harness must support business/code understanding, mock data construction, application execution, batch execution, judge, attribution, and code/standard consistency checking.
2. **Analysis/project extraction**: project analysis must be able to derive API shape, business background, mock plan, frontend adaptation, evaluation standard, pipeline/code chain, and attribution strategy into `impl/projects/<project>` artifacts.
3. **Application execution**: projects with existing services must be callable through standardized service usage; projects without complete services must still expose a standardized simulated application path.
4. **Mock capability**: mock must generate realistic user intents and, for runtime interaction, simulate next user input where multi-turn context exists.
5. **Judge capability**: judge must evaluate how well the trace output fulfills current user/downstream business expectations under the active project boundary; when no reference exists, judge must produce or align a reference as evidence for expectation fulfillment.
6. **Attribute capability**: attribute must explain why business expectations are fulfilled, partially fulfilled, unmet, or not evaluable by analyzing the project code/logic chain, and must produce actionable, developer-useful causal evidence and improvement direction.
7. **Trace language/depth**: judge, attribute, mock trace analysis should be Chinese, real-time, multi-round, and deep; it must not collapse into instant shallow single-prompt output.
8. **Implementation placement**: generic protocols/core must live under `impl`; project-specific implementations must live under `impl/projects/<project>` and fill the protocol rather than creating incompatible structures.
9. **Protocol-first design**: protocols are the core abstraction; they must define boundaries, connect to each other, stay flexible, and support both simple and complex projects.
10. **Template usability**: templates must be goal-oriented, project-fillable, generic across projects, and guide users toward useful boundary/standard information instead of vague fields.
11. **Trace definition**: a trace is a complete business execution chain; trace-time may include mock simulation, and post-trace normally includes judge and attribute.
12. **Frontend requirements**: each project should support live request and attribution summary views; these must support mock dataset creation, uploaded custom datasets, batch attribution, case-pool management, persistence, table visualization, output/reference shape alignment, independent per-case judge/attribute context, and judge/attribute skip or retry.
13. **Output/reference handling**: if input provides output, use it; otherwise call the business service. If input provides reference, use it; otherwise judge generates reference. Reference must be shape-aligned to output for display without content-changing conversion.
14. **Judge boundary and fulfillment**: judge evaluates how well output satisfies user intent and downstream business expectations within the project responsibility boundary; external uncontrollable limitations must be represented as boundary or not-evaluable fulfillment outcomes instead of in-scope project failures.
15. **Boundary process**: evaluation boundary must be constructed through protocol/project implementation flow, not by having each judge prompt independently guess the boundary every time.
16. **Attribution usefulness**: attribution must be solution-oriented, evidence-backed, traceable, executable, and specific enough for developers to know what to verify or change.
17. **Attribution chain testing**: attribution should decompose API/code flow into trace nodes and use existing project code/imports/probes/local chain checks where possible; invented standalone logic is not acceptable evidence.
18. **Attribution location and expectation expected-vs-actual**: attribution must identify module/component/function/config/prompt locations only when supported by evidence, and must state the expectation-level expected behavior, actual behavior, causal divergence, and minimal improvement direction.
19. **Avoid mapping confusion**: attribution must not confuse field/config/enum mappings or bring unrelated historical fields into the current case.
20. **Avoid overfit/rule fixes**: improving model behavior must not be done through brittle case-specific rules; check-agent standards govern anti-overfit verification.

### B. Check-agent requirements from `.claude/skills/evals/agents/specialized/check.md`

The change must pass these check-derived constraints:

1. **Mechanism over display**: visible correctness is insufficient; the producing mechanism must regenerate correct, traceable, generalized results.
2. **Latest intent reconstruction**: implementation and review must use current demand/review/project docs, not stale generated outputs.
3. **Source of truth mapping**: every changed artifact must identify its source of truth: protocol, project standard, adapter, pipeline, generator, backend endpoint, frontend component, or persisted case pool.
4. **Protocol alignment**: generic concepts must remain in protocols/core, and project-specific behavior must remain in project implementations/docs.
5. **Source consistency**: generated docs/data/frontend views must match current source generators or project standards; stale generated artifacts should be regenerated from fixed sources.
6. **End-to-end chain review**: mock/live input, service/adapter run, judge, attribute, cluster, check, frontend display, and saved/uploaded case-pool behavior must be walked when relevant.
7. **Producing mechanism inspection**: inputs, normalization, API extraction, judge reference generation, attribution evidence, clustering, persistence, and rendering must agree.
8. **Overfit detection**: hardcoded case values, historical expected fields, example-specific branches, or rules that improve one known case while weakening new cases must fail review.
9. **Dead/stale surface detection**: obsolete buttons, panels, duplicate paths, unused files, and redundant code bypassing current protocol must be aligned or removed after dependency review.
10. **Persistence and batch resilience**: large case pools, partial failures, retries, and storage failures must not erase completed results or stop unrelated cases.
11. **Attribution grounding**: every attribution field, expected condition, suspected location, and patch direction must be grounded in current query, actual, expected, execution trace, project docs, or verified local chain test.
12. **Smallest generalized fix**: issues must be fixed at the common source mechanism with the smallest generalized change that preserves working behavior.
13. **Check report**: final acceptance must include passed items, failed items, evidence locations, causal categories, source/probe support, and generalized fixes or deferrals.

### C. Project demand requirements

#### QA project requirements from `projects/QA/QA-demand.md`

The state-machine change must preserve these QA-specific constraints:

1. **Dataset-driven QA evaluation**: QA evaluation may receive user input, actual output, and golden/reference answer directly from uploaded or provided datasets.
2. **No tested-service call required**: QA can evaluate provided content without calling an external QA system; provided output must still become a normal trace input/output for judge.
3. **Reference-based scoring**: judge must compare user intent, actual output, and reference/golden answer, and support multi-dimensional scoring where the QA project standard requires it.
4. **Generic upload handling**: uploaded QA datasets should use a unified JSON-compatible format or conversion path before entering the shared case-pool protocol.
5. **Project selection UI**: live and attribution summary pages should support project selection as an enumerable dropdown and preserve project-specific state without polluting other project UX.
6. **Protocol generality**: protocol changes must not be hardcoded for client_search; QA-specific needs such as multidimensional scoring, QA error taxonomy, scenario, contexts, and cluster/attribute adaptation must be expressed through generic extension points.
7. **RunTrace flexibility**: QA trace semantics can use provided input/output/reference fields rather than service response extraction, while still conforming to the unified trace protocol.
8. **Per-row evaluation**: uploaded datasets must be evaluated per case/row, not as one shared context that leaks judge/attribute state.
9. **Contexts as input**: QA contexts are part of the evaluation input and may vary by scenario; the protocol must allow project-specific input extensions.
10. **QA check coverage**: check review should include QA-specific checks for dataset parsing, multidimensional scoring, scenario/context handling, reference alignment, and QA error taxonomy alignment.

#### Marketing-planning requirements from `projects/marketting-planning/marketplan-demand.md`

The state-machine change must preserve these marketing-planning constraints:

1. **Repository boundary**: the business project lives at `https://github.com/PA-ALG/marketing-planning` and may be initialized locally under `/Users/xiaozijian/WorkSpace/package/marketing-planning` when absent.
2. **No unauthorized remote mutation**: do not re-pull, push, or otherwise mutate the business repository unless the user explicitly asks.
3. **Standardized service startup**: project execution should follow the project startup flow and expose standardized application usage in the verifier.
4. **Integration risks are source constraints**: known integration differences and pitfalls recorded in `impl/projects/marketting-planning/issue/20260611-marketplan-integration-risks.md` and `reviews-of-propose/20260611-marketplan-integration-risks.md` must be treated as project constraint inputs when implementing custom states/hooks.

#### Marketing-planning-intent requirements from `projects/marketting-planning-intent/marketplan-demand.md`

The state-machine change must preserve these intent-project constraints:

1. **Shared repository and service boundary**: the intent project shares the marketing-planning repository/service constraints but has its own evaluation boundary.
2. **Intent endpoint**: the core API is `/api/v1/marketing-planning/intent-recognition`.
3. **Single-turn scope**: intent recognition is currently single-turn; the graph must not force multi-turn simulation for this project.
4. **Integration risks are source constraints**: the same integration-risk documents must be considered when defining project-specific states/hooks.

### D. Project implementation-standard requirements

Each discovered project standard requires the state-machine change to preserve these acceptance surfaces:

1. **API/application shape**: request execution/capture must respect each project API and application boundary.
2. **Request construction**: state-machine input normalization must reuse project adapter request construction rather than inventing a parallel path.
3. **Output extraction**: actual output must come from project adapter extraction and remain judge/frontend compatible.
4. **Reference handling**: provided references and judge-generated references must align to project output shape.
5. **Judge boundary**: project-specific boundary standards must drive judge scope and gate behavior.
6. **Attribution trace**: project trace nodes and probes must be extensible through adapter hooks/configuration.
7. **Frontend display contract**: UI/API payloads must expose project-compatible output/reference and new state/gate history without breaking existing useful displays.
8. **Batch persistence shape**: generated/uploaded/saved case pools must persist durable source data and independent case results without oversized transient leakage.
9. **Check evidence**: each project must expose enough evidence for check-style review of protocol alignment and source mechanism correctness.

### E. Remembered project constraints relevant to this change

1. **Mock full pipeline**: mock use cases are simulated data but must still execute the unified full evaluation pipeline.
2. **Shared marketing planning service**: `marketting-planning` and `marketting-planning-intent` share a business service but have different evaluation boundaries; the state-machine design must support shared service execution with project-specific judge boundaries.

## Non-negotiable constraints

### 1. Demand compliance matrix is required

Before coding, create or update `openspec/changes/multi-agent-trace-state-machine/harness/compliance-matrix.md`.

For every relevant demand/check requirement, the matrix must include:

- source document and line/section
- requirement summary
- scope: generic protocol, core runner, project adapter, frontend/API, test, or explicit non-goal
- implementation artifact that satisfies it
- verification evidence required before completion
- status: pending, satisfied, deferred, or non-goal

A requirement cannot be marked satisfied without implementation and verification evidence.

### 2. Generic protocols stay generic

Generic core and protocol files must define reusable contracts only: state graph, state record, transition, evidence, gate, subagent execution, stop reason, and extension points.

Project-specific business fields, endpoints, examples, ports, prompts, case values, or semantic mappings must live in project specs, project configuration, project adapters, or project hook implementations.

### 3. Project flexibility is mandatory

Each project must be able to extend the architecture through both:

- declarative configuration: state graph, state roles, gate requirements, evidence requirements, transition conditions
- executable hooks: probes, local verifications, normalizers, evidence collectors, result reconciliation

Simple projects may use the default graph. Complex projects must be able to add depth without editing generic core.

### 4. Mock/live/batch must share the full pipeline

Mock cases are simulated inputs or user intents, not a shortcut around evaluation.

Generated, uploaded, saved, live, and provided-output cases must normalize into the same trace flow and use the same state-machine path for application execution/capture, judge, attribute, finalization, and frontend/batch reporting.

Batch cases must keep independent state history and must not share judge/attribute context across cases.

### 5. Judge must be boundary-aware and fulfillment-driven

Judge must reconstruct the current user intent, identify the downstream consumer/business expectation contract, evaluate actual output against each business expectation under the active project boundary, and expose fulfillment assessments plus any derived verdict summary.

Boundary handling must be represented as process/state/gate behavior, not as every judge prompt independently re-litigating boundary rules.

When no reference exists, judge must generate or align a reference in the output-compatible shape required by frontend and batch views, but the reference is evidence for fulfillment assessment rather than the primary judge/attribute handoff object.

### 6. Attribute must be expectation-causal and evidence-chain driven

Attribute cannot finalize an expectation attribution unless it has current-case evidence for:

- the target business expectation and its fulfillment status
- expectation-level expected behavior, actual behavior, and gap or contested fulfillment reason
- trace or project chain nodes checked
- earliest divergence or explicit unknown marker
- causal category such as implementation bug, model capability gap, boundary limitation, unclear contract, insufficient evidence, or no issue
- suspected locations only when supported by code/config/doc/probe evidence
- executable verification steps or a blocked-probe reason
- minimal improvement direction tied to the producing mechanism

If local code-path evidence is unavailable, attribute must return an incomplete or next-verification reason instead of inventing file paths, functions, logs, tests, or fixes.

### 7. Quality gates are blocking, not decorative

Quality gates must control transitions and completion. They must block finalization when required evidence is missing, contradiction is unresolved, project boundary is unavailable, or claims are unsupported.

Gate failure must either route to a recoverable state such as collect evidence/probe/retry/clarify, or stop as incomplete/human review with reasons preserved.

### 8. Check-agent standards are acceptance criteria

Implementation must pass a check-style review for:

- protocol alignment across protocols, core, project adapters, docs, frontend, CLI, and APIs
- generic/project boundary hygiene
- source mechanism correctness instead of display-only fixes
- no hardcoded overfit to historical cases or field examples
- no split-brain orchestration paths across CLI/backend/frontend/mock/live/batch
- batch resilience for partial failures and retryable errors
- frontend/API consistency with current protocol fields
- data consistency for uploaded, generated, saved, and displayed cases
- minimality: no redundant parallel flows when shared protocol paths can be reused

### 9. Frontend and API visibility is required

Live and summary views must expose enough state-machine information for users to understand what happened:

- state progress/history
- subagent outputs or summaries
- gate decisions
- transition decisions
- final fulfillment matrix and expectation-level attribute result
- incomplete or human-review reason

Output/reference display must preserve shape alignment and readable JSON formatting where applicable.

### 10. Completion requires verification evidence

Before marking implementation complete, provide evidence for:

- unit tests for graph loading, transition selection, fulfillment gate evaluation, attribution gate evaluation, merge policies, and stop conditions
- at least one simple default-graph end-to-end trace that produces business expectations and fulfillment assessments
- at least one complex project deep-graph trace using project hooks/probes for expectation-level attribution
- mock-generated case entering the same full state-machine pipeline
- batch isolation across cases
- frontend/API smoke check for state history, gate display, fulfillment matrix, and expectation attribution display
- compliance matrix completed with no unsatisfied relevant requirement

## Project standards discovered at creation time

Current project implementation standards discovered:

- `impl/projects/QA/implementation_standard.md`
- `impl/projects/client_search/implementation_standard.md`
- `impl/projects/marketting-planning/implementation_standard.md`
- `impl/projects/marketting-planning-intent/implementation_standard.md`

These standards point to `impl/project_implementation_standard-template.md` and cover API/application shape, request construction, output extraction, reference handling, judge boundary, attribution trace, frontend display contract, batch persistence shape, and check evidence. Implementation must treat those categories as project-level acceptance surfaces.

## Required workflow for future agents

1. Read this harness file before applying the change.
2. Refresh source document discovery for new demand or project standard files.
3. Update `harness/compliance-matrix.md` before coding.
4. Implement through generic protocols/core and project extension points according to the matrix.
5. After each implementation group, update the matrix evidence column.
6. Before completion, run the verification set and produce a check-style summary.
