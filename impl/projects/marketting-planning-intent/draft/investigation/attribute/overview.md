# marketting-planning-intent Attribute investigation

## Scope

The business source of truth is the repository configured by `source_project`, currently revision `222c3d88c05d0c55735cab3709485d1d633c6335`. This package covers the single-turn `/api/v1/marketing-planning/intent-recognition` path only. Planning execution, streaming cards, and downstream NBEV calculations are outside this role boundary.

The Judge gap starts an investigation; it does not prove which business stage is defective. A valid finding must connect the same current query across the public RunTrace, one actual business branch, and the output difference. Static source presence, a rule no-match, or a plausible prompt weakness cannot establish a finding by itself.

## Confirmed topology

The endpoint converts the public request into `ChatRequest`, calls `run_intent_only`, and returns an envelope containing `intent_code` and `nlu_info`. The resolver first evaluates deterministic rules. It uses the configured LLM when no rule matches, and may use it to supplement missing NBEV fields. The verifier adapter then extracts the public response before Judge evaluates it.

The companion trace document contains the operational index, branch selection signals, verification actions, and evidence boundaries. It is the entry point for runtime attribution.

## Verification assets

- `marketing_intent.rule_stage_replay` executes the checked-out deterministic recognizer. `matched=false` selects the LLM fallback branch; it is not a defect conclusion.
- `marketing_intent.resolver_replay` executes the checked-out resolver and reports whether the path was rule-only, LLM fallback, or rule plus LLM supplementation.
- The current `RunTrace` remains authoritative for the public HTTP result and verifier extraction. Replays do not replace it.

## Rejected shortcut

The previous Draft probe copied the production regex and added locally invented “relaxed” regexes. It thereby treated agreement with a candidate replacement rule as proof that production rule coverage was the cause. That circular path has been removed. A repair idea may be evaluated later, but it cannot serve as evidence for the original cause.

## Known limits

The business service does not expose a case-level distributed trace identifying every internal LLM prompt/model event. Resolver replay can reproduce the configured path, but stochastic LLM disagreement across invocations cannot prove the original invocation’s internal cause. If the public result and replay disagree and no original internal record is available, the conclusion must remain unresolved at that boundary.
