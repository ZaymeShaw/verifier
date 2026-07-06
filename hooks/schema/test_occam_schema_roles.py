from __future__ import annotations

from impl.core.schema.fixture import load_fixture
from impl.core.schema.occam import SCHEMA_FIELD_ROLES, field_role


def test_occam_field_roles_are_declared_for_high_risk_schemas():
    assert "RunTrace" in SCHEMA_FIELD_ROLES
    assert field_role("RunTrace", "extracted_output") == "derived_alias"
    assert field_role("RunTrace", "live_result") == "canonical"
    assert field_role("JudgeResult", "fulfillment_assessments") == "canonical"
    assert field_role("JudgeResult", "scenario") == "legacy_alias"
    assert field_role("AttributeResult", "causal_category") == "canonical"
    assert field_role("TraceTableRow", "verdict") == "view_only"


def test_run_trace_derived_aliases_match_live_result_fixture():
    trace = load_fixture("impl.core.schema.trace.RunTrace")

    assert trace.live_result is not None
    assert trace.normalized_request == trace.live_result.normalized_request
    assert trace.raw_response == trace.live_result.raw_response
    assert trace.extracted_output == trace.live_result.extracted_output
    assert trace.output_source == trace.live_result.output_source
    assert trace.application_boundary == trace.live_result.application_boundary
    assert trace.project_fields == trace.live_result.project_fields


def test_judge_fulfillment_is_canonical_for_fixture():
    judge = load_fixture("impl.core.schema.judge.JudgeResult")

    assert judge.fulfillment_assessments
    assert judge.overall_fulfillment["status"] == "fulfilled"
    assert judge.verdict == "correct"


def test_attribute_canonical_fields_drive_fixture():
    attribute = load_fixture("impl.core.schema.attribute.AttributeResult")

    assert attribute.causal_category == "implementation_bug"
    assert attribute.earliest_divergence["stage"] == "adapter.extract_output"
    assert attribute.chain_nodes
    assert attribute.probe_results
