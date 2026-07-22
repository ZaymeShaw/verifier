# Config Semantic Closure and Portability Implementation Plan

**Design:** `docs/superpowers/specs/2026-07-23-config-semantic-closure-and-portability-design.md`

**Governing specs:** `spec/adapter/config.md`, `spec/adapter/config-prefixpath.md`

All work preserves unrelated working-tree changes. Neither governing spec is edited. Current behavior is the regression oracle; the `20260721` branch is semantic reference only.

## Task 1: Freeze five-project behavior

**Files:**

- Add `tests/test_config_semantic_behavior_baseline.py`.
- Adjust existing focused tests only when they already own the behavior being frozen.

**Work:**

1. Load all five formal project configurations.
2. Record sanitized resolved values for scenarios, Mock defaults, intent taxonomy, interaction decisions, QA Judge context, Check markers, stream aliases/terminal events, LiveSchema results, and frontend projection.
3. Use fixed in-memory inputs; do not require real services.
4. Prove current behavior before any production field move.

**Gate:**

```bash
pytest -q tests/test_config_semantic_behavior_baseline.py
```

Stop if current behavior cannot be characterized deterministically.

## Task 2: Add canonical schema fields and migrate formal YAML atomically

**Files:**

- `impl/core/project_config.py`
- `impl/core/schema/project.py`
- `impl/projects/project.template.yaml`
- `impl/projects/QA/project.yaml`
- `impl/projects/client_search/project.yaml`
- `impl/projects/deerflow/project.yaml`
- `impl/projects/marketting-planning-intent/project.yaml`
- `impl/projects/marketting-planning/project.yaml`
- `tests/test_project_config_contract.py`
- `tests/test_project_yaml_template.py`
- `tests/test_config_semantic_behavior_baseline.py`

**Work:**

1. Add strict `project.taxonomies.intent`, `runtime.services.*.stream`, `verifier.scenarios`, and `verifier.judge` parsing.
2. Extend `verifier.check_rules` with `core_forbidden_markers`.
3. Enforce scenario, intent-description, interaction, and stream cross-field constraints.
4. Move existing values without changing content.
5. Make Mock defaults explicit for every project that currently depends on scenario fallback.
6. Reject migrated behavioral fields under `verifier.presentation`.
7. Keep `schema_version: 1`; do not create a v2 compatibility path.

**Gate:**

```bash
pytest -q tests/test_project_config_contract.py tests/test_project_yaml_template.py tests/test_config_semantic_behavior_baseline.py
```

## Task 3: Switch all behavioral consumers to typed canonical accessors

**Files:**

- `impl/core/schema/project.py`
- `impl/core/pipeline.py`
- `impl/core/mock_agent.py`
- `impl/core/mock_protocol.py`
- `impl/core/interaction_protocol.py`
- `impl/core/check.py`
- `impl/core/frontend_view.py`
- `impl/projects/QA/judge.py`
- `impl/projects/marketting-planning/live.py`
- Related focused tests in `tests/`.

**Work:**

1. Expose typed accessors for allowed/interactive scenarios, Mock defaults, intent taxonomy, Judge contract, Check rules, and primary stream behavior.
2. Replace behavioral `spec.presentation` reads.
3. Let frontend projection aggregate canonical values while retaining its public response shape.
4. Add a source gate allowing `spec.presentation` reads only in frontend/report projection code.
5. Remove scenario and intent fallbacks to presentation or code constants.
6. Do not modify reviewer algorithms or result schemas.

**Gate:**

```bash
pytest -q tests/test_config_semantic_behavior_baseline.py tests/test_live_schema_check.py tests/test_reallive_transport.py tests/test_vnext_mock_case_protocol.py tests/test_project_layer_dispatch.py
```

Stop on any unexplained business-result change.

## Task 4: Unify artifact writer and scanner context

**Files:**

- `impl/core/portable_artifact.py`
- `impl/core/active_artifacts.py`
- `impl/core/context_store.py`
- `tests/test_portable_artifact.py`
- `tests/test_active_artifacts.py`
- `tests/test_context_runtime.py`
- `tests/test_attribute_baseline_runtime.py`

**Work:**

1. Remove the production `base_overrides` API.
2. Resolve writer destinations exclusively from `ActiveArtifactContext`/`PathRoots`.
3. Make scanner validation consume the same resolved context.
4. Replace `STORE_DIR` monkeypatch tests with injected temporary configuration/context.
5. Add negative tests for arbitrary roots, absolute portable references, traversal, and context mismatch.

**Gate:**

```bash
pytest -q tests/test_portable_artifact.py tests/test_active_artifacts.py tests/test_context_runtime.py tests/test_attribute_baseline_runtime.py
```

