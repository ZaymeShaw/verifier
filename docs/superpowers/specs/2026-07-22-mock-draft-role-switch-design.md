# Mock Draft Role Switch Design

## Objective

Complete the Mock Draft integration defined by `spec/alg/investigate.md` without
introducing a Mock-specific runtime switch. A project operator changes only
`verifier.roles.mock.draft.enabled`; Role code, candidate Context and candidate
Tools then resolve as one active Mock implementation bundle, exactly like
Attribute.

## Runtime switch

The canonical switch is:

```yaml
verifier:
  roles:
    mock:
      draft:
        enabled: true
        module: draft/mock.py
```

All runtime consumers derive the active variant from the same project Role
configuration:

- the project Role loader chooses `mock.py` or `draft/mock.py`;
- the shared Role asset resolver chooses production or candidate paths;
- mandatory Mock Context loading consumes the resolved Context assets;
- the Role Tool loader consumes the resolved Tool assets.

Mock must not require a second runtime source, scenario or frontend flag. Static
`role_assets` mappings describe installable dependencies and promotion targets;
they are not additional operator switches.

The YAML truth source is `verifier.roles.<role>.draft`. The project resolver
materializes that canonical section into the existing `ProjectSpec.<role>_draft`
compatibility view consumed by the common loader. Mock must reuse the same
resolved view and loader path as Attribute; it must not parse YAML independently
or add a second switch representation.

## Production without promoted Mock assets

A Role asset may have a candidate path while its production path does not exist
yet. With Draft disabled, the common resolver returns that production selection
with `available=false`. Common Context and Tool consumers ignore unavailable
production selections when every applicable asset is still candidate-only in
physical availability, so the Role receives an empty candidate capability set.
They must still fail for a declared, previously available production dependency
that becomes unreadable during an active run. This is the empty-asset Production
special case described by the Draft protocol and preserves the existing
Production Mock behavior.

With Draft enabled, a declared candidate path is required to exist. Missing
candidate Role code, Context or Tool fails closed instead of silently falling
back to Production.

This availability rule belongs to the shared Role asset resolver and applies to
Attribute, Judge and Mock alike. It removes the need for a separate Mock-only
`candidate_only` runtime semantic.

## Data boundary

The Draft switch changes the active Mock implementation, not the comparison
data:

- `构建 Mock 用例池` invokes the active Mock implementation and therefore uses
  Draft code and candidate Context/Tools when enabled;
- `加载 Mock 数据集` remains a read-only load of persisted cases and does not
  invoke an LLM;
- Draft Loop Current and Draft continue to receive the same frozen cases.

Changing `runtime.mock_cases.source` or `default_scenarios` is not part of Role
switching and must not be required to activate Draft.

## Promote boundary

Promotion is not a runtime switch. After a separately authorized promotion it
moves the validated candidate Role/assets to their production paths and changes
the same canonical nested field from `true` to `false`.

The common promotion implementation must update the YAML truth source
`verifier.roles.<role>.draft.enabled`, so Attribute and Mock use the same path.
After the project is resolved, the existing `ProjectSpec.<role>_draft`
compatibility view remains the common loader input for both roles.

## Verification

1. Toggle only `verifier.roles.mock.draft.enabled` in a resolved DeerFlow spec.
2. Assert Production loads `DeerflowMock` with no unpromoted Mock Context/Tool.
3. Assert Draft loads `DeerflowMockDraft`, the candidate mandatory Context and
   the candidate validation Tool.
4. Exercise the `/api/mock_cases` service path with a stub LLM and prove the
   Draft prompt consumes the candidate Context in one generation call.
5. Assert `/api/mock_datasets` still reads persisted fixtures without an LLM.
6. Verify the same common switch behavior for Attribute remains unchanged.
7. Verify promotion planning/updating recognizes the canonical nested config.
8. Verify a missing production path plus an existing candidate path resolves as
   unavailable for Current, while a missing selected candidate fails closed.

## Non-goals

- No Live, MockCase or frontend transport schema change.
- No Draft-specific scenario taxonomy.
- No fixture preference for dynamic Mock generation.
- No automatic promotion.
