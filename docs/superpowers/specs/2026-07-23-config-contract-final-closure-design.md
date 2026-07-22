# Config Contract Final Closure Design

## 1. Objective

Close the remaining gaps between the repository implementation and:

- `spec/adapter/config.md`
- `spec/adapter/config-prefixpath.md`

The change must make the formal configuration and portable-path checks green without weakening evidence validation or changing LiveSchema, Judge, Attribute, or Mock business algorithms.

## 2. Scope

This change covers four connected boundaries:

1. revalidate and repair active investigation manifests and validation receipts;
2. remove the remaining legacy project-config and bare-path compatibility paths;
3. make active-artifact configuration access use the canonical runtime resolver;
4. strengthen writer-bypass and post-command artifact scanning.

Historical reports that are not read by a formal consumer remain historical. They are not rewritten merely to make repository text uniform.

## 3. Active Evidence Repair

### 3.1 File-backed evidence

For every stale file-backed `EvidenceRef`:

1. resolve its `LogicalPathRef` through the configured `PathResolver`;
2. verify the declared symbol still exists when a symbol is present;
3. run the smallest behavior probe that proves the evidence still supports the recorded business conclusion;
4. calculate revision and sha256 from the verified target;
5. write the manifest through the registered active-artifact writer;
6. regenerate the validation receipt through the official validation flow.

A changed hash is not sufficient evidence. If the referenced behavior or symbol no longer supports the recorded conclusion, the repair stops and reports a semantic evidence failure.

### 3.2 Non-file observations

API, SSE, and runtime observations must not be represented as filesystem references. They use a non-path evidence kind with structured inline `payload`. A stable content hash is calculated over the canonical JSON payload when the evidence requires an integrity fingerprint.

The marketing-planning `stream trace_id=...` observation will therefore remain an API observation and payload, not a `business_source` `LogicalPathRef`.

### 3.3 Receipt rules

Receipts are always derived from a successfully validated current manifest. They are never repaired by directly copying a new manifest hash or editing expected evidence hashes.

## 4. Compatibility Removal

### 4.1 Project configuration

Draft promotion accepts only:

```text
verifier.roles.<role>.draft
```

The fallback that edits legacy top-level `<role>_draft` blocks is removed. Missing canonical structure is a configuration error.

### 4.2 Prefixed paths

`parse_prefixed_path` and `canonical_prefixed_path` no longer accept a `legacy_scope`. `PrefixedPath` no longer records a legacy state, and the warning type used to convert bare paths is removed.

Every formal filesystem path without an explicit allowed prefix fails with `PATH_PREFIX_REQUIRED`.

### 4.3 Canonical public configuration access

Active-artifact discovery obtains `context.store_root` from the canonical `RuntimeConfig` resolver. It does not parse `impl/config.yaml` independently and does not silently fall back to a hard-coded context-store path.

## 5. Gate Strengthening

### 5.1 Static writer sinks

The structured-writer AST gate covers at least:

- direct `json.dump` and YAML dump calls;
- `Path.write_text` or stream `.write` receiving a JSON/YAML serialization;
- serialization assigned to a local variable before the write;
- supported import aliases for JSON/YAML modules;
- direct construction of `PortableArtifactWriter` outside its registry boundary.

The gate remains limited to formal implementation and Draft producer roots so ordinary test fixtures and human-authored Markdown are not treated as active artifacts.

### 5.2 Post-command scan

`config-check --full` performs a second active-registry and changed/untracked scan after its executable gates finish. This detects artifacts created during adapter, protocol, mock, or minimal-run checks.

Registered active directories reject unknown structured files. Scan failures and unreadable formal inputs fail closed.

## 6. Protected Business Behavior

The change must not modify:

- LiveSchema field semantics or request/output validation;
- Judge fulfillment boundaries;
- Attribute investigation or attribution reasoning;
- Mock scenario generation and validation algorithms;
- service request/response extraction rules.

Only configuration access, path representation, evidence integrity, registered persistence, and associated tests may change.

## 7. Verification

The change is complete only when all of the following hold:

1. `python -m impl.core.config_check --full` succeeds;
2. the full pytest suite succeeds;
3. all active manifests and receipts validate with no `PATH_INTEGRITY_STALE` or `PATH_NOT_FOUND`;
4. no production consumer triggers `PROJECTSPEC_COMPAT_BYPASS`;
5. no formal producer triggers `PATH_WRITER_BYPASS`;
6. legacy top-level draft configuration and bare path negative tests fail closed;
7. writer-alias, assigned-serialization, stream-write, and post-command generation negative tests are detected;
8. the two-layout cross-machine portability test continues to pass.

If an active evidence item cannot be semantically revalidated, the implementation is reported as blocked for that item rather than lowering validation requirements.

## 8. Change Order

1. add failing tests for remaining compatibility and gate gaps;
2. remove project-config and path compatibility;
3. route active-artifact public configuration through `RuntimeConfig`;
4. strengthen writer and post-command scanning;
5. revalidate and repair active manifests one project at a time;
6. regenerate receipts through the official validator;
7. run focused, configuration-full, and repository-full regression suites.
