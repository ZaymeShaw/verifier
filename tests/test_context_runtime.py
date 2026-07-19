from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from impl.core.context.adapters import load_configured_context_adapter
from impl.core.context.bootstrap import build_context_runtime
from impl.core.context.embedding import DeterministicHashEmbeddingProvider
from impl.core.context.errors import (
    ContextAuthorizationError,
    ContextBudgetError,
    ContextConfigurationError,
    ContextResolutionError,
    ContextValidationError,
)
from impl.core.context.models import ContextUnitRecord
from impl.core.context.resolvers import CompositeContentResolver, FileContentResolver


PUBLIC_POLICY = {
    "default": {
        "enabled": True,
        "allowed_statuses": ["active"],
        "candidate_limit": 5,
        "load_limit": 4,
        "content_char_budget": 1_000,
        "query_limit": 3,
        "top_k_per_query": 3,
    }
}


def make_record(unit_id: str, **overrides) -> ContextUnitRecord:
    values = {
        "id": unit_id,
        "name": unit_id,
        "description": f"knowledge about {unit_id}",
        "content": f"full content for {unit_id}",
        "content_ref": None,
        "project_id": "demo",
        "scope": "project",
        "roles": ("judge",),
        "unit_type": "document",
        "source_type": "config",
        "status": "active",
        "tags": {},
    }
    values.update(overrides)
    return ContextUnitRecord(**values)


def build_runtime(tmp_path: Path, *, provider=None, resolver=None, project_policy=None):
    return build_context_runtime(
        project_id="demo",
        data_root=tmp_path / "runtime-data",
        project_root=tmp_path,
        embedding_provider=provider or DeterministicHashEmbeddingProvider(),
        content_resolver=resolver,
        public_policy=PUBLIC_POLICY,
        project_policy=project_policy,
    )


def test_context_record_requires_exactly_one_content_source_and_is_immutable():
    with pytest.raises(ContextValidationError):
        make_record("missing", content=None, content_ref=None)
    with pytest.raises(ContextValidationError):
        make_record("double", content="inline", content_ref="file:///tmp/example")

    record = make_record("immutable", tags={"trace_id": "trace-1"})
    with pytest.raises(FrozenInstanceError):
        record.name = "changed"
    with pytest.raises(TypeError):
        record.tags["trace_id"] = "trace-2"


def test_registration_reuses_embedding_when_only_content_or_governance_changes(tmp_path):
    provider = DeterministicHashEmbeddingProvider()
    runtime = build_runtime(tmp_path, provider=provider)
    original = make_record("unit-1")

    created = runtime.register_context_unit(original)
    assert created == {"id": "unit-1", "action": "created", "embedding_rebuilt": True}
    assert provider.calls == 1

    reused = runtime.register_context_unit(original)
    assert reused["action"] == "reused"
    assert provider.calls == 1

    content_changed = replace(original, content="new authoritative content")
    updated = runtime.register_context_unit(content_changed)
    assert updated["action"] == "updated"
    assert updated["embedding_rebuilt"] is False
    assert provider.calls == 1

    governance_changed = replace(content_changed, roles=("judge", "attribute"), scope="trace")
    updated = runtime.register_context_unit(governance_changed)
    assert updated["embedding_rebuilt"] is False
    assert provider.calls == 1

    description_changed = replace(governance_changed, description="different searchable description")
    reembedded = runtime.register_context_unit(description_changed)
    assert reembedded["embedding_rebuilt"] is True
    assert provider.calls == 2


def test_multi_query_search_preserves_diversity_and_never_returns_content(tmp_path):
    runtime = build_runtime(tmp_path)
    runtime.register_context_units(
        [
            make_record(
                "routing",
                name="Gateway routing",
                description="gateway routing configuration and HTTP 404 diagnostics",
                content="secret routing implementation",
            ),
            make_record(
                "field",
                name="Family relation field",
                description="familyrelation extraction field logic and schema",
                content="secret field implementation",
            ),
            make_record(
                "mock-only",
                description="gateway routing hidden mock reference",
                roles=("mock",),
            ),
        ]
    )
    run = runtime.start_run(role="judge", operation="evaluate", trace_id="trace-1")

    candidates = run.search_context_units(
        ["gateway routing 404", "familyrelation extraction field"], top_k_per_query=2
    )

    assert {item["id"] for item in candidates} == {"routing", "field"}
    assert all("content" not in item for item in candidates)
    assert all(item["matched_queries"] for item in candidates)
    debug = run.debug_snapshot()["context_debug"]
    assert set(debug["candidate_ids"]) == {"routing", "field"}


def test_load_rechecks_entire_batch_and_does_not_leak_allowed_subset(tmp_path):
    runtime = build_runtime(tmp_path)
    runtime.register_context_units(
        [
            make_record("allowed"),
            make_record("mock-only", roles=("mock",)),
        ]
    )
    run = runtime.start_run(role="judge", operation="evaluate")

    with pytest.raises(ContextAuthorizationError):
        run.load_context_units(["allowed", "mock-only"])
    assert run.debug_snapshot()["context_debug"]["loaded_ids"] == []


