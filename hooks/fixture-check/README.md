# Fixture Check

`fixture-check` verifies that standard schema fixtures can drive selected function checks.

Scope:

- Standard schema fixtures and project business fixture scenarios.
- Function behavior under valid typed schema inputs.
- Cross-layer materialization checks, such as trace/judge/attribute to table rows.

Out of scope:

- `normalize_*` compatibility checks.
- Dirty, legacy, or half-structured payload hydration.
- Exhaustive per-function test coverage.

Run:

```bash
python -m pytest verifier/hooks/fixture-check
```
