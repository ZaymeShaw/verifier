## Why

The current trace algorithms for judge, attribute, and mock are too shallow because each capability is mostly implemented as a single prompt with a large output schema. This makes accuracy, evidence collection, verification depth, and project-specific extensibility depend on prompt wording instead of a reusable multi-round operating model.

## What Changes

- Introduce a trace-level declarative state machine that can orchestrate mock, live execution, business expectation construction, fulfillment-oriented judge, expectation-level attribute, and verification as one multi-round evaluation graph.
- Reframe the judge/attribute handoff around business expectation fulfillment rather than errors: judge evaluates whether user/downstream business expectations are fulfilled, partially fulfilled, unmet, or not evaluable; attribute explains the causal chain behind non-full fulfillment or contested fulfillment.
- Support multiple subagents per state so projects can split planning, evidence collection, semantic comparison, critique, probing, and finalization into focused roles.
- Add quality gates as evidence/process checks that decide whether a state can finalize, must collect more evidence, must retry, must escalate, or must stop as incomplete.
- Allow project-specific state graphs, transition conditions, probes, normalizers, and subagent roles through both configuration and adapter hooks.
- Replace the “one prompt produces final result” model with an inspectable execution record that preserves state transitions, subagent outputs, evidence, gate decisions, and final recommendations.
- Keep protocol constraints generic: the framework defines state/node/transition/evidence/gate contracts, while each project decides which states and project evidence matter.
- Make total demand, project demand, and check-agent standard compliance explicit acceptance criteria for the architecture and implementation.

## Capabilities

### New Capabilities
- `trace-state-machine`: Defines declarative, multi-round trace orchestration across mock, live, judge, attribute, and verification.
- `subagent-state-execution`: Defines how states invoke one or more focused subagents, merge their outputs, and preserve evidence for downstream states.
- `quality-gated-evidence`: Defines generic quality gates for evidence sufficiency, contradiction checks, finalization readiness, and incomplete-result handling.

### Modified Capabilities
<!-- No existing capability requirements are modified in this proposal; existing harness behavior is extended through new protocol capabilities. -->

## Impact

- Affects core trace orchestration, business expectation/fulfillment schemas, judge, attribute, mock, pipeline, and schema concepts under `impl/core`.
- Affects protocol documents under `impl/protocols` by adding state machine, subagent execution, quality gate contracts, and a unified business expectation fulfillment contract shared by judge, attribute, check, cluster, and frontend.
- Affects project adapters under `impl/projects/*` by requiring project-specific consumer contracts, expectation criteria, attribution graphs/probes, local verifications, and result normalizers.
- Affects frontend/live and summary pages because trace results should show state progress, gate decisions, evidence, and incomplete reasons instead of only final judge/attribute fields.
- Does not require every project to implement complex graphs; simple projects can use a default graph with minimal extension points.