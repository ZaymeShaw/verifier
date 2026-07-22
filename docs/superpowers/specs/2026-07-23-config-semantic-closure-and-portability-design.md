# Config Semantic Closure and Portability Design

**Date:** 2026-07-23

**Status:** approved for implementation design; implementation has not started

**Governing specifications:**

- `spec/adapter/config.md`
- `spec/adapter/config-prefixpath.md`

This design does not amend either governing specification. If implementation appears to require a conflicting rule, work stops and the conflict is reported instead of silently changing the specifications.

## 1. Objective

Complete the configuration migration so that moving verifier and its business projects to another machine requires changes only in the approved configuration chain:

- `impl/config.yaml` for public runtime configuration;
- `impl/projects/<project>/project.yaml` for formal project runtime configuration;
- `projects/<project>/project.yaml` for human knowledge routing;
- repository-root `.env` for machine-local values and secrets.

The migration must preserve current business behavior, especially LiveSchema, Judge, Check, Mock, interaction, and SSE behavior. The `20260721` branch is historical semantic evidence, not a target revision to restore.

## 2. Non-goals

- Do not restore the codebase to `20260721`.
- Do not change Judge, Attribute, Mock, Live, LiveSchema, or DeerFlow algorithms as part of configuration migration.
- Do not add a new top-level project configuration layer.
- Do not preserve permanent legacy aliases or dual-read fallbacks.
- Do not make hook, Skill, Draft, checklist, or migration-tool configuration part of project configuration unless its result is promoted into the formal runtime chain.
- Do not treat proposal files, reports, fixtures, manifests, or receipts as configuration authorities.

## 3. Why the current implementation looks this way

The current inconsistencies are transitional choices with identifiable origins. They must be understood before removal so that migration does not oscillate between designs.

### 3.1 `verifier.presentation` contains behavioral fields

On `20260721`, legacy `frontend_extensions` mixed UI values with values consumed by Mock, Live, Judge, Check, and interaction logic. The first canonical migration moved that container into `verifier.presentation` to remove project-local constants while preserving behavior.

That preserved execution, but it did not complete semantic classification. The current consumers prove the mismatch:

- Mock scenario and intent generation read presentation fields;
- interaction logic reads `interactive_scenarios`;
- QA Judge reads score dimensions and error taxonomy;
- Check reads forbidden markers;
- marketing-planning Live reads SSE event aliases and terminal events.

The governing specification says presentation fields must not change protocol, Judge, Attribute, ready, or runtime conclusions. Therefore the current placement is a migration bridge, not a valid terminal state.

### 3.2 `base_overrides` exists in the artifact writer

The legacy context store used a fixed repository path. During the writer migration, tests continued to monkeypatch `STORE_DIR` to temporary directories. `base_overrides` was added so those tests could write through the registered writer without building a matching runtime configuration context.

There is no established production requirement for one process to write the same artifact kind to unrelated roots. The override therefore solves test injection by weakening the production invariant. The terminal design removes the override and makes tests inject `PathRoots` or an artifact context.

### 3.3 Writer scanning covers only selected directories

The initial scanner intentionally avoided tests, Markdown, diagnostics, hooks, and migration helpers to prevent false positives. It used a positive list of formal producer directories.

That choice reduced noise but silently excludes future formal directories such as `impl/tools`. A repository-wide scan without classification would produce the opposite failure by treating diagnostics and independent tools as runtime producers. The terminal design scans repository-wide and classifies execution domains explicitly.

### 3.4 Full-gate subprocesses do not share the supplied environment

The main resolver and post-scan can receive a custom environment mapping, while subprocess gates inherit the actual process environment. No business requirement explains this difference; it is an incomplete propagation path. A run must freeze one effective environment and pass it through the complete gate chain.

### 3.5 Scaffold writes a formal configuration directly

The first scaffold implementation treated a generated file as a reviewable working-tree draft: a human could inspect the diff before committing or running it. Later protection prevented overwriting an existing human-edited file, but a newly created file remained immediately visible to the runtime loader.

The terminal workflow separates generation from authority: scaffold creates a non-runtime proposal, and an explicit human `accept` operation creates the formal file.

