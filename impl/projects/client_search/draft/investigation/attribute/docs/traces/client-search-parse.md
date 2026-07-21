# client_search parse business flow

This document explains the business data carried by `client-search-parse.mmd`. The same-name `client-search-parse.trace.json` is the structured index used by validation and Solidify. Source topology explains responsibility; only a case observation or faithful replay can prove that a node produced a particular value.

## How to use this trace map

Start from the Judge's not-fulfilled gap and the public `response.parse_api_response`. Follow the branch identified by `router.matched_level` backward until the earliest data value that differs from the expected business value. Read the cited EvidenceRef to understand the responsible mechanism, then use the associated Tool when one exists. If the needed row has an observation gap, stop at the last observed data value and keep the conclusion unresolved.

The `.trace.json` sidecar supplies stable node/data/ref relationships; it is not a repair recipe or a candidate implementation plan.

## Operational index

| Node | Input data IDs | Output data IDs | Observe or verify | Boundary |
|---|---|---|---|---|
| `REQUEST` | - | `request.parse_api_request` | `client_search.search_api`; `parse-endpoint` | Public request only |
| `ENDPOINT` | `request.parse_api_request` | `endpoint.user_query`, `endpoint.trace_id` | Public request; `parse-endpoint` | Router-call snapshot absent |
| `ROUTER` | `endpoint.user_query`, `endpoint.trace_id` | `router.raw_query` | `router-pipeline` | Source responsibility, not a case observation |
| `NORMALIZE` | `router.raw_query` | `router.normalized_query` | L2 `case_route_replay`; `router-pipeline` | Replay covers L2 boundary only |
| `L1` | `router.normalized_query` | `l1.conditions` | `router-pipeline` | Per-case L1 output is not exposed |
| `L2_PATTERN` | `router.normalized_query` | `l2.matched_rule`, `l2.matched_pattern`, `l2.matched_text` | `case_route_replay`; `rule_verify`; `l2-match-execution` | Requires API-confirmed L2 route |
| `L2_CAPTURE` | `l2.matched_rule`, `l2.matched_pattern`, `l2.matched_text` | `l2.capture_groups` | `case_route_replay`; `l2-capture-extraction` | L2-local observation |
| `L2_CONDITION` | `l2.capture_groups` | `l2.confirmed_conditions` | replay exposes confirmed output | L2-local observation |
| `OVERRIDE` | `router.normalized_query`, `l1.conditions`, `l2.confirmed_conditions` | `router.deterministic_merged_conditions` | `router-pipeline` | No current pre/post override probe |
| `L4_PROMPT` | `router.normalized_query` | `l4.rag_prompt`, `l4.has_intents` | `l4-parser-source`; proposed `l4_route_replay` | Exact deployed prompt/config unobserved |
| `L4_MODEL` | `l4.rag_prompt` | `l4.raw_response`, `l4.finish_reason` | proposed `l4_route_replay` | Raw response unavailable now |
| `L4_CONVERT` | `l4.raw_response` | `l4.converted_conditions`, `l4.query_logic` | proposed `l4_route_replay`; `l4-parser-source` | Conversion snapshot unavailable now |
| `L4_MERGE` | `l4.converted_conditions`, `router.normalized_query` | `l4.l2_merge_candidates`, `router.l4_merged_conditions` | proposed `l4_route_replay`; `router-pipeline` | Candidate recall/merge snapshot unavailable now |
| `PRE_VALIDATE` | `router.deterministic_merged_conditions`, `router.l4_merged_conditions` | `router.pre_validation_conditions` | `router-pipeline`; proposed replay | One branch supplies the input; name-specific transformation snapshot unavailable |
| `VALIDATE` | `router.pre_validation_conditions` | `router.validated_conditions`, `router.summary_normalized_conditions`, `router.matched_level`, `router.matched_patterns`, `router.rewritten_query` | `search_api`; `field_capability`; proposed replay | Public route metadata is visible; pre/post validation is not |
| `FORMAT` | `router.summary_normalized_conditions`, `router.matched_level`, `router.matched_patterns`, `router.rewritten_query`, optional `l4.rag_prompt` | `endpoint.debug_pattern_text`, `endpoint.date_normalized_conditions`, `endpoint.intent_summary`, `endpoint.filtered_conditions`, `endpoint.age_converted_conditions` | final `search_api`; endpoint EvidenceRefs | Intermediate formatter snapshots absent |
| `RESPONSE` | `endpoint.age_converted_conditions`, `endpoint.intent_summary`, `endpoint.debug_pattern_text`, `router.matched_level`, `router.rewritten_query` | `response.parse_api_response` | `search_api`; `RunTrace.extracted_output` | Does not include downstream customer search |

