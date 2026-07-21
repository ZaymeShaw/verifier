# Intent-recognition business trace

## How to use this trace map

Start with the current case, not with a preferred cause. Compare the public request, raw API response, verifier-extracted output, reference contract, and Judge gap. Use the operational index to select the first node where two available observations can be compared. Follow only that branch deeply. A source file explains an observed result; it does not prove that the branch ran.

For a label mismatch, first compare `RESPONSE_ENVELOPE` with `ADAPTER`. If extraction is faithful, run `rule_stage_replay` on the same query. A match allows inspection of the deterministic branch; a no-match directs the investigation to `LLM`. Use `resolver_replay` only when it can distinguish these competing paths or reproduce the public result. For confidence or NBEV-field gaps, inspect the branch-specific field behavior rather than assuming that every intent type must populate planning fields.

## Operational index

| Node | Current-case signal | Decisive action | What the result can establish |
|---|---|---|---|
| `REQUEST` | `normalized_request`, original input, contexts | Compare the actual transmitted query/contexts with the case input | Whether the evaluated input reached the project boundary unchanged |
| `ENDPOINT` | HTTP status, raw response, endpoint metadata | Use the current RunTrace/API result; inspect endpoint source only after an observed envelope gap | Whether the public endpoint returned a usable result |
| `CHAT_REQUEST` | public payload fields versus business `user_message`/contexts | Compare request schema conversion with transmitted fields | Whether normalization selected a different message or context |
| `RESOLVER` | rule replay and resolver replay for the same query | Compare execution path and final internal result | Which broad business branch currently produces the internal result |
| `HOME_RULE` | rule replay returns a homepage label | Inspect the matched current rule and compare its output with public result | A deterministic homepage branch result, not overall API correctness |
| `CONTEXT_RULE` | completed-planning contexts plus an adjustment result | Replay with the exact contexts and inspect context predicates | Whether context-dependent adjustment logic changes the label |
| `STRUCTURED_RULE` | rule replay returns target/path/NBEV heuristic output | Inspect actual extracted values and the corresponding current functions | Whether deterministic extraction/heuristics produce the observed fields |
| `LLM` | rule replay no-match, or incomplete NBEV rule followed by resolver result | Run resolver replay and inspect prompt/source only for the active path | Current configured fallback/supplementation output; not the original stochastic invocation’s hidden reasoning |
| `INTENT_RESULT` | resolver result fields | Compare label/confidence/fields with raw `nlu_info` | Whether the business result changed before the response envelope |
| `RESPONSE_ENVELOPE` | raw `intent_code` and `nlu_info` | Compare with internal replay and adapter input | Whether response assembly loses or changes business fields |
| `ADAPTER` | extracted `intent`, confidence, raw intent, errors | Compare directly with raw response | Whether verifier extraction creates the judged difference |
| `JUDGE_GAP` | not-fulfilled expectations and expected/actual | Verify the expectation is in the single-turn contract before investigating it | The investigation boundary; not root-cause evidence |

## Investigation procedure

1. Establish the exact business gap at `JUDGE_GAP` and reject planning/SSE expectations outside this project.
2. Compare `RESPONSE_ENVELOPE` and `ADAPTER`. Stop at adapter extraction only if the raw and normalized values differ.
3. Execute `rule_stage_replay` with the current query and exact available contexts.
4. If a rule matched, inspect only its active branch (`HOME_RULE`, `CONTEXT_RULE`, or `STRUCTURED_RULE`) and connect its actual fields to the public result.
5. If no rule matched, or NBEV fields invoke supplementation, execute `resolver_replay` and investigate `LLM`; do not label the rule no-match as a gap.
6. Compare replay and public evidence. If they cannot be aligned to the same revision/input or stochastic behavior differs without original internal records, emit `unresolved_reason` instead of a cause.
7. Register only the ContextUnits that materially support the final conclusion during Attribute finalization.

## Node: `REQUEST`

The public payload may carry content in both `user_text` and `extra_input_params.agent_args.message.content`. Attribution must use what was actually sent in the current trace.

## Node: `ENDPOINT`

`app.api.router.intent_recognition` is the public non-streaming boundary. Service unavailability is infrastructure evidence, not evidence that an intent algorithm is wrong.

## Node: `CHAT_REQUEST`

`MarketingPlanningRequest.to_chat_request` prefers the agent message over `user_text` and passes configured contexts. This is the normalization point for competing-input explanations.

## Node: `RESOLVER`

`_resolve_intent_result` selects deterministic recognition, LLM fallback, or LLM supplementation. The resolver replay reports this current execution path.

## Node: `HOME_RULE`

Homepage regex matches are final and skip LLM supplementation. A replayed match can therefore distinguish this path from the fallback path.

## Node: `CONTEXT_RULE`

Adjustment intents depend on markers in prior contexts. Replaying without the original contexts cannot validate this branch.

## Node: `STRUCTURED_RULE`

Target/path extraction and the NBEV keyword heuristic can create an `nbev_planning` result. Missing target/path values may trigger LLM supplementation.

## Node: `LLM`

The configured model uses `INTENT_RECOGNITION_PROMPT`. Prompt text is explanatory evidence only after the current case is shown to take this branch.

## Node: `INTENT_RESULT`

The internal schema contains `intent`, `confidence`, `target_value`, and `path_types`. It does not define product/customer entities for every portrait intent.

## Node: `RESPONSE_ENVELOPE`

`run_intent_only` and the endpoint expose the internal result through `nlu_code`/`nlu_info`, then wrap it into the project response frame.

## Node: `ADAPTER`

The verifier adapter extracts normalized intent evidence from the raw response. A mismatch here is a verifier-project defect, not a business recognizer defect.

## Node: `JUDGE_GAP`

Judge output identifies what failed. It must be reconciled with the actual business contract before Attribute treats it as an in-scope gap.
