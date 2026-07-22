# Config Prefix Path Final Compliance Design

## 1. Objective

Complete the remaining infrastructure work required by
`spec/adapter/config-prefixpath.md` without changing evaluation business
algorithms or re-attesting existing evidence.

After this change, moving the verifier or a business repository to another
machine changes only registered machine-root bindings. Formal YAML remains
logical, and resumable artifacts cannot persist physical paths or ambiguous
relative paths.

This change must not:

- modify Judge, LiveSchema, Attribute, Mock, attribution, or local-service
  business behavior;
- refresh stale revision or hash evidence;
- weaken receipt, manifest, or evidence integrity validation;
- turn generated artifacts into a fourth configuration source;
- introduce a filesystem audit session around every CLI command.

Existing Deerflow stale evidence and other stale receipts remain explicit
integrity blockers. They are evidence-maintenance work, not path-contract work.

## 2. Selected Architecture

Use a lean, three-layer enforcement model:

1. `ActiveArtifactRegistry` declares which generated artifacts are formal,
   resumable, or promotion-relevant.
2. A family-aware writer validates the declared family, target location,
   lifecycle, schema, and portable references before an artifact is persisted.
3. `config-check` and CI inspect the repository tree and changed/untracked files
   so a producer that bypasses the writer is still rejected.

The registry is metadata about generated runtime artifacts. It does not contain
machine roots or business values and is not a configuration source. The only
formal configuration and knowledge-routing locations remain those defined by
`spec/adapter/config.md`: `impl/config.yaml`,
`impl/projects/<project>/project.yaml`, `projects/<project>/project.yaml`, plus
registered machine values supplied through `.env`, process environment, or a
secret manager.

Rejected alternatives:

- Extending unrelated glob and AST allowlists leaves artifact ownership and
  lifecycle ambiguous.
- Git-only auditing cannot see runtime artifacts that were generated without
  being tracked or staged.
- Wrapping every CLI in a before/after filesystem audit session adds lifecycle
  complexity that is not currently justified. It can be added later if a real
  generate-then-delete bypass is demonstrated.

## 3. Active Artifact Registry

Each registered family owns:

- a stable `family_id`;
- lifecycle (`derived_active`, `derived_historical`, or `machine_local`);
- allowed target patterns and owning directories;
- payload schema/parser;
- portable-reference and integrity validators;
- formal consumers and promotion/resume boundaries;
- the required writer policy;
- rules for recognized historical siblings, if the same directory contains
  both active and historical files.

Lifecycle is determined by consumption, not by the directory name. Any
artifact that can be resumed, revalidated, compared as the current baseline, or
used by promotion is `derived_active`. `derived_historical` is display/audit
input only. `machine_local` is limited to disposable cache or telemetry and
cannot be consumed by a formal run. Moving a historical or machine-local
artifact into a formal boundary requires rewriting it through a
`derived_active` family.

The first complete registry covers every currently known structured artifact
that can be loaded, resumed, compared, or promoted:

1. investigation manifests and their trace graphs;
2. investigation validation receipts;
3. endpoint-discovery manifests;
4. Draft loop state, the current run report, and current review/promotion
   evidence referenced by that state;
5. case-pool storage;
6. frozen project MockCase datasets;
7. context records that are loaded by a formal runtime consumer.

All seven categories above are `derived_active` when used in the stated formal
boundary. Historical iteration siblings and disposable cache records are
classified separately and cannot satisfy an active consumer lookup.

Referenced Markdown or other evidence files do not need a separate structured
family merely because they are files. Their owning active artifact must refer
to them with `LogicalPathRef`, and the registry validator checks existence and
any declared `sha256`, `revision`, or `symbol` metadata.

Unreferenced iteration reports remain historical. A historical artifact may be
read for display, but it must pass the active family contract before it becomes
a resume or promotion input. Files found in an active-owned directory that are
neither a registered family nor an explicitly recognized historical sibling
fail closed as `PATH_ACTIVE_UNKNOWN`.

## 4. Family-Aware Persistence

Formal producers write through one entry point and must provide a `family_id`.
The writer resolves that family in the registry and performs these checks
before the atomic write:

1. the family exists and permits writes;
2. the requested lifecycle matches the family;
3. the target is inside the family's allowed logical/physical boundary;
4. the payload matches the family schema;
5. persisted file and directory references use `LogicalPathRef`;
6. physical absolute paths and ambiguous path-like strings are absent;
7. required integrity metadata is present and internally valid.

The general normalization logic currently provided by
`PortableArtifactWriter` remains reusable internally, but calling it without a
registered family is not a valid formal write. Test fixtures and explicitly
historical exporters may use separate, clearly named non-formal helpers; they
cannot target active-owned directories.

This boundary rejects invalid output at its source. It also gives
`config-check` a concrete producer-to-family relationship to verify instead of
guessing intent from a generic JSON write.

## 5. Consumer and Compatibility Cutover

Formal consumers obtain paths from resolver-backed accessors on `ProjectSpec`
or the corresponding route/artifact context:

- business files use a business-scoped accessor;
- verifier project-package files use a project-scoped accessor;
- public verifier files use a verifier-scoped accessor;
- knowledge documents use `ProjectKnowledgeRoute`;
- artifact-package files use the run's explicit artifact root.

