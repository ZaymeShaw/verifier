## Context

The current verifier normalizes live or provided outputs into `RunTrace`, then runs judge and attribute as mostly single-pass LLM calls with large JSON schemas. Project adapters can add context, semantic equivalence rules, execution trace nodes, and mock cases, but the main operating model is still one prompt per capability. This makes deep analysis fragile: missing evidence, contradictions, failed probes, and review loops are represented as fields in a final answer instead of first-class runtime states.

The target architecture is a trace-level, declarative state machine for the full evaluation run. A single trace graph can include mock generation, live execution, judge analysis, attribute analysis, verification, critique, retry, and final recommendation states. Each state may invoke one or more subagents, local probes, adapter hooks, or deterministic normalizers. The graph is project-extensible, so complex projects can add deeper chain verification without changing generic core code.

## Goals / Non-Goals

**Goals:**
- Replace single-prompt trace analysis with a multi-round, multi-subagent execution model.
- Use a trace-level state machine, not separate judge/mock/attribute-only graphs, so the whole run can loop through evidence collection, judging, attribution, and verification as needed.
- Make state graphs declarative and project-extensible through configuration plus adapter hooks.
- Preserve state transitions, subagent outputs, evidence, quality gate decisions, retries, and incomplete reasons as inspectable runtime artifacts.
- Provide a recommended default graph that works for simple projects while allowing complex projects to override or extend states and transitions.
- Treat `demand/demand.md`, any project-level demand documents, `.claude/skills/evals/agents/specialized/check.md`, and `openspec/changes/multi-agent-trace-state-machine/harness/constraints.md` as implementation acceptance sources, not optional background.
- Ensure the new architecture preserves protocol alignment, avoids hardcoded overfit, keeps mock/live/batch paths unified, and verifies producing mechanisms rather than only final displayed results.

**Non-Goals:**
- Do not hard-code client-search-specific fields, probes, or evaluation rules in generic core.
- Do not require every project to implement custom subagents or complex graphs.
- Do not make quality gates business correctness rules; they are process and evidence sufficiency checks.
- Do not preserve the old error/failure-centered judge-to-attribute semantics where they conflict with the business expectation fulfillment model. Existing summary fields such as verdict or failure category may remain only as derived display fields during migration, not as the primary protocol contract.

## Decisions

### Decision 1: Use a trace-level declarative state machine

Use one state graph for a full trace evaluation instead of independent per-capability graphs. The state machine represents observable analysis lifecycle states: input preparation, execution, evidence collection, business expectation construction, fulfillment evaluation, fulfillment critique, expectation-level attribution, probe execution, causal review, final synthesis, incomplete stop, or human review.

Rationale: the user's target is overall trace accuracy and depth, not just deeper judge or attribute prompts. A trace-level graph allows judge to request more execution evidence, attribute to request clearer fulfillment assessment, and finalization to block until contradictions are resolved.

Alternatives considered:
- Fixed pipeline: easier but repeats the current rigidity.
- Separate capability graphs: cleaner ownership but weak cross-agent feedback.
- Free-form blackboard: flexible but hard to reproduce, debug, and display.

### Decision 2: Treat state machine as runtime protocol, not business logic

Generic core defines the shape of states, transitions, inputs, outputs, evidence records, quality gates, subagent invocations, and stop reasons. Projects define which states exist, which subagents/probes run, and which gate thresholds apply.

Rationale: a state machine becomes a constraint only if generic code fixes the business states. Here it is the opposite: it externalizes control flow that is currently hidden inside prompts and makes it configurable.

### Decision 3: Support multi-subagent state execution

A state can run one subagent, multiple subagents in sequence, or multiple subagents in parallel. Each subagent must have a role, input contract, output contract, evidence contribution, and merge policy. Example judge state roles include business expectation builder, consumer contract evaluator, boundary evaluator, fulfillment assessor, and fulfillment critic. Example attribute roles include expectation attribution planner, probe runner, earliest-divergence finder, causal category reviewer, and improvement reviewer.

