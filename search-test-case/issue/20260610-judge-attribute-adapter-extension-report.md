# 2026-06-10 judge attribute adapter extension report

## Scope

- Continue the judge/attribute process-evidence upgrade by extracting project-specific reconciliation and chain evidence into adapter hooks.
- Keep generic core free of `client_search` field semantics while still letting project adapters provide current-case semantic and chain context.

## Changes

- [x] Added generic adapter hooks in `impl/core/adapter.py`.
  - `build_judge_context(trace)` lets a project provide semantic-equivalence hints, boundary context, or current-case evidence to the judge prompt.
  - `reconcile_judge_result(trace, judge_result)` makes project post-judge reconciliation explicit while preserving the old `normalize_judge_result` compatibility path.
  - `build_attribute_context(trace, judge_result)` lets a project provide deterministic chain nodes and local evidence to the attribute prompt.
  - `normalize_attribute_result(trace, judge_result, attribute_result)` lets a project normalize attribution output without hardcoding project logic in core.

- [x] Wired hooks through generic runtime.
  - `impl/core/judge.py` includes `project_judge_context` in the judge prompt payload.
  - `impl/core/attribute.py` includes `project_attribute_context` in the attribute prompt payload.
  - `impl/core/pipeline.py` now loads the adapter once per judge/attribute call, passes project context into the LLM step, and applies the project reconciliation/normalization hook afterward.

- [x] Moved `client_search` evidence into project adapter hooks.
  - `impl/projects/client_search/adapter.py` now exposes semantic-equivalence rules, field patterns, downstream search status, and boundary instructions through `build_judge_context`.
  - It exposes request normalization, parser output, routing match evidence, downstream probe evidence, judge boundary decision, conditions, matched patterns, and source config paths through `build_attribute_context`.
  - The existing downstream-boundary correction and condition canonicalization behavior is preserved under `reconcile_judge_result`.

## Check conclusions

- Generic core now controls only the hook mechanism and prompt plumbing.
- Project-specific fields such as `query_logic`, `conditions`, `matched_level`, and concrete client-search fields remain in the `client_search` adapter/project documents.
- The implementation follows the process-evidence demand: judge/attribute can receive current-case evidence from deterministic project hooks without adding rule-like overfit detection in core.

## Verification

- [x] `python -m compileall -q impl` passed.
- [x] `python -m impl.cli projects` returned `QA` and `client_search`.
- [x] `client_search` mock `run-chain` for `有生存金未领取的客户` returned `judge_verdict=correct`, downstream boundary flags preserved, and `check.passed=true`.
- [x] QA mock `run-chain` returned `judge_verdict=correct` and `check.passed=true`.
- [x] `client_search` mock batch with two cases returned `total=2`, both verdicts `correct`, and `check.passed=true`.
