# client_search Judge investigation

## Scope

This package defines the product-level business expectation, the parser Live
boundary, and the authority investigation hand-off required to judge
client-search output. It does not contain expected answers for individual
cases.

## Proposed boundary

The user-facing goal is to retrieve the customer population described in a
natural-language request. The Live component evaluated here controls the
translation into downstream-consumable query semantics. It does not control
whether matching customer records exist or whether an external service is
available.

The user-authored boundary source (`judge_boundary-template.md`) is registered
as normative evidence (`project-judge-boundary-source`). It confirms the
responsibility boundary (database absence is judged by the business system
capability boundary; parser-controlled transformation errors are in scope) and
declares the trust model (M1): configuration/enum materials serve as proxies of
the downstream capability space, so their space statements are positioned
`inlive_boundary` (material-positioning.md §4/§5).

## Authority investigation hand-off

The investigation layer investigates per material. The frozen
`docs/authority-investigation-report.json` registers, for each business
material, its capability declarations (MaterialDecision: which business items
the material directly decides under which conditions), the connections between
materials, and the coverage gaps.

Coverage gaps are deterministic facts that no material alone decides the given
business item × condition. They are not conclusions and carry no
resolved/unresolved status:

- semantic-mapping-authority: a business-approved spoken-language normalization
  requires a governed glossary or business confirmation.
- query-form-equivalence-authority: result-set equivalence requires a fixed
  data-snapshot dual-query check or a business-confirmed closed rule.

Two earlier gaps are closed in this round: enum-value-authority (config/enum
materials are registered as `inlive_boundary` under the user-declared trust
model M1 and decide the reachable value space) and evaluation-boundary-authority
(the user-authored boundary source is registered as `normative_rule`).

At runtime the Judge resolves authority questions on the spot via
`authority.resolve` inside the materialized evidence space: when a
decision_question hits a material conflict or a capability/responsibility
boundary point, a resolved conclusion is consumed by its conclusion kind and an
unresolved one yields not_evaluable (insufficient basis) together with the
required-evidence list. Gaps are closed by later, manually triggered
investigation rounds; runtime never writes back into the investigation layer.

The remaining gaps are deliberate. Behavioral statements of internal
configuration (parse rules, normalization choices, time conversion) still prove
current system behavior only; space statements act as boundary proxies under the
registered trust model (material-positioning.md).

## Incremental refresh 2026-08-17

Business source moved `b4ffbb6` → `fa0ef7a`. This round only re-read the four
changed parser materials. Unrelated gaps, Key-Index experiments, the Judge
contract, and enum/planfullname space statements were left as-is.

- `familyInfo.familyclientbirthday`: field-definition intents now declare
  RANGE/GT/GTE/LT (the old MATCH-vs-RANGE conflict is gone). `enhanced_rules`
  still uses LTE and EXISTS; that residual operator mismatch remains bound to
  `query-form-equivalence-authority`.
- Address / claim-coverage / tax-preferred / cross-sell-claim changes are
  recorded as current conversion behavior, not new normative authority.
- `value_mappings` added 平安家医→臻享家医; `time_knowledge` added 本周/这周.

## Case-time applicability boundary

An unresolved project-level authority question does not make every case in its
dimension unevaluable. Judge must first use the current request, observable
actual output, a current-case oracle when one exists, closed field/value rules,
and deterministic comparison evidence.

Authority applies only when that direct evidence still leaves two outcome-
changing claims in conflict:

- enum authority requires a claim about the complete downstream value space,
  not a simple check that one explicit value or field was preserved;
- evaluation-boundary authority requires a real responsibility dispute between
  parser output and an external system, not an observable parser omission or
  extra condition;
- semantic-mapping authority requires at least two reasonable mappings that the
  current request and valid clarification cannot distinguish, not merely an
  unfamiliar word;
- query-form authority requires materially different query forms whose result-
  set equivalence is not already established by a closed rule, not a syntactic
  variation that the project comparator can decide.

When direct evidence is sufficient, the Judge must make a positive or negative
fulfillment decision without calling authority.resolve. When it is not, only
the evaluation point that depends on the unresolved question is blocked.
## Key-Index retrieval investigation

The field-definition Collection was evaluated through exact, lexical, and real Bailian embedding channels on separated development and holdout probes. The embedding channel improved paraphrase recall but regressed unsupported/irrelevant-query rejection. No candidate passed both frozen splits, so the experiment remains `unresolved`: it is registered as investigation evidence but is not selected or silently substituted with a full-Collection fallback. Further exploration must invalidate any observed holdout before tuning and freeze a new holdout before another selection attempt.