### 3.6 Unrelated Mock and DeerFlow changes are present

Current Mock and DeerFlow behavior changes have their own design history. They are not config/path migrations and must not be reverted or expanded during this work. Characterization tests isolate their current behavior from the configuration refactor.

## 4. Architectural invariants

Project configuration retains the object-oriented layering already defined by `config.md`:

- `project`: project identity, capabilities, intrinsic resources, and business-domain vocabulary;
- `runtime`: deployment, services, transport, interaction, and runtime inputs;
- `verifier`: how verifier connects to and processes the project;
- `verifier.presentation`: UI, report, and explanation-only values;
- `environment`: declarations binding machine-local variables to canonical fields;
- `metadata`: non-behavioral provenance and audit facts.

No new top-level containers are introduced. A field is classified by the object or behavior it describes, not by the module that currently consumes it.

Downstream code consumes typed `RuntimeConfig`, `ProjectSpec`, and `ProjectKnowledgeRoute` interfaces. Raw YAML dictionaries and file locations are not downstream APIs.

This work completes the already-declared `schema_version: 1`; it does not introduce a v2. The misplaced presentation fields are a non-compliant transitional implementation, not a second accepted v1 shape that must remain readable.

## 5. Semantic field closure

### 5.1 Canonical ownership

| Current location | Canonical location | Semantics |
|---|---|---|
| `verifier.presentation.scenarios` | `verifier.scenarios.allowed` | scenarios accepted by verifier for the project |
| implicit Mock fallback to presentation scenarios | `runtime.mock_cases.default_scenarios` | explicit default Mock generation input |
| `verifier.presentation.interactive_scenarios` | `verifier.scenarios.interactive` | scenario-specific interaction behavior |
| `verifier.presentation.intent_labels` | `project.taxonomies.intent.labels` | intrinsic business output vocabulary |
| `verifier.presentation.intent_descriptions` | `project.taxonomies.intent.descriptions` | intrinsic business output descriptions |
| QA `verifier.presentation.score_dimensions` | `verifier.judge.score_dimensions` | Judge contract input |
| QA `verifier.presentation.error_taxonomy` | `verifier.judge.error_taxonomy` | Judge result classification |
| `verifier.presentation.core_forbidden_markers` | `verifier.check_rules.core_forbidden_markers` | Check contract input |
| `verifier.presentation.event_aliases` | `runtime.services.primary.stream.event_aliases` | service stream normalization |
| `verifier.presentation.terminal_events` | `runtime.services.primary.stream.terminal_events` | service stream completion behavior |

Fields that are demonstrably display-only, including currently unconsumed display stages, dimensions, path types, or taxonomies, remain in `verifier.presentation`. If a future runtime consumer needs one of them, that change must first establish a canonical semantic owner; runtime code must never start consuming the presentation copy.

The strict schema also enforces these cross-field relations:

- `runtime.mock_cases.default_scenarios` is an explicit subset of `verifier.scenarios.allowed`;
- `verifier.scenarios.interactive` is a subset of `verifier.scenarios.allowed`;
- `verifier.scenarios.interactive` is allowed only when the project/runtime interaction contract supports continuation;
- `project.taxonomies.intent.descriptions` may describe only declared intent labels;
- stream aliases and terminal events are valid only for a service transport that declares stream handling.

### 5.2 Typed consumer boundary

Behavioral consumers use typed accessors such as:

- `spec.scenarios.allowed`;
- `spec.scenarios.interactive`;
- `spec.mock_cases.default_scenarios`;
- `spec.intent_taxonomy.labels`;
- `spec.judge.score_dimensions`;
- `spec.check_rules.core_forbidden_markers`;
- `spec.primary_stream.event_aliases`.

Exact Python type shapes may follow existing dataclass conventions, but the semantic paths above are fixed. Consumers must not reconstruct ownership through raw `dict.get` chains.

The frontend is a projection: it may aggregate project, runtime, verifier, and presentation values into the existing response shape. It cannot become a source for behavioral consumers.

### 5.3 Hard cutover

Each semantic slice updates all of the following as one green change:

1. every affected formal project YAML;
2. parser and strict schema;
3. typed output/accessors;
4. all behavioral consumers;
5. positive and negative contract tests.

