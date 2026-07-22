# Config Prefix Path Implementation Design

## 1. Objective

Implement `spec/adapter/config-prefixpath.md` without restoring legacy YAML structure or changing non-path business behavior. The `20260721` branch is a semantic reference for deciding what each historical path meant and which consumer depended on it; it is not the target implementation.

The completed system must let a machine migration change only registered machine-root values while keeping repository configuration and logical references stable.

## 2. Scope

This implementation covers:

- the five YAML prefixes: `business://`, `verifier://`, `project://`, `route://`, and `artifact://`;
- `PathRoots`, `PathResolver`, `ResolvedPath`, and stable path error codes;
- strict prefix declarations with a temporary legacy-relative compatibility window;
- migration of the three authoritative YAML layers and their templates;
- migration of project documents, source paths, endpoint-discovery roots, role modules, role assets, and knowledge-route documents to resolver-backed access;
- `LogicalPathRef` for active manifest, receipt, state, report, and promotion references;
- a guarded artifact writer and config-check coverage;
- per-project semantic migration records and cross-machine regression tests.

This implementation does not change Judge, LiveSchema, Attribute, Mock, ready, service, attribution, or presentation semantics. Existing non-path defects may be recorded or may block a path consumer, but they must not be repaired by weakening an auditor or by changing business algorithms inside this migration.

## 3. Selected Migration Strategy

Use a compatibility-first cutover:

1. New prefixed paths are parsed strictly.
2. Existing bare relative values are temporarily resolved by the single historical scope owned by that schema field and emit `PATH_PREFIX_REQUIRED` migration warnings.
3. Absolute paths in authoritative YAML are rejected immediately.
4. YAML, templates, and consumers migrate incrementally while the compatibility view preserves current behavior.
5. Active artifacts migrate after the config and consumer path is stable.
6. The legacy-relative compatibility branch is removed only after consumer probes and cross-machine regression pass.

Rejected alternatives:

- A big-bang hard cutover has excessive risk in the current dirty worktree and would make unrelated failures difficult to attribute.
- Long-lived dual resolvers would create a second path authority and violate the single-resolution-chain requirement.

## 4. Core Path Model

### 4.1 Path scopes

The core module defines one closed scope vocabulary:

| Prefix | Scope | Root source |
|---|---|---|
| `business://` | `business_source` | resolved project source repository |
| `verifier://` | `verifier_repo` | auto-discovered verifier root |
| `project://` | `project_package` | `impl/projects/<project>` |
| `route://` | `knowledge_route` | `projects/<project>` |
| `artifact://` | `artifact_package` | explicit current artifact context |

No YAML registry of roots is added. `PathRoots` exists only in resolved runtime memory.

### 4.2 Types

The shared path module provides:

- `PathScope`: the closed logical-root enum;
- `PrefixedPath`: validated prefix plus normalized POSIX location;
- `PathRoots`: the physical roots for one resolution context;
- `ResolvedPath`: logical scope, normalized location, and physical `Path`;
- `LogicalPathRef`: serializable active-artifact reference;
- `PathContractError`: stable issue code plus safe field/location diagnostics;
- `PathResolver`: the only logical-to-physical resolution implementation.

### 4.3 Resolver behavior

`PathResolver.resolve()` receives the value, allowed scopes, expected target type, existence policy, and field path. It must:

1. parse the prefix;
2. reject unknown or disallowed scopes;
3. reject absolute, home, drive, UNC, `file://`, environment expansion, and traversal syntax;
4. locate the one declared root;
5. normalize without trying alternate roots or `cwd`;
6. reject lexical and symlink escape;
7. enforce file/directory/executable expectations when requested;
8. return `ResolvedPath`.

Commands and URLs never enter this parser. Registered machine-root environment values may be absolute because they construct `PathRoots`, not a prefixed child reference.

## 5. Configuration Integration

### 5.1 Project runtime configuration

`project_config.py` validates prefixes per field:

- `project.resources.source.paths.*`: `business`;
- `project.resources.documents.*`: `project`;
- `verifier.endpoint_discovery.source_roots`: `business`;
- role draft modules and role asset paths: `project`;
- any future verifier-wide repository file: only scopes explicitly declared by its schema.

`ProjectSpec` gains resolver-backed accessors for source, document, module, asset, and discovery paths. Canonical configuration retains the logical prefixed value. Temporary legacy compatibility properties are derived from it and do not own a second value.

### 5.2 Knowledge routes

Knowledge-route document paths accept only `route://`. `ProjectKnowledgeRoute.document_path()` resolves them from the project route root. Runtime project loading must not use this resolver as a fallback for missing implementation documents.

### 5.3 Public configuration

Command-valued fields such as `python.executable` and `browser.driver_path` remain commands when given a simple command name. A machine-specific absolute executable is supplied through its already registered environment binding. Future public repository-file fields use `verifier://`.

### 5.4 Compatibility window

Each schema-owned path field may temporarily declare exactly one `legacy_scope`. A bare relative value resolves only against that scope and records a structured warning containing the field and replacement prefix. The resolver must not infer the scope from file existence.

There is no compatibility for authoritative-YAML absolute paths, unknown prefixes, disallowed prefixes, or traversal.

## 6. Consumer Migration

Consumers migrate in bounded groups:

