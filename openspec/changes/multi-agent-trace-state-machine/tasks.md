## 1. Demand and Standard Alignment

- [x] 1.1 Read `harness/constraints.md`, inventory `demand/demand.md`, available project demand documents, project implementation standards, and `.claude/skills/evals/agents/specialized/check.md` before implementation
- [x] 1.2 Create and maintain `harness/compliance-matrix.md`, mapping every relevant demand/check item to one of: protocol requirement, schema field, state graph behavior, quality gate, adapter hook, frontend/API display, test, or explicit non-goal
- [x] 1.3 Map demand/check requirements into explicit architecture acceptance checks for protocol alignment, full-pipeline mock flow, judge depth, attribution evidence chain, batch isolation, frontend visibility, and anti-overfit behavior
- [x] 1.4 Identify any project-specific demand conflicts and decide whether they belong in generic protocols, project specs, or adapter hooks before coding
- [x] 1.5 Keep the compliance matrix updated after each implementation group and block completion when any relevant demand/check item lacks verification evidence

## 2. Protocol and Schema Foundation

- [x] 2.1 Add trace state machine protocol documentation covering state graph, transitions, state records, stop reasons, and default graph semantics
- [x] 2.2 Add subagent state execution protocol documentation covering executor types, role contracts, merge policies, and conflict handling
- [x] 2.3 Add quality-gated evidence protocol documentation covering gate types, gate records, recoverability, and incomplete handling
- [x] 2.4 Extend core schemas with state graph, state execution, subagent result, gate decision, transition decision, and trace state history models

## 2. State Machine Runner

- [ ] 2.1 Implement a generic trace state machine runner that loads a graph, executes states, records state history, and follows conditional transitions
- [ ] 2.2 Replace the default error-centered graph with a fulfillment-centered graph: prepare_trace, mock_or_input, execute_or_capture, collect_evidence, build_business_expectations, evaluate_fulfillment, fulfillment_critic, attribute_expectations, run_attribution_probes, attribution_critic, finalize, and incomplete_or_human_review
- [ ] 2.3 Implement retry/depth limits and incomplete/human-review stop behavior
- [ ] 2.4 Preserve useful final summaries while making business expectations, fulfillment assessments, and expectation attributions the primary runtime objects

## 3. Subagent and Hook Execution

- [x] 3.1 Add executor abstraction for LLM subagents, deterministic functions, project adapter hooks, local probes, and normalizers
- [x] 3.2 Wrap existing mock, judge, and attribute calls as default state executors
- [x] 3.3 Implement merge policies for single output, sequential accumulation, parallel agreement, and contradiction recording
- [x] 3.4 Add project adapter extension points for custom graph declaration, state hooks, evidence collectors, probes, and result normalizers

## 4. Quality Gates

- [ ] 4.1 Implement generic gate evaluators for required evidence, business expectation coverage, fulfillment assessment coverage, boundary decision presence, contradiction detection, unsupported claims, source/probe support for causal claims, and finalization readiness
- [ ] 4.2 Wire gate decisions into state transitions so recoverable evidence gaps can collect evidence or retry and unrecoverable gaps stop incomplete
- [ ] 4.3 Add fulfillment-oriented gate presets for user intent reconstruction, consumer contract presence, business expectation criteria, boundary use, fulfillment derivation, and derived verdict consistency
- [ ] 4.4 Add attribution-oriented gate presets for unmet/partial expectation targeting, chain node coverage, local probe or explicit blocked-probe reason, earliest divergence, causal category support, suspected location support, and improvement direction support

## 5. Project Extension and Validation

- [ ] 5.1 Add a simple default project path that uses the built-in fulfillment graph without custom configuration
- [ ] 5.2 Convert all active projects (`QA`, `client_search`, `marketting-planning`, `marketting-planning-intent`) to declare or derive consumer contracts, business expectations, fulfillment criteria, attribution graphs, probes, and result normalizers through configuration and adapter hooks
- [ ] 5.3 Verify mock-generated cases still enter the unified full trace graph instead of bypassing fulfillment evaluation or expectation attribution
- [ ] 5.4 Add regression cases demonstrating recoverable missing expectation evidence, subagent conflict, incomplete stop, successful fulfillment assessment, and successful expectation-level attribution

## 6. Frontend and CLI Visibility

- [ ] 6.1 Expose state history, gate decisions, transition decisions, subagent outputs, fulfillment matrix, expectation attributions, and incomplete reasons in API/CLI result payloads
- [ ] 6.2 Update live and summary pages to show expectation fulfillment status, blocking expectations, causal categories, state progress, and gate outcomes alongside compact derived verdict summaries
- [ ] 6.3 Ensure batch runs preserve independent state history, fulfillment assessments, and expectation attributions per case and do not share judge/attribute context across cases

## 7. Verification

- [x] 7.1 Run unit tests for graph loading, transition selection, gate evaluation, merge policies, and stop conditions
- [ ] 7.2 Run end-to-end traces for all active projects, proving each project produces business expectations, fulfillment assessments, and expectation-level attribution when needed
- [ ] 7.3 Run frontend smoke checks for live trace and attribution summary state-history plus fulfillment-matrix display
- [x] 7.4 Review generated protocols and project implementations for over-specific rules or hard-coded project assumptions
- [x] 7.5 Run `harness/compliance-matrix.md` and check-agent standard review as final acceptance, including evidence that mock/live/batch share the same protocol-driven path and attribution claims are grounded in current trace evidence
