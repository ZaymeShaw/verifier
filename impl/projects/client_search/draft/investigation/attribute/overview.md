# client_search Attribute investigation

## Scope

This package describes the business request path behind `POST /api/v1/client_search_query_parse_no_encipher`. It is intended to help Attribute decide which business material or verification capability to load after Judge has identified a concrete gap. It does not contain a precomputed attribution for any evaluation case.

The investigated API parses natural-language customer-search intent into structured conditions. Its source explicitly states that it does not execute customer search. A verifier-side downstream search probe may test result-set behavior when that separate service is available, but that probe is not part of the parser's core execution path.

## Confirmed business path

At source revision `2859c55f71ec8a1e9687c73b40cc0987d81d379c`:

1. The FastAPI endpoint accepts `ParseApiRequest` and calls `QueryRouter.route_with_peeling`.
2. The router normalizes the query and runs enabled L1 and L2 extractors. If L2 produces confirmed conditions, current code discards all L1 conditions.
3. The L3 semantic-cache execution block is commented out in the inspected revision. It must not be proposed as a current case cause without different runtime evidence.
4. If no confirmed conditions remain, the router may return weak bare-value candidates or call L4 depending on query shape and settings.
5. Both rule and LLM paths apply field/value validation and summary normalization before returning `ParsedQuery`.
6. The endpoint applies date-format normalization, builds an intent summary, removes unsupported conditions, converts age conditions to birthday form and serializes `ParseApiResponse`.

The graph and its companion document preserve this topology with stable node IDs and exact EvidenceRef links.

## Available investigation capabilities

- `client_search.field_capability` returns the configured field/operator/value contract. It does not execute a case.
- `client_search.rule_verify` returns a small relevant mapping/rule subtree. It is static configuration evidence and does not prove that a case traversed the returned rule.
- `client_search.search_api` observes the current public parser boundary for one query.
- `client_search.case_route_replay` executes the real L2 matcher and returns its normalized query, matched rule/pattern, capture groups and generated condition. Its scope is only the L2 matcher; it does not prove router selection or another route's behavior.
- No current Tool observes all L1 inputs, the L2 override, L4 generation/conversion/validation, endpoint post-processing and downstream search for one correlated request. These gaps remain explicit in the trace artifacts.

## Rejected shortcuts

- A config rule's existence does not prove it fired.
- A generally imperfect source file does not prove it caused the current business gap.
- Verifier's own run trace is not a substitute for the business system's L1/L2/L4 execution trace.
- A successful parse response does not prove downstream customer-result correctness.

## Current boundary

The code topology and static configuration sources are traceable. For cases whose public API response reports `matched_level=2`, the L2 replay now provides per-case rule, capture and condition facts. L1/L4 stage internals, endpoint post-processing mutations and downstream result-set behavior remain outside that replay and require separate evidence.