## Task 5: Close source-scanning bypasses

**Files:**

- `impl/core/config_check.py`
- Add a focused protocol module only if keeping execution-domain classification inside `config_check.py` would duplicate policy.
- `tests/test_config_contract.py`
- `tests/test_config_path_portability.py`

**Work:**

1. Replace the producer-root positive list with repository-wide candidate discovery plus explicit execution-domain classification.
2. Classify formal product code, independent tools, migrations, tests/fixtures, and documents/reports.
3. Include formal locations such as `impl/tools`.
4. Fail closed for unclassified executable writers/path constructors.
5. Use the same classifier for full and changed-file scans.
6. Inspect complete changed files rather than sampling bytes.
7. Add repository-wide absolute-literal detection with explicit invalid-fixture annotations.
8. Preserve independent hook/Skill/checklist autonomy while preventing their output from bypassing formal writer checks when promoted.

**Gate:**

```bash
pytest -q tests/test_config_contract.py tests/test_config_path_portability.py tests/test_portable_artifact.py
python -m impl.core.config_check
```

## Task 6: Freeze and propagate the effective environment

**Files:**

- `impl/core/config.py`
- `impl/core/config_bootstrap.py`
- `impl/core/config_check.py`
- `tests/test_runtime_config.py`
- `tests/test_config_contract.py`
- `tests/test_config_path_portability.py`

**Work:**

1. Build one effective environment snapshot from root `.env` and process environment.
2. Pass it to runtime/project resolution, full-gate subprocesses, post-scan, and evidence generation.
3. Preserve declared precedence and secret redaction.
4. Add tests where the supplied mapping intentionally differs from the real process environment.

**Gate:**

```bash
pytest -q tests/test_runtime_config.py tests/test_config_contract.py tests/test_config_path_portability.py
python -m impl.core.config_check --full
```

## Task 7: Implement proposal and explicit accept

**Files:**

- `scripts/scaffold_project.py`
- `impl/core/config_bootstrap.py` or a narrowly scoped proposal module if needed.
- `tests/test_project_config_contract.py`
- Add `tests/test_project_config_proposal.py`.

**Work:**

1. Change scaffold output from a formal file to `report/config-proposals/<project>/<proposal-id>/`.
2. Emit candidate YAML, source revision, candidate hash, validation summary, and existing-config diff.
3. Ensure loaders ignore proposal locations.
4. Add explicit accept requiring proposal identity and expected hash.
5. Refuse initial accept when the formal file exists.
6. For update proposals, require the expected current formal-file hash.
7. Write atomically and record the accepted proposal hash in formal metadata.
8. Ensure evals, harness, scaffold, and normal runtime have no auto-accept path.

**Gate:**

```bash
pytest -q tests/test_project_config_proposal.py tests/test_project_config_contract.py tests/test_project_yaml_template.py
```

## Task 8: Prove real-project cross-machine portability

**Files:**

- `tests/test_config_path_portability.py`
- `tests/test_project_config_contract.py`

**Work:**

1. Create two unrelated temporary verifier/business root layouts.
2. Copy or parameterize the five real project YAML and route inputs.
3. Bind distinct project environment variables in each layout.
4. Assert equivalent logical resolutions, typed consumer values, role assets, source-provider paths, and service configuration.
5. Avoid network/service startup; this test proves configuration portability, not service health.

**Gate:**

```bash
pytest -q tests/test_config_path_portability.py tests/test_project_config_contract.py
```

## Task 9: Remove stale compatibility and regenerate evidence

**Files:**

- `spec/adapter/config-prefixpath-20260721-ledger.yaml`
- `tests/test_config_contract.py`
- Relevant reports under `search-test-case/issue/`.

**Work:**

1. Remove ledger entries whose compatibility properties no longer exist.
2. Make retained entries carry executable deletion conditions.
3. Remove stale expected failures such as obsolete `PATH_INTEGRITY_STALE` expectations.
4. Regenerate closure evidence from the exact final working state.
5. Mark or supersede reports that claim closure using stale results.

**Final gate:**

```bash
pytest -q tests/test_config_semantic_behavior_baseline.py tests/test_project_config_contract.py tests/test_project_config_proposal.py tests/test_config_path_portability.py tests/test_portable_artifact.py tests/test_active_artifacts.py tests/test_config_contract.py tests/test_runtime_config.py tests/test_live_schema_check.py tests/test_reallive_transport.py tests/test_vnext_mock_case_protocol.py
python -m impl.core.config_check
python -m impl.core.config_check --full
git diff --check
```

After the automated gates pass, run the `check`, `aihacking`, and `Bussiness` reviews against the complete configuration-contract diff. Findings must be fixed or explicitly accepted before claiming compliance.