Formal path construction from `Path(spec.root)`, `spec.source_project`, YAML
field-position guesses, or hand-built repository-relative joins is removed in
this change. `spec.root` and `spec.source_project` may remain temporarily as
read-only display/API compatibility views, but scanners reject using them as
path-construction roots. Tests that instantiate `ProjectSpec` directly must use
a resolver-equipped fixture rather than activating production fallbacks.

Compatibility is allowed only when it preserves a non-path public data shape.
There is no production fallback from a missing resolver to legacy roots.
Missing root registration therefore fails at the actual consumer boundary with
the path protocol's missing-root error.

## 6. `config-check` and CI

`config-check --full` combines four forms of evidence:

1. schema validation for the three formal YAML locations and registered
   environment-variable names;
2. registry discovery and validation of the current active artifact graph;
3. narrow AST/static sink checks for raw structured writes and path construction
   from legacy roots;
4. changed/untracked-file inspection supplied by CI or local Git state. A pull
   request compares against its checked-out base revision; local execution uses
   the index, worktree, and untracked set. If the comparison boundary cannot be
   established, the full current-tree checks still run and the unavailable
   changed-file layer is reported rather than treated as a clean result.

The current-tree registry scan is authoritative for existing formal artifacts.
The changed/untracked scan is a supplement that catches a new producer, schema,
or output location before it becomes an established blind spot. CI must run the
full check after dependency installation and must not silently skip scan,
parse, symlink, or repository-state errors.

Static checking uses narrow bootstrap exceptions for the resolver and writer
implementations themselves. Whole-file exemptions are not permitted for formal
producers or consumers. Ordinary temporary paths, logs, HTTP URLs, command
names, and test-only filesystem setup remain outside the formal path graph and
must not be reported solely because they use `Path` or `write_text`.

No command-wide `ActiveArtifactAuditSession` is introduced. Consequently, a
malicious native extension that writes and deletes an invalid file entirely
within one command is outside this phase's guarantee. If that becomes an actual
threat model, sandbox/filesystem event auditing requires a separate design.

## 7. Migration Ledger

The `20260721` ledger remains review evidence, not executable configuration.
It is expanded from family-level notes to one entry per project and historical
formal reference. Each entry records:

- project and historical semantic location, without personal machine roots;
- old consumer and expected scope/lifecycle;
- canonical YAML field or active `LogicalPathRef` target;
- behavior probe that proves the meaning was preserved;
- disposition (`migrate`, `split`, `delete`, or `handoff`);
- compatibility owner and an explicit deletion condition/date when any
  compatibility remains.

`config-check` validates the ledger schema, known project IDs, canonical target
syntax, and probe IDs. It does not use ledger values to resolve runtime paths.

## 8. Cross-Machine Proof

The portability test creates two independent temporary layouts with identical
logical YAML and different bindings for all five roots:

- verifier repository;
- business source;
- verifier project package;
- knowledge route;
- artifact package.

Both layouts contain same-named decoy files under the wrong roots. The test
loads configuration, resolves representative files in every scope, loads the
knowledge route, validates one registered active artifact, and runs one
non-network minimal consumer. It proves that consumers use scope identity, not
the current checkout or a same-named fallback.

Negative cases cover missing roots, unknown prefixes/families, traversal,
symlink escape, physical absolute paths, naked active path fields, wrong target
families, stale hashes, and raw writer/path-construction bypasses.

## 9. Error Handling

All enforcement is fail-closed. Existing protocol error codes remain stable;
the implementation adds a dedicated unknown-active-family/location error only
if no existing code expresses it precisely. Reports identify:

- `family_id` and artifact path;
- failing field or logical reference;
- whether failure occurred at producer, current-tree audit, static scan, or
  consumer resolution;
- the remediation boundary, without automatically rewriting evidence.

Integrity failures never mutate `revision`, `sha256`, `symbol`, or receipts.
Path-contract completion may leave the overall check red when a genuine stale
evidence blocker already exists.

## 10. Rollout and Verification

Implementation order:

1. complete family declarations and tests;
2. make the formal writer family-aware and migrate known producers;
3. extend current-tree, unknown-file, static-sink, and changed/untracked checks;
4. remove formal `spec.root`/`source_project` path fallbacks and update fixtures;
5. expand and validate the migration ledger;
6. add the two-layout minimal-run proof;
7. run targeted tests, Ruff, `config-check --full`, and the full test suite.

Exit criteria:

- every known resumable or promotion-relevant structured artifact has one
  registered family and one formal writer path;
- unknown files in active-owned locations fail closed;
- formal consumers do not construct paths from legacy compatibility views;
- current-tree and changed/untracked auditing detect formal writer and path
  bypasses without broad file exemptions;
- the per-project ledger has a canonical target and behavior probe for every
  known historical formal reference;
- the five-root cross-machine minimal run and negative isolation tests pass;
- path-related regressions are green;
- remaining red checks are separately identified pre-existing evidence or
  receipt integrity failures, not hidden or repaired by this change;
- no evaluation business algorithm changes are included.
