# Check Report: multi-agent-trace-state-machine

Date: 2026-06-14

## Scope

This report supersedes the 2026-06-13 check evidence because the change target has been redesigned around business expectation fulfillment. The earlier evidence validated a state-machine implementation whose judge/attribute handoff was still centered on verdicts, inspectable judge gaps, and root-cause attribution.

That historical evidence remains useful only as baseline evidence for runner mechanics. It must not be used to mark the fulfillment-centered redesign complete.

Projects covered by the next acceptance run:

- `client_search`
- `QA`
- `marketting-planning`
- `marketting-planning-intent`

## Current Source of Truth

- Generic architecture: fulfillment-centered trace state machine, subagent execution, and quality-gated evidence specs in this OpenSpec change.
- Runtime mechanism to implement: `impl/core/state_machine.py`, `impl/core/pipeline.py`, `impl/core/schema.py`, `impl/core/adapter.py`.
- Project-specific behavior to align: `impl/projects/*/adapter.py`, `impl/projects/*/project.yaml`, `impl/projects/*/implementation_standard.md`.
- Frontend/API visibility to align: `impl/frontend/live.html`, `impl/frontend/summary.html`, server API payloads.
- Acceptance ledger: `openspec/changes/multi-agent-trace-state-machine/harness/compliance-matrix.md`.

## Current Acceptance Target

The change is accepted only when implementation and verification prove:

- judge builds or consumes business expectations and downstream/consumer contracts;
- judge produces per-expectation fulfillment assessments and an overall fulfillment summary;
- verdict-like fields are derived summaries, not the primary judge/attribute handoff object;
- attribute targets unmet, partially fulfilled, not-evaluable, or contested expectations;
- attribute produces expectation-level causal attribution with causal category, earliest divergence, source/probe evidence, and improvement direction;
- all active projects are aligned to the fulfillment model, not split between old and new semantics;
- frontend/API/batch expose fulfillment matrix and expectation attributions in addition to state history and gates.

## Previous Evidence Status

Historical evidence from 2026-06-13 is downgraded as follows:

- State-machine runner mechanics: reusable baseline, must be rechecked after graph rename/restructure.
- Project graph hooks: reusable baseline, must be extended to consumer contracts and expectation graphs.
- Mock/live/batch shared path: reusable baseline, must be reverified through fulfillment states.
- Judge quality: insufficient, because it validated expected/actual verdict derivation rather than business expectation fulfillment.
- Attribution grounding: insufficient, because it validated root-cause grounding after judge gaps rather than expectation-level causal attribution.
- Frontend/API visibility: insufficient, because it did not prove fulfillment matrix or expectation attribution display.

## Required Next Check

After implementation, produce a fresh check report with:

1. Compile and unit test evidence for fulfillment schemas, graph transitions, gates, and adapter hooks.
2. All-project run evidence showing `build_business_expectations`, `evaluate_fulfillment`, and, where needed, `attribute_expectations` / `run_attribution_probes`.
3. Representative project examples:
   - QA: answer relevance, groundedness, reference alignment, and taxonomy dimensions as fulfillment assessments.
   - client_search: downstream search-condition fulfillment and causal attribution for condition/field/operator gaps.
   - marketting-planning: planning-output business expectation fulfillment and causal probe evidence.
   - marketting-planning-intent: single-turn intent contract fulfillment.
4. Frontend/API smoke evidence for fulfillment matrix, blocking expectations, causal category, state history, and gate display.
5. Check-agent audit confirming no old error/failure-centered split path remains as the primary protocol.

## Current Status

Pending. The OpenSpec documents now require the new fulfillment-centered implementation and verification; the prior implementation evidence is no longer sufficient for archive readiness.
