# Field Key-Index Investigate Notes (2026-08-12 simulate)

## Selection status
`unresolved` — validate_key_index_experiment: investigate PASS, simulation PASS, selection FAIL (no shortlist / no loop_evidence).

## Honest blockers (field Collection)
1. Threshold conflict: no candidate meets top8_recall≥0.85 AND irrelevant_rejection=1.0 on both development and holdout.
2. Holdout paraphrases (另一半/家里人/保的是谁/做哪一行/收信) are not present as source phrases in field_definitions/enums/mappings; injecting them would be answer pollution.
3. Business nouns used in Auth-OFF badcases (关爱客户/有钱/金凤/盘客) are only partially navigable via field Index:
   - projection omits examples/notes
   - 2-char stem matching gap (`有钱` vs `有钱客户`)
   - 金凤 is in abbrname/planfullname enums Collection, not field definitions
4. Evidence declares `key_live` for enhanced_rules / value_mappings consumers, but those Collections have **no** selected Key-Index experiment/Manifest registration — Investigate→Solidify consumption gap.

## AUTHORITY_GATE
Prior failure: `--tool-inputs` keyed as bare `condition_compare` while requirement/tool_id is `client_search.condition_compare`.
Reran `validate_investigation.py --execute-tools` with correct key → succeeded; stale gate feedback archived/cleared.

## What was NOT done (correctly)
- No `selected` claim
- No Solidify of field key-index
- No Production Judge / frozen expected_status edits
- No Draft skill edits
- No Loop auto-promotion; iteration 1 still awaiting harness review decision/route
