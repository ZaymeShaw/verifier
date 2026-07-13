from __future__ import annotations

from pathlib import Path

from impl.core.project_loader import list_projects, load_project


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_project_template_is_minimal():
    template = REPO_ROOT / "impl" / "projects" / "project.template.yaml"
    text = template.read_text(encoding="utf-8")

    assert "common:" in text
    assert "extra:" in text
    assert "adapter:" not in text
    assert "capabilities:" not in text
    assert "documents:" not in text


def test_existing_projects_load_with_common_compatibility():
    for project_id in list_projects():
        spec = load_project(project_id)

        assert spec.project_id == project_id
        assert spec.name
        assert spec.adapter == "adapter.py"
        assert isinstance(spec.common, dict)
        assert isinstance(spec.extra, dict)
        assert isinstance(spec.endpoint_discovery, dict)
        assert isinstance(spec.attribute_draft, dict)
        assert isinstance(spec.judge_draft, dict)
        assert (Path(spec.root) / "adapter.py").exists()

        common_api = spec.common.get("api") or {}
        if spec.api:
            assert spec.api == common_api


def test_default_documents_are_discovered():
    qa = load_project("QA")

    assert qa.documents["application"] == "application.md"
    assert qa.documents["evaluation"] == "evaluation.md"
    assert qa.documents["attribution"] == "attribution.md"
    assert qa.documents["checklist"] == "checklist.md"
