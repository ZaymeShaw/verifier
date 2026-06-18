# Intent-first Judge Design

## Goal

Judge must first understand the user's real intent, then evaluate whether the current business-system output satisfies that intent within the project's responsibility boundary. Reference matching, fulfillment status, verdict, score, and frontend summaries are secondary artifacts derived from this intent model.

## Problem to fix

The current judge path asks the LLM to reconstruct intent, derive expectations, compare actual output, and emit verdict in one pass. Fallback logic can also derive business expectations from verdict or reasoning. This makes the algorithm look structured while still allowing the core target to be wrong: if user intent is misunderstood, later fulfillment and attribution become precise but useless.

## Design

### 1. Intent model is the primary judge object

Each judge run should first produce an `intent_model`:

- `raw_user_request`: the current trace input used as the user request.
- `explicit_intents`: goals directly stated by the user.
- `implicit_business_intents`: necessary business goals implied by the project context.
- `constraints`: object, time, scope, format, units, context, and boundary constraints.
- `success_definition`: what completing the user task means.
- `blocking_requirements`: requirements whose failure blocks the task.
- `nice_to_have_requirements`: useful but non-blocking requirements.
- `intent_evidence`: where each intent came from: input, context, reference, project document, or trace.

This model is not display-only. It is the source for business expectations and fulfillment assessment.

### 2. Project adapters provide intent frames

Each project adapter should expose an intent frame, not case-specific rules:

- where to read the user request from the trace;
- who consumes the output;
- what business task type the project serves;
- which intent dimensions are critical;
- which boundary rules decide whether an intent is in scope;
- what output semantics let the user or downstream system continue the task.

Examples:

- QA: question target, context dependency, factual/interpretive intent, faithfulness, contradiction risk.
- client_search: target population, fields, operators, units, AND/OR logic, downstream executable search semantics.
- marketing-planning: business metric, target value, time range, decomposition dimensions, planning actionability.

### 3. Business expectations derive from intent

`business_expectations` must be derived from `intent_model`, not from verdict or stale reasoning. Each expectation should identify:

- `source_intent_id`
- `user_goal`
- `required_outcome`
- `blocking_level`
- `boundary_scope`
- `success_criteria`
- `failure_impact`

### 4. Fulfillment evaluates intent-derived expectations

Actual output is judged against intent-derived expectations:

- Does the output satisfy the user goal?
- Does it satisfy blocking requirements?
- Does it respect constraints?
- If it fails, is the failure inside the project responsibility boundary?

Reference answers are evidence and shape guidance. They are not the primary target unless the user/case explicitly defines them as the target.

### 5. Verdict and reason are derived

- `verdict` is a compatibility summary derived from fulfillment.
- `score` reflects blocking and partial fulfillment.
- `reasoning_summary` must explain the understood user intent, which intent was satisfied or blocked, why that matters, and whether the failure is in project scope.
- Judge must not attribute internal code/config/prompt causes; that belongs to attribute.

## Minimal implementation approach

1. Add a generic adapter hook for intent frame construction.
2. Update the generic judge prompt/output contract so intent model is produced before expectations and fulfillment.
3. Change fallback expectation creation so it never derives expectations from verdict alone. If intent cannot be reconstructed, mark the judgment not evaluable.
4. Implement intent frames for QA, client_search, and marketing-planning without case-specific branches.
5. Ensure attribute consumes failed intent-derived expectations instead of reconstructing user intent independently.

## Check.md alignment

- Avoid overfitting: project intent frames describe task semantics, not sample IDs.
- Avoid display-only fixes: the intent model feeds judge expectations and attribute targets.
- Keep protocol alignment: generic hook in core, project-specific semantics in adapters.
- Keep attribution useful: failed expectations carry source intent, so attribute starts from the real user-goal gap.
- Avoid excessive tests: use a few algorithm-effect examples that verify intent modeling, not broad sample patching.

## Success criteria

A judge result is useful only if it can answer:

1. What user intent did it understand?
2. Where did that intent come from?
3. Which in-scope business expectations came from that intent?
4. Did actual output satisfy them?
5. If not, what user task was blocked and why?