def test_trace_operation_status_and_budget_are_enforced(tmp_path):
    project_policy = {
        "roles": {
            "judge": {
                "operations": {
                    "evaluate": {
                        "allowed_scopes": ["trace"],
                        "load_limit": 2,
                        "content_char_budget": 12,
                    }
                }
            }
        }
    }
    runtime = build_runtime(tmp_path, project_policy=project_policy)
    runtime.register_context_units(
        [
            make_record(
                "current",
                scope="trace",
                content="12345678",
                tags={"trace_id": "trace-1", "operation": "evaluate"},
            ),
            make_record(
                "other-trace",
                scope="trace",
                tags={"trace_id": "trace-2", "operation": "evaluate"},
            ),
            make_record(
                "other-operation",
                scope="trace",
                tags={"trace_id": "trace-1", "operation": "diagnose"},
            ),
        ]
    )
    run = runtime.start_run(role="judge", operation="evaluate", trace_id="trace-1")

    candidates = run.search_context_units(["knowledge"])
    assert [item["id"] for item in candidates] == ["current"]
    assert run.load_context_units(["current"])[0].content == "12345678"

    runtime.register_context_unit(
        make_record(
            "second",
            scope="trace",
            content="abcdefgh",
            tags={"trace_id": "trace-1", "operation": "evaluate"},
        )
    )
    with pytest.raises(ContextBudgetError):
        run.load_context_units(["current", "second"])


def test_content_ref_is_resolved_inside_allowed_root_and_escape_is_rejected(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    document = project_root / "guide.md"
    document.write_text("authoritative project guide", encoding="utf-8")
    resolver = CompositeContentResolver([FileContentResolver([project_root])])
    runtime = build_runtime(tmp_path, resolver=resolver)

    record = make_record(
        "file-unit",
        content=None,
        content_ref=document.as_uri(),
    )
    runtime.register_context_unit(record)
    run = runtime.start_run(role="judge", operation="evaluate")
    assert run.load_context_units(["file-unit"])[0].content == "authoritative project guide"

    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(ContextResolutionError):
        runtime.register_context_unit(
            make_record("outside", content=None, content_ref=outside.as_uri())
        )


def test_invalidation_removes_unit_from_search_and_load(tmp_path):
    runtime = build_runtime(tmp_path)
    runtime.register_context_unit(make_record("temporary", description="temporary diagnostic evidence"))
    runtime.invalidate_context_unit("temporary")
    run = runtime.start_run(role="judge", operation="evaluate")

    assert run.search_context_units(["temporary diagnostic"]) == []
    with pytest.raises(ContextAuthorizationError):
        run.load_context_units(["temporary"])


def test_mandatory_units_use_the_same_guarded_load_path(tmp_path):
    project_policy = {
        "roles": {
            "judge": {
                "operations": {
                    "evaluate": {"mandatory_ids": ["required"]}
                }
            }
        }
    }
    runtime = build_runtime(tmp_path, project_policy=project_policy)
    runtime.register_context_unit(make_record("required"))
    run = runtime.start_run(role="judge", operation="evaluate")

    mandatory = run.load_mandatory_context_units()
    assert [unit.id for unit in mandatory] == ["required"]
    assert run.debug_snapshot()["context_debug"]["loaded_ids"] == ["required"]


def test_configured_adapter_requires_explicit_stable_fields_and_forces_project_boundary(tmp_path):
    spec = SimpleNamespace(
        project_id="demo",
        root=str(tmp_path),
        extra={
            "context": {
                "units": [
                    {
                        "id": "configured",
                        "name": "Configured guide",
                        "description": "explicit stable project guidance",
                        "content": "guide body",
                        "scope": "project",
                        "roles": ["judge"],
                        "unit_type": "document",
                        "source_type": "config",
                    }
                ]
            }
        },
    )
    adapter = load_configured_context_adapter(spec)
    records = list(adapter.iter_stable_context_units({"project_id": "demo"}))

    assert len(records) == 1
    assert records[0].id == "configured"
    assert records[0].project_id == "demo"


def test_loaded_content_preserves_authoritative_whitespace(tmp_path):
    runtime = build_runtime(tmp_path)
    runtime.register_context_unit(make_record("spacing", content="  exact body\n"))
    run = runtime.start_run(role="judge", operation="evaluate")

    assert run.load_context_units(["spacing"])[0].content == "  exact body\n"


def test_default_bootstrap_policy_fails_closed(tmp_path):
    runtime = build_context_runtime(
        project_id="demo",
        data_root=tmp_path / "closed",
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )
    runtime.register_context_unit(make_record("registered"))
    run = runtime.start_run(role="judge", operation="evaluate")

    with pytest.raises(ContextAuthorizationError):
        run.search_context_units(["registered"])


def test_run_restrictions_cannot_add_mandatory_units(tmp_path):
    runtime = build_runtime(tmp_path)
    with pytest.raises(ContextConfigurationError, match="cannot add mandatory"):
        runtime.start_run(
            role="judge",
            operation="evaluate",
            run_restrictions={"mandatory_ids": ["guessed"]},
        )


def test_search_ignores_vectors_from_a_different_embedding_model(tmp_path):
    first = DeterministicHashEmbeddingProvider(model_id="model-a")
    runtime = build_runtime(tmp_path, provider=first)
    record = make_record("model-bound", description="model bound searchable knowledge")
    runtime.register_context_unit(record)

    second = DeterministicHashEmbeddingProvider(model_id="model-b")
    changed_runtime = build_runtime(tmp_path, provider=second)
    run = changed_runtime.start_run(role="judge", operation="evaluate")
    assert run.search_context_units(["model bound searchable"]) == []

    changed_runtime.register_context_unit(record)
    assert run.search_context_units(["model bound searchable"])[0]["id"] == "model-bound"