After a slice is migrated, its old presentation field is rejected. There is no permanent `new or legacy`, alias, silent default, or project-module constant fallback.

## 6. Behavior preservation

### 6.1 Sources of truth during migration

- Current resolved behavior is the regression oracle.
- `20260721` explains original field intent and helps detect lost information.
- Neither source authorizes an unrelated behavior change.

If current behavior and historical intent expose an unexplained contradiction, implementation stops for a business decision.

### 6.2 Five-project characterization matrix

Before production changes, tests record stable, machine-independent behavior for:

- `QA`;
- `client_search`;
- `deerflow`;
- `marketting-planning-intent`;
- `marketting-planning`.

The matrix covers:

- sanitized resolved configuration;
- allowed and default Mock scenarios;
- intent labels;
- single-turn and multi-turn decisions;
- QA Judge context dimensions and taxonomy;
- Check forbidden-marker results;
- SSE alias normalization and terminal-event detection;
- LiveSchema ready/schema results;
- frontend projection values.

Snapshots remove secrets, physical machine roots, timestamps, UUIDs, and other nondeterministic data.

### 6.3 Reviewer protection

LiveSchemaCheck, Judge, and Check are treated as protected behavioral surfaces:

- their algorithms are not changed by this migration;
- the same frozen inputs must produce the same outputs and error codes before and after field relocation;
- a changed conclusion is a separate business change and blocks the configuration slice;
- loader/input plumbing may change only when the parity tests remain exact.

## 7. Path and environment architecture

### 7.1 Approved physical and logical sources

The three YAML authorities store logical paths or declared environment references. Only repository-root `.env` or the process environment may carry machine-specific absolute roots.

For example, each project may declare a different variable:

```yaml
project:
  resources:
    source:
      repository: ${DEERFLOW_REPO}

environment:
  variables:
    DEERFLOW_REPO:
      bind: project.resources.source.repository
      type: path
```

The resolver binds that selected project's repository to the shared `business://` scope. Consumers use `business://...` and do not know the environment variable name.

### 7.2 Derived artifacts

Manifests, investigation results, context records, Mock cases, and other derived data that may re-enter a formal run store logical references, for example:

```json
{
  "location_scope": "business_source",
  "location": "src/api/server.py",
  "symbol": "create_app"
}
```

`revision` and `sha256` are optional provenance/integrity fields. They identify source state or content and do not participate in path resolution.

### 7.3 One artifact context

The effective environment and formal configuration resolve one `PathRoots`/artifact context per run. Writer and scanner consume the same context.

`base_overrides` is removed from the production writer API. Tests that need temporary storage inject a complete temporary context instead of monkeypatching a destination outside the registry.

## 8. Repository scanning and runtime enforcement

### 8.1 Execution-domain classification

The gate discovers candidate Python, Shell, YAML, and JSON files repository-wide and classifies executable sources into explicit domains:

- formal product runtime and producers;
- independent hooks, Skills, checklists, and diagnostic tools;
- one-time migration tools;
- tests and fixtures;
- documentation/report-only content.

This classification is protocol code, not a fourth user-editable configuration source. A new executable location that performs path construction or structured writes but has no classification fails closed.

Formal product roots include current runtime areas and future formal source locations such as `impl/tools`; they are not limited to the current positive list.

### 8.2 Static checks

Full and changed-file checks use the same classifier and detect at least:

- unapproved absolute path literals;
- direct structured writes that bypass the registered writer;
- ad hoc joins or relative-path interpretation in formal consumers;
- writes to an unregistered active-artifact root;
- unclassified executable producer locations.

Invalid-path test fixtures must be explicitly marked as fixtures so that examples used to prove rejection do not become exceptions available to product code.

### 8.3 Runtime checks

Static analysis cannot prove arbitrary dynamic code safe. Runtime enforcement therefore rejects:

- physical absolute paths in portable artifact fields;
- unresolved scopes;
- parent traversal or root escape;
- a destination outside the artifact registry;
- a writer and scanner operating with different contexts.

Static discovery and runtime rejection form complementary gates.

## 9. Frozen environment propagation

