# Marketing-planning business trace

## How to use this trace map

Start from the current public RunTrace and Judge gap. Compare the raw SSE with the verifier-extracted output before entering the business repository. If both show the same wrong value, card, path, or stage, the adapter is not the first deviation. Select the earliest branch where the current case has two comparable observations and follow that branch only. Source code explains an already active mechanism; its mere presence is not evidence that it ran.

For target/path gaps, replay field extraction with the exact transmitted query. If that result already matches the public deviation, run the workflow handoff replay to determine whether clarification/session handling preserves or changes it. Stop before costly planning when the handoff plus public SSE already connect the same value. For card/content failures with a correct handoff, inspect only the dispatched path and its assembly branch.

## Operational index

| Node | Current-case signal | Decisive action | What the result can establish |
|---|---|---|---|
| `REQUEST` | original input and `normalized_request` | Compare all candidate message fields and contexts | What the verifier intended to send |
| `CHAT_REQUEST` | public payload versus selected `user_message`/contexts | Inspect request conversion only when the fields differ | Whether business request normalization changed the input |
| `INTENT_RESOLUTION` | public stage or current resolver output | Confirm the request entered NBEV planning | Branch selection, not downstream correctness |
| `FIELD_CLARIFICATION` | target/path values | Run `field_extraction_replay` on the exact query | Current checked-out parser output and executed source |
| `PLANNING_STARTED` | target/path handoff | Run `workflow_handoff_replay` only if propagation is disputed | Value and paths actually handed to planning before external data work |
| `PATH_DISPATCH` | selected paths and missing/extra path results | Inspect the current dispatch table and path completion events | Whether the expected path function was selected/completed |
| `PLANNING_FUNCTION` | one path's result/error/fallback | Inspect or replay only that current path | Whether its planning mechanism produced the observed result |
| `RESULT_ASSEMBLY` | internal results versus response cards | Compare assembly input/output | Whether card loss or mutation starts during assembly |
| `SSE_ENVELOPE` | raw event order, think text and cards | Compare with internal result and adapter input | What the business API actually exposed |
| `VERIFIER_ADAPTER` | normalized stage/cards/fallback | Compare directly with raw SSE | Whether verifier extraction created the judged difference |
| `JUDGE_GAP` | not-fulfilled expectations | Check the expectation against the planning contract | Investigation boundary, not cause evidence |

## Investigation procedure

1. Establish the precise `JUDGE_GAP`; merge expectations only when one business defect explains them.
2. Compare `SSE_ENVELOPE` and `VERIFIER_ADAPTER`. Investigate the adapter only if they differ materially.
3. For target/path gaps, call `field_extraction_replay` using the current RunTrace query and contexts.
4. If parser output could explain the public value, call `workflow_handoff_replay` to distinguish extraction from later session/conversion changes.
5. If handoff is correct but output is wrong, follow only the observed `PATH_DISPATCH` → `PLANNING_FUNCTION` → `RESULT_ASSEMBLY` branch.
6. Reconcile all replay results with the same source revision and current public trace. If this is impossible, return `unresolved_reason` rather than a hypothesis.
7. During finalization, retain only ContextUnits that materially connect the finding to the current gap.

## Node: `REQUEST`

The current public payload and normalized request establish candidate message fields and contexts. They cannot show which field the business selected.

## Node: `CHAT_REQUEST`

`MarketingPlanningRequest.to_chat_request` selects the agent message before `user_text` and carries contexts. Inspect it only when transmitted fields compete.

## Node: `INTENT_RESOLUTION`

The resolver determines whether this request enters NBEV planning. Its label alone cannot explain a downstream numeric or card defect.

## Node: `FIELD_CLARIFICATION`

Current extraction plus session merge determines target/path strings. `field_extraction_replay` verifies the parser branch; session behavior needs the handoff replay.

## Node: `PLANNING_STARTED`

This event is the first typed target/path handoff to planning. `workflow_handoff_replay` stops here so field propagation can be tested without external planning data.

## Node: `PATH_DISPATCH`

The normalized path selects one current planning function. Inspect it only for missing, extra or failed path output.

## Node: `PLANNING_FUNCTION`

Each path consumes the handoff target and may access external data or fallback logic. Its result is relevant only when the same path is active in the current trace.

## Node: `RESULT_ASSEMBLY`

Assembly combines completed path results into response data. Compare its input/output before attributing missing cards here.

## Node: `SSE_ENVELOPE`

The public stream exposes reasoning, cards and lifecycle events. It is the business boundary against which adapter output is checked.

## Node: `VERIFIER_ADAPTER`

The adapter compacts raw SSE into stage/card/fallback fields. A defect here requires a material raw-versus-normalized difference.

## Node: `JUDGE_GAP`

Not-fulfilled expectations define what must be investigated. They do not establish which business node caused the gap.

## Known evidence boundary

The public SSE provides the deployed behavior but not a correlated internal span for every function call. A checked-out replay proves current-revision behavior. If deployment revision, request, session state, or an LLM-dependent branch cannot be aligned with the original trace, the replay cannot by itself identify the original hidden cause.
