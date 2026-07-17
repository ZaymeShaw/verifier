from __future__ import annotations

from impl.core.schema.fixture import load_fixture
from impl.core.schema.occam import SCHEMA_FIELD_ROLES, field_role


def test_occam_field_roles_are_declared_for_high_risk_schemas():
    assert "RunTrace" in SCHEMA_FIELD_ROLES
    assert field_role("RunTrace", "extracted_output") == "derived_alias"
    assert field_role("RunTrace", "turn_records") == "canonical"
    assert field_role("JudgeResult", "fulfillment_assessments") == "canonical"
    assert field_role("JudgeResult", "summary") == "summary"
    assert field_role("AttributeResult", "expectation_attributions") == "canonical"
    assert field_role("TraceTableRow", "fulfillment_status") == "view_only"


def test_run_trace_fixture_keeps_output_and_trace_facts_separate():
    trace = load_fixture("impl.core.schema.trace.RunTrace")

    assert trace.input == {"query": "上海 30-40岁 高净值客户"}
    assert trace.extracted_output
    assert not hasattr(trace, "live_result")


def test_judge_fulfillment_is_canonical_for_fixture():
    judge = load_fixture("impl.core.schema.judge.JudgeResult")

    assert judge.fulfillment_assessments
    assert judge.overall_fulfillment["status"] == "fulfilled"
    assert all(item.status == "fulfilled" for item in judge.fulfillment_assessments)


def test_attribute_canonical_fields_drive_fixture():
    attribute = load_fixture("impl.core.schema.attribute.AttributeResult")

    assert attribute.expectation_attributions
    assert attribute.root_cause_hypothesis
    assert attribute.evidence