1. Project documents and source-path accessors.
2. Knowledge-route documents.
3. Draft modules and role assets.
4. Endpoint discovery.
5. Investigation source roots and package/module loading.
6. Fixed local-service wrapper scripts.

New consumers must use resolver-backed methods. Existing `Path(root) / value`, `cwd` fallback, multi-root probing, and direct path-environment reads are removed only after the corresponding probe passes.

The current `ProjectSpec.frontend_extensions` compatibility issue, missing Judge contract, LiveSchema mock seeds, and other non-path findings are not changed by these consumer edits.

## 7. Active Artifact Model

### 7.1 LogicalPathRef

New active references serialize:

```json
{
  "location_scope": "business_source",
  "location": "src/api/server.py",
  "symbol": "create_app",
  "revision": "optional-revision",
  "sha256": "optional-file-hash"
}
```

`location_scope` and `location` are always required. `symbol` is required only for symbol references. `revision` and `sha256` are required by validation/promotion policies, not by ordinary runtime references.

### 7.2 Compatibility and integrity

Legacy active artifacts may be read temporarily through an explicit legacy adapter and emit warnings. Any rewrite must emit `LogicalPathRef`; legacy strings cannot be copied forward. Historical artifacts that are not formally consumed remain untouched.

Hash or revision mismatch blocks active consumption. A hash is recalculated only after the referenced source is stable and without modifying the source behavior as part of the path migration.

### 7.3 PortableArtifactWriter

The writer performs schema validation, recursive logical-reference validation, physical-path rejection, lifecycle checks, stable serialization, redaction, and atomic replacement. Initial enforcement covers investigation manifests and validation receipts. Other active artifact types join only after their schemas are registered, avoiding an unsafe heuristic rewrite of arbitrary historical JSON.

## 8. Error Handling

The implementation uses the protocol issue codes:

- `PATH_PREFIX_REQUIRED`
- `PATH_PREFIX_UNKNOWN`
- `PATH_PREFIX_NOT_ALLOWED`
- `PATH_ABSOLUTE_CONFIG`
- `PATH_ROOT_UNBOUND`
- `PATH_TRAVERSAL`
- `PATH_SYMLINK_ESCAPE`
- `PATH_ENV_BYPASS`
- `PATH_CONSTRUCTION_BYPASS`
- `PATH_SCHEMA_BYPASS`
- `PATH_WRITER_BYPASS`
- `PATH_SCAN_FAILED`

Errors identify the configuration or artifact file, field/JSON pointer, prefix, normalized location, and construction site where available. They never print secret values or machine-root environment contents.

## 9. Validation Strategy

### 9.1 Unit tests

Cover all five scopes, allowed-scope enforcement, missing roots, absolute and cross-platform forms, traversal, symlink escape, expected file/directory type, commands and URLs, and deterministic legacy warnings.

### 9.2 Configuration tests

Cover every registered path field in public, project, route, and template YAML. Verify that prefixed values resolve correctly and bare legacy values use only their declared legacy scope.

### 9.3 Consumer probes

For every project, prove the resolved document, source child, draft module, role asset, endpoint root, and start wrapper actually reaches the intended consumer. Existence alone is not sufficient.

### 9.4 Artifact tests

Cover LogicalPathRef parsing, optional and required integrity fields, legacy read compatibility, mandatory logical rewrite, physical-path guard, atomic writer behavior, and stale revision/hash rejection.

### 9.5 Cross-machine tests

Construct two temporary layouts with different verifier, business, project, route, and artifact roots. Change only registered root bindings and verify identical logical resolution and consumer behavior. Include same-named files in multiple roots to prove there is no existence-based fallback.

### 9.6 Regression accounting

Record known failures before path edits. Targeted path tests and affected existing suites must pass after every migration group. A pre-existing non-path failure is not silently accepted as success, but it is tracked separately and must not trigger unrelated auditor changes.

## 10. Rollout Phases

1. Add core path types, error codes, and resolver tests.
2. Integrate project and knowledge-route parsers with temporary legacy scopes.
3. Add resolver-backed accessors and consumer probes.
4. Migrate all three YAML layers and templates to explicit prefixes.
5. Migrate consumers and remove their local path construction.
6. Add LogicalPathRef and migrate investigation manifest/receipt active paths.
7. Add PortableArtifactWriter enforcement for registered active schemas.
8. Extend config-check to YAML prefixes, consumer bypasses, active artifacts, writers, symlinks, changed files, and scan failure.
9. Run cross-machine regression and per-project semantic-path audits.
10. Remove legacy bare-relative compatibility after all exit criteria pass.

## 11. Exit Criteria

- All authoritative YAML filesystem children use allowed explicit prefixes.
- Absolute machine roots appear only in registered machine-value channels and runtime memory.
- All formal consumers use resolver-backed paths.
- All registered active artifact paths use LogicalPathRef and pass integrity checks.
- All registered active producers use PortableArtifactWriter.
- Config-check fails closed on unknown paths, artifacts, writers, and scan failures.
- Every `20260721` formal path has a migrate, split, delete, or handoff disposition and a consumer probe.
- Non-path LiveSchema, Judge, Attribute, and Mock changes are absent from the path-migration diff.
- Cross-machine regression passes.
- Legacy compatibility is removed or has an explicit remaining owner and deletion condition.