Bootstrap constructs one effective environment snapshot from repository-root `.env` plus the invoking process environment. Precedence remains the one defined by `config.md`.

The same snapshot is passed to:

- runtime and project resolvers;
- full-gate subprocesses;
- post-run artifact scanning;
- configuration evidence generation.

Secret values participate in resolution but are redacted from diagnostics, fingerprints, reports, and snapshots.

## 10. Proposal and explicit accept workflow

### 10.1 Generation

Scaffold reads the human project knowledge route and generates a proposal under a non-runtime location such as:

```text
report/config-proposals/<project>/<proposal-id>/
```

The proposal includes:

- candidate formal YAML;
- source knowledge-route revision;
- candidate content hash;
- schema, path, and environment validation results;
- a diff against the current formal configuration when one exists.

Runtime loaders never search or read proposal locations.

### 10.2 Acceptance

An explicit human command accepts a specific proposal and expected hash.

For initial creation:

- the formal target must not exist;
- hash and validation state must still match;
- the final file is written atomically;
- formal metadata records the accepted proposal hash.

For an existing project, initial accept refuses to overwrite. A separately declared update-proposal operation must include the expected hash of the current formal file, so concurrent human edits cannot be lost.

Evals, harness AI, scaffold, and normal runtime commands have no automatic accept path.

## 11. Implementation sequence

Every batch must leave the relevant suite green.

1. Add five-project characterization tests without production behavior changes.
2. Move Check and Judge fields and consumers.
3. Move SSE, scenario, interaction, Mock-default, and intent-taxonomy fields and consumers.
4. Reject legacy presentation fields and remove behavioral fallbacks.
5. Unify artifact context and remove `base_overrides`.
6. Add repository-wide execution-domain classification, static detection, and runtime path enforcement.
7. Freeze and propagate one effective environment.
8. Implement proposal generation and explicit accept.
9. Update stale tests, compatibility ledger entries, and evidence reports from the final code state.

Unrelated Mock, DeerFlow, or reviewer algorithm changes are excluded from these batches.

## 12. Permanent anti-regression gates

- Only frontend/report projection code may read `spec.presentation`.
- Behavioral modules use typed canonical fields.
- Every configurable field has one canonical path and one default source.
- Schema ownership metadata identifies expected consumers.
- Old, unknown, or misplaced YAML fields fail validation.
- New path-writing code belongs to a classified execution domain.
- Compatibility entries carry a machine-checkable deletion condition.
- Completion reports are regenerated from the exact code and test state they describe.

## 13. Acceptance matrix

Each of the five real projects must prove:

| Area | Required evidence |
|---|---|
| strict parsing | formal YAML resolves through the canonical schema |
| behavior parity | frozen Mock, Judge, Check, Live/SSE, interaction, and LiveSchema results match |
| consumer wiring | each canonical behavior field reaches a real consumer |
| legacy rejection | restoring the old presentation field fails |
| machine portability | two unrelated temporary machine layouts resolve to equivalent logical results |
| environment binding | project-specific variables bind to shared logical scopes |
| artifact safety | absolute paths, unregistered roots, and traversal fail |
| scanner coverage | full and changed-file scans detect bypass writers and unclassified producers |
| proposal safety | unaccepted, changed-hash, and existing-target cases cannot enter runtime |
| secret safety | values are absent from evidence and diagnostics |

The final verification sequence includes:

```text
five-project characterization tests
related unit and contract tests
python -m impl.core.config_check
python -m impl.core.config_check --full
git diff --check
```

## 14. Stop conditions

Implementation pauses and reports a separate decision when:

- a frozen LiveSchema, Judge, Check, Mock, interaction, or SSE result changes;
- current behavior and `20260721` semantics cannot be reconciled without a business decision;
- an active artifact's legal root or lifecycle cannot be determined;
- passing tests would require a legacy-field fallback;
- implementation would require changing or contradicting either governing specification.

## 15. Completion definition

The work is complete only when every applicable rule in both governing specifications has:

- an implementation path;
- a positive test;
- a negative or bypass test where failure behavior matters;
- current, reproducible evidence;
- no unexplained change to protected business behavior.

Passing a partial test suite or retaining a compatibility bridge with a future cleanup note is not completion.