Rationale: focused subagents reduce the ambiguity of huge prompts and make weak evidence or fulfillment contradictions easier to isolate. The merge policy prevents independent subagent outputs from becoming unstructured text blobs.

### Decision 4: Add quality gates as transition guards

Quality gates decide whether a state may finalize, must collect more evidence, must retry, must escalate to another state, or must stop as incomplete. Gates check generic process properties: required evidence presence, contradiction status, business expectation coverage, fulfillment assessment coverage, boundary decision availability, probe success, unsupported claims, and confidence calibration.

Rationale: quality gates make depth enforceable. They prevent formal fulfillment assessments or expectation-level causal attributions when the required analysis evidence does not exist.

### Decision 5: Keep project extension two-layered

Projects can extend through declarative specs for graph states, subagent roles, evidence requirements, gate rules, and transition conditions. Projects can also implement adapter hooks for probes, normalizers, local verifications, evidence collectors, and result reconciliation.

Rationale: simple projects should configure rather than code, while complex projects need executable hooks to verify real code paths.

### Recommended default state machine

A default graph should be available for projects that do not declare their own graph:

1. `prepare_trace`: normalize input, determine execution mode, attach project context.
2. `mock_or_input`: generate or validate mock/user input when needed.
3. `execute_or_capture`: call the application or capture provided output.
4. `collect_evidence`: collect runtime logs, project fields, boundary metadata, source references, and optional probes.
5. `build_business_expectations`: reconstruct user intent, downstream consumer, business expectations, acceptance criteria, and active project boundary.
6. `evaluate_fulfillment`: assess actual output against each business expectation under the active boundary and produce a fulfillment matrix.
7. `fulfillment_critic`: check for contradictions, missing expectation evidence, invalid boundary use, and unsupported fulfillment conclusions.
8. `attribute_expectations`: for unmet, partially met, not-evaluable, or contested expectations, plan causal analysis against the project trace/code graph.
9. `run_attribution_probes`: run project probes, subprocess imports, API replays, schema checks, or documented chain checks.
10. `attribution_critic`: verify earliest divergence, causal category, suspected locations, improvement direction, and source/probe evidence coverage.
11. `finalize`: produce trace result, preserving complete state history.
12. `incomplete_or_human_review`: stop when gates prove evidence is insufficient or the graph exceeds retry limits.

Transitions are conditional rather than linear. For example, `fulfillment_critic` can return to `collect_evidence`, `build_business_expectations`, or `finalize`; `attribution_critic` can return to `run_attribution_probes`, request fulfillment clarification, or stop incomplete.

## Risks / Trade-offs

- State graph complexity can make simple cases slower → Provide a minimal default graph and depth profiles such as `fast`, `standard`, and `deep`.
- Projects may over-customize graphs and lose consistency → Require all states to emit the same state result, evidence, gate, and transition records.
- Parallel subagents may disagree → Require merge policies and critic states to record contradictions before finalization.
- Quality gates may become hidden business rules → Limit generic gates to process/evidence checks and keep project-specific correctness in project specs/adapters.
- Migration may disrupt existing frontend and batch flows → Preserve current final result fields while adding state history alongside them.

## Migration Plan

1. Add protocol documents and schemas for trace state machines, subagent state execution, and quality-gated evidence.
2. Implement default graph execution behind the current trace pipeline while preserving existing judge/attribute/mock outputs.
3. Wrap existing judge, attribute, and mock calls as default state/subagent implementations.
4. Add state history, fulfillment matrix, gate output, and expectation-level attribution output to frontend/batch summaries.
5. Convert all active projects to declare or derive consumer contracts, business expectations, fulfillment criteria, and attribution/probe graphs so the change does not leave split semantics across projects.
6. Gradually move project-specific context assembly from monolithic prompts into declared states and adapter hooks.

Rollback is straightforward during migration: keep the old single-pass pipeline callable and select the new state-machine runner only when enabled for a project or run mode.