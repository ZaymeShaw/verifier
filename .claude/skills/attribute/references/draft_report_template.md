# Draft Attribute Comparison Report

## Scope

- Project: `<project_id>`
- Current implementation: `<impl/projects/<project>/attribute.py or core fallback>`
- Draft implementation: `impl/projects/<project>/draft/attribute.py`
- Mock data source: `<draft config frozen mock dataset>`
- Config: `<draft config path>`

## Result

Conclusion: draft better / draft not better yet / blocked

## Summary table

| Case | Judge status | Current strength | Draft strength | Draft improvement | Risk |
| --- | --- | --- | --- | --- | --- |
| `<case_key>` | `<status>` | `<strength>` | `<strength>` | `<evidence/link localization delta>` | `<overfit/inflation/missing evidence risk>` |

## Evidence quality

- Current gaps:
  - ...
- Draft improvements:
  - ...
- Remaining blockers:
  - ...

## Anti-overfit check

- Mock dataset unchanged during loop: pass / fail
- User-requested config changes applied: none / listed below
- Case id / sample index hardcoding: pass / fail
- Current-case-only evidence: pass / fail
- Canonical standard preserved: pass / fail
- Missing evidence does not produce strong: pass / fail
- Fulfilled cases not forced into failure: pass / fail

## Decision

Promotion recommendation: yes / no

Required follow-up before promotion:

- [ ] ...
