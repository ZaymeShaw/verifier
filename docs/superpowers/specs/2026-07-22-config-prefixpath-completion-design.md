# Config Prefix Path Completion Design

## 1. Objective

Close the remaining gaps between the current implementation and
`spec/adapter/config-prefixpath.md` without changing Judge, LiveSchema,
Attribute, Mock, attribution, or project-service business algorithms.

The business outcome is that moving the verifier repository or a registered
business repository changes only registered machine-root values. Logical YAML
paths and active artifact references remain stable, and every formal path
bypass is either rejected or explicitly classified.

Deerflow's currently stale investigation evidence is not re-attested in this
change. The improved gate must expose those stale hashes as a separate blocking
fact; it must not rewrite hashes or weaken validation.

## 2. Selected Approach

Use a registry-driven incremental cutover.

An `ActiveArtifactRegistry` becomes the authoritative list of structured
artifacts that may enter the formal verifier graph. Each registration owns:

- artifact identity and lifecycle;
- discovery rules;
- schema/parser;
- portable writer policy;
- integrity validator;
- consumer or promotion boundary.

`config-check` discovers active artifacts through this registry rather than a
growing collection of unrelated glob expressions. Files in registered active
directories that cannot be classified fail closed. Historical files remain
untouched and cannot be promoted merely because they exist.

Rejected alternatives:

- Extending glob and AST allowlists would preserve the current blind spots.
- A big-bang removal of all compatibility views would mix path work with the
  large dirty worktree and create unnecessary business-regression risk.

## 3. Artifact Boundary

The first registry version covers:

1. Investigation manifest.
2. Investigation validation receipt.
3. Endpoint-discovery manifest.
4. Draft loop state.
5. Draft run report referenced by loop state.
6. Draft review evidence referenced by the current promotion candidate.

The registry validates both portable representation and integrity. A manifest
with a valid `LogicalPathRef` but stale `revision`, `sha256`, or `symbol` is not
healthy. Config-check reports the integrity failure and does not repair it.

Unreferenced Draft reports are historical. They may retain historical display
strings, but a loop or promotion input cannot reference them until they conform
to the registered active schema.

## 4. Consumer Boundary

Formal consumers must use `ProjectSpec` resolver-backed accessors.

- Business source children use `source_path(path_id)` or an explicitly scoped
  `resolve_path` call.
- Project package assets use project-scoped accessors.
- Knowledge documents use `ProjectKnowledgeRoute.document_path`.
- Investigation and endpoint consumers receive resolved paths, not YAML values
  or environment variables.
- Fixed convention files such as `adapter.py` and `tools.py` receive named
  project-package accessors instead of rebuilding `Path(spec.root) / value`.

`spec.root` and `spec.source_project` may remain as runtime compatibility views
for non-path public APIs during this phase, but formal file construction cannot
use them. Each remaining compatibility owner is recorded with a deletion
condition.

## 5. Audit Boundary

Path-construction scanning moves from whole-file exemptions to narrow,
documented bootstrap operations. The scanner must detect:

- direct joins from configured roots;
- aliases of configured roots followed by joins;
- raw JSON/YAML structured writers;
- unknown files in active artifact directories;
- tracked and untracked active artifacts;
- malformed, missing, or stale integrity references;
- scan/read/parse failures.

The legacy investigation v1 writer remains readable only for historical input.
It is not an active writer exemption and cannot emit into a registered active
location.

## 6. Migration Ledger

A repository-owned ledger records each formal path semantic inherited from the
`20260721` baseline. Each entry contains:

- historical semantic location without a personal physical root;
- logical scope and lifecycle;
- current canonical field or `LogicalPathRef`;
- formal consumers;
- behavior probe;
- migrate, split, delete, or handoff disposition;
- compatibility owner and deletion condition, when applicable.

The ledger is review evidence, not a fourth configuration source.

## 7. Cross-Machine Verification

Tests construct two independent layouts and bind all five roots:

- verifier repository;
- business source;
- project package;
- knowledge route;
- artifact package.

The same logical references must resolve to their corresponding machine roots.
Same-named files in multiple roots must never influence selection. Missing roots,
unknown active artifacts, raw writers, traversal, symlink escape, and stale
hashes must fail with the protocol error family.

Consumer probes verify adoption, not merely file existence.

## 8. Rollout

1. Add registry types and register the currently formal artifact families.
2. Route config-check artifact and integrity scanning through the registry.
3. Replace formal consumer joins with named resolver-backed accessors.
4. Narrow path-construction and writer exemptions.
5. Add the baseline migration ledger and compatibility deletion conditions.
6. Add five-root and negative cross-machine tests.
7. Run config-check and the full regression suite.

The expected final regression may still contain the existing Deerflow stale
evidence failures. They must appear as explicit integrity blockers in both the
relevant runtime tests and config-check. No hash is updated in this change.

## 9. Exit Criteria

- All registered active artifacts are discovered by the registry.
- Unknown files in active locations fail closed.
- Registered active artifacts pass portable schema checks; stale integrity is
  reported without mutation.
- Formal consumers no longer construct file paths from `spec.root` or
  `spec.source_project`.
- Writer and path scanners use no broad file-level exemption for formal code.
- The `20260721` ledger has a disposition and consumer probe for every known
  formal path family.
- Five-root cross-machine and same-name isolation tests pass.
- Path-related tests pass, config-check reports only genuine integrity blockers,
  and unrelated business algorithms are unchanged.