## Investigation procedure

1. Fix the scope to the not-fulfilled expectation and confirm whether it concerns parser output or downstream customer results; this map covers parser output only.
2. Reproduce `RESPONSE` with the exact business query when the existing public observation is not trustworthy. Record final conditions, summary, `matched_level`, matched metadata and source/runtime identity.
3. For `matched_level=2`, replay the same query and compare `router.normalized_query` → `l2.matched_pattern` → `l2.capture_groups` → `l2.confirmed_conditions` with the public condition.
4. For `matched_level=4`, do not infer that the model omitted a field merely from final output. The missing value can originate at prompt retrieval, model generation, JSON conversion, router merge/validation or endpoint filtering. Until `client_search.l4_route_replay` or an equivalent business trace supplies those snapshots, report only the last proven boundary.
5. Use source/config EvidenceRefs to explain an already observed transition, not as proof that it occurred in this case. Register decisive ToolResults as ContextUnits for Attribute finalization and Reviewer inspection.

## Node: REQUEST

`request.parse_api_request` is the exact public business input. Verifier metadata outside the request is not business execution evidence.

## Node: ENDPOINT

The endpoint extracts `endpoint.user_query` and `endpoint.trace_id`, invokes QueryRouter, and later performs response formatting. `parse-endpoint` establishes this responsibility.

## Node: ROUTER

`QueryRouter.route_with_peeling` accepts `router.raw_query` and orchestrates the active parser branches. The graph intentionally omits the commented L3 block because it does not execute in the inspected revision.

## Node: NORMALIZE

Normalization produces `router.normalized_query`, the shared input to deterministic parsing and L4. A defect claim needs a before/after value, not just the existence of normalization code.

## Node: L1

L1 produces `l1.conditions`. Current Tools do not expose that output for a case, so the later L2 override mechanism cannot be blamed without an additional observation.

## Node: L2_PATTERN

The real matcher produces `l2.matched_rule`, `l2.matched_pattern` and `l2.matched_text`. `case_route_replay` can observe them; `rule_verify` only confirms static configuration.

## Node: L2_CAPTURE

Capture extraction converts the selected match into `l2.capture_groups`. This is the earliest useful value for defects where the wrong substring becomes a condition value.

## Node: L2_CONDITION

The matcher builds `l2.confirmed_conditions`. The later L4 merge does not consume this output directly; it performs a separate candidate recall after L4 parsing.

## Node: OVERRIDE

The router produces `router.deterministic_merged_conditions` after applying the L2-over-L1 rule. Source proves the replacement mechanism exists; a case still needs the L1, L2 and merged values.

## Node: L4_PROMPT

`Level4LLMParser` builds `l4.rag_prompt` and `l4.has_intents`. Prompt-like public diagnostics are insufficient unless they preserve the exact deployed prompt, system instruction, model configuration and case identity.

## Node: L4_MODEL

The configured model returns `l4.raw_response` and `l4.finish_reason`. Without these values, final missing conditions cannot be assigned specifically to model generation.

## Node: L4_CONVERT

JSON extraction and `_convert_conditions` create `l4.converted_conditions` and `l4.query_logic`. A field present in raw output but absent here would locate a conversion defect rather than a generation defect.

## Node: L4_MERGE

After L4 conversion, the router may call `_recall_level2_candidate_conditions` again with `merge_to_llm_only=True`, producing `l4.l2_merge_candidates`, and combine them with `l4.converted_conditions` into `router.l4_merged_conditions`. The earlier general recall result is not used here. This stage depends on runtime configuration and requires a faithful replay or business trace.

## Node: PRE_VALIDATE

Both active branches pass through explicit full-name enforcement and name-candidate materialization, producing `router.pre_validation_conditions` immediately before common validation. This node prevents the override or L4 merge output from being mislabeled as the direct validation input.

## Node: VALIDATE

Router validation produces `router.validated_conditions` and `router.summary_normalized_conditions`, then returns `router.matched_level`, `router.matched_patterns` and `router.rewritten_query`. `field_capability` proves the field contract but not that validation removed this case's condition.

## Node: FORMAT

The endpoint builds `endpoint.debug_pattern_text` (L4 prompt or first deterministic pattern), then sequentially produces `endpoint.date_normalized_conditions`, `endpoint.intent_summary`, `endpoint.filtered_conditions` and `endpoint.age_converted_conditions`. Final output alone cannot distinguish these transformations when a condition disappears.

## Node: RESPONSE

`response.parse_api_response` is the public parser boundary seen by Judge. Downstream customer retrieval is deliberately excluded rather than represented as a verifier-owned business node.
