# Draft Candidate-Only Role Assets Design

## Objective

Complete the missing Mock/Judge Solidify path in the Draft protocol. A candidate Role may consume ContextUnit, Tool, and investigation assets without changing a Production Role that has not adopted those assets. Production's unadopted state is represented as an empty asset set and remains behaviorally equivalent to the previous implementation.

## Configuration

Extend `RoleAssetMapping` with one explicit field:

```yaml
candidate_only: true
```

The field defaults to `false`, preserving every existing project configuration.

A candidate-only mapping remains fully promotion-addressable:

```yaml
- asset_id: mock_investigation
  kind: investigation
  enabled: true
  candidate_only: true
  roles: [mock]
  production_path: investigation/mock
  candidate_path: draft/investigation/mock
  replace: true
```

`production_path` is the future promotion target, not evidence that Current already owns the asset. A candidate-only mapping must declare a non-empty `candidate_path` under `draft/`.

## Resolution semantics

For an enabled mapping whose role matches:

| Role mode | `candidate_only=false` | `candidate_only=true` |
|---|---|---|
| Production Current | select `production_path` | omit the mapping, producing no asset |
| Draft Candidate | select `candidate_path` when declared, otherwise `production_path` | require and select `candidate_path` |
| Promotion planning | use the configured production/candidate paths | use the configured production/candidate paths |

Missing or invalid candidate assets fail closed when Draft is selected. Production does not probe, register, embed, or load a candidate-only asset.

## Role-specific consumption

The common loader only resolves authorized assets. Each Role keeps its own consumption strategy.

### Mock

- Open-ended initial generation deterministically loads the mandatory business ContextUnit before calling the model.
- A caller-provided concrete intent remains the complete fact contract and is not enriched from project Context.
- Multi-turn continuation uses the established intent, user context, visible transcript, and live feedback; it does not reload the complete business ContextUnit on every turn.
- Candidate validation uses the Mock VerifiableTool as a Solidify/Loop gate. Mock does not inherit Attribute Search/Load, dynamic ContextUnit, Finalization, or Reviewer.

### Judge

- Judge may deterministically load its own mandatory acceptance ContextUnit before evaluation.
- Current case input/output/reference remain explicit evaluation inputs.
- Judge does not inherit Attribute investigation or evidence-closure behavior.

This change provides the asset isolation primitive for both roles; the DeerFlow implementation in this change enables it only for Mock.

## DeerFlow Mock completion

Enable the three existing candidate-only Mock mappings:

- `mock_investigation`;
- `mock_investigation_context_builder`;
- `mock_business_input_validator`.

Production DeerFlow Mock resolves these to an empty set. Draft DeerFlow Mock resolves the candidate investigation package, builds the derived NBEV user-goal ContextUnit, and exposes the candidate validator for Solidify/Loop checks. Raw repository material is not injected directly.

## Promotion

Promotion keeps the existing deterministic move/copy behavior. After applying a candidate-only asset:

- material moves or copies from `candidate_path` to `production_path`;
- the promoted mapping must no longer be candidate-only;
- the Role Draft switch is closed by the existing promotion flow.

Promotion remains user-authorized and performs no model call.

## Verification

1. Config parser accepts `candidate_only`, rejects it without `candidate_path`, and defaults existing mappings to `false`.
2. Production resolution omits candidate-only assets even when the future `production_path` exists.
3. Draft resolution requires and selects the candidate path.
4. Production mandatory Context loading returns `None` when it has no other assets or adapters.
5. Draft Mock loads exactly the derived Mock business ContextUnit with a deterministic test embedding provider.
6. Production Mock prompt and behavior remain unchanged; Draft open-ended generation observes the ContextUnit.
7. Mock validator smoke and focused Draft/Live regressions pass.
8. Promotion check includes candidate-only assets and plans removal of the candidate-only state.
9. Run a frozen DeerFlow Production/Draft comparison and, when external execution is permitted, a real `run_chain` A/B.

## Non-goals

- No Attribute Search/Load or Reviewer behavior for Mock/Judge.
- No new Mock, Judge, Live, ContextUnit, or Tool result schema.
- No automatic promotion.
- No change to stored fixtures or promotion-only unseen cases.
- No repeated full ContextUnit injection on each multi-turn Mock step.
