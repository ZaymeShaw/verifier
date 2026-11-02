# v2 shared-output validation tests

## Scope and execution

Owned test files only: `tests/test_process_unit_output.py`, `tests/test_process_criterion_checks.py`, and new `tests/test_process_v2_rules.py`. No production code or other tests edited. This report is the explicitly requested handoff artifact.

Read `AGENTS.md`, implementation task, `demand/expectations.md`, complete v2 `spec/alg/expectations.md`, relevant six-axis protocol/implementation documentation, and output abstraction. All test cases are explicitly synthetic; none are represented as frozen real business/model runs. Tests call actual `build_units`, `expand`, `validate_submission`, provenance/block generation, result binding and aggregation.

Removed the retired ProcessAssessment/_expand and commitment attachment test paths, replacing their guards with current short-C coverage, schema, provenance and rule tests. Existing default omissions, strict types, no-extra-fields, fail/problem coverage, atomic aggregation and reference guards remain.

Interpreter: `/Users/xiaozijian/miniconda3/envs/agno/bin/python`. Runs use existing `offline_tests.py` plus a stricter outer guard replacing `socket.socket.connect`, `connect_ex` and `socket.create_connection` with an unconditional assertion before invoking the runner. No real model or network traffic permitted.

First run: **208 passed, 5 failed, 0 collection errors** (0.49s). Second run after additional boundary cases: **220 passed, 6 failed, 0 collection errors** (226 total; 0.49s). Final rerun after migrating the off-map action helper fully to current `required_units`/necessity/shared submission: **220 passed, 6 failed** (0.41s). `compileall` passed for all three owned test files. Production files were being edited concurrently. No xfail/skip or weakened expectations added. The six failures below are left as ordinary regression tests for coordinator fixes; they must not be deleted merely to turn the suite green.

## Coordinator handoff: observed failures

1. **Optional nested Necessity silently discards extra fields.**
   - Test: `test_process_v2_rules.py::test_necessity_types_enums_extra_fields_and_nonblank_fact_remain_strict[invented-x]`.
   - Add `invented: "x"` to otherwise valid `units[0].necessity`. Shared validator accepts it and Pydantic drops it.
   - Expected: strict schema rejection (`ValueError`), just like extra fields in rules/checks/blocks. Requirement explicitly preserves strict extra-field guards.
   - `UnitJudgment.necessity` currently uses `Optional[Necessity]`; generated schema uses `anyOf`. Inspect shared enforcement of optional nested dataclasses before changing process logic.

2. **Escaped JSON pointer cannot resolve legal format-field quote.**
   - Test: `test_process_v2_rules.py::test_message_tool_and_format_blocks_resolve_escaped_nested_quote_paths`.
   - A real `dossier_blocks` inventory contains one message, one tool, full format and field, not recursive leaves. Format property is `a/b~c`; relative quote pointer `/properties/a~1b~0c/description` references a verbatim string containing newline/quotes.
   - Actual: `ValueError: ... 摘录未逐字出现在声明的位置 B2/properties/a~1b~0c/description`.
   - Block generator emits escaped pointer names, but shared `resolve_node_path` currently splits without decoding `~1`/`~0`. Simple nested paths work. Expected legal pointer resolves and retains full absolute original path in problem.expected.

3. **Quote.path nullable contract differs from assignment.**
   - Test: `test_process_v2_rules.py::test_nullable_empty_quote_path_selects_the_block_root[None]`.
   - Assignment explicitly says coordinator is adding `Quote.path Optional[str]` default `''`; current implementation is `path: str` with allow_empty metadata. Explicit empty and omission pass; null is rejected.
   - Await coordinator decision/implementation; test preserves the requested Optional contract rather than quietly changing it. If nullable was not intended, clarify the assignment; no production fallback is added here.

4. **Malformed long-form program provenance raises KeyError, not protocol ValueError.**
   - Tests: `test_process_criterion_checks.py::test_long_form_provenance_must_resolve_to_existing_demand_or_this_obligation[obligation:other]` and `[invented]`.
   - A short-C submission whose program criterion table resolves to an unknown obligation/namespace reaches `bind_results.text` before provenance checking and crashes with `KeyError('other')` / `KeyError('invented')`.
   - This is invalid program material, not model-generated long IDs. The old guards rejected unidentified refs; migrated guards require an intentional validation error rather than an uncaught lookup failure. Existing unknown E checks already raise ValueError.

5. **An existing local issue can be misused as a self-upstream reference.**
   - Test: `test_process_v2_rules.py::test_known_upstream_issue_cannot_reference_the_same_unit_it_is_supposed_to_explain`.
   - Build an actual synthetic `context_memory` failure record with `issues_for`; submit input_invalid for exactly the same `(axis_id, obligation_id, link_id)` and cite that existing issue.
   - Actual: shared `validate_submission` accepts it, checking only existence and `attribution == local`. Expected: reject the self-reference; it is not upstream evidence.
   - A later `validate_issue_references` has a self-reference check, but the shared entry validator currently does not. This unit regression protects the shared validation contract; distinct prior upstream units remain accepted.

## Verified boundaries

- E, obligation and design source preservation; all rule/condition/exception quotes kept in expected, problem and summary.
- Full block inventories and per-block reviews; intentionally skipped applicable rule remains inspectable (coverage is not semantic recall).
- Model actual-input scope, tool/planning/context execution scope, collected/reference versions insufficient for pass/fail, receiving-call ownership.
- Verbatim quotes, unknown/wrong blocks, exact C coverage, short D problem references, individual missing reasons, failed-rule problem coverage.
- Candidate satisfied (cache/equivalent path) discharged without issue; required action cannot use not_applicable; unknown retains unit and missing reasons; required unmatched becomes unresolved issue, not default planning fault.
- Existing localized upstream issue accepted; missing/unresolved upstream issue rejected; untested aggregation retained. Dependent input-invalid model unit does not exempt an independent no-fabrication unit; sound composition still exposes the invalid-input unit.
- Context delivery loss uses actual dossier-generated proven source (`execution`) and actual received message (`actual_input`), preserving both endpoints. Identical quote text at different locations/sources/scopes gets distinct provenance identity.
- Legal optional omissions preserved without mutating input; required blocks and strict checks/rules/properties retained.

## Reproduction

```bash
/Users/xiaozijian/miniconda3/envs/agno/bin/python - <<'PY'
import runpy, socket, sys
def offline(*args, **kwargs):
    raise AssertionError('offline unit tests prohibit every network connection')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = offline
sys.argv = ['offline_tests.py', '-q', 'tests/test_process_unit_output.py',
            'tests/test_process_criterion_checks.py', 'tests/test_process_v2_rules.py', '--tb=short']
runpy.run_path('report/expectations-20261006/expectations-v2-impl-20261007/offline_tests.py', run_name='__main__')
PY
```

No whole-repository or real-model validation claimed by this worker; these are shared-output unit/protocol tests.
