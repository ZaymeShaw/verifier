from __future__ import annotations

from pathlib import Path

from impl.core.config_schema import load_yaml_document
from impl.core.project_config import parse_project_document
from impl.core.project_loader import list_projects, load_project


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_project_template_is_minimal():
    template = REPO_ROOT / "impl" / "projects" / "project.template.yaml"
    document, _ = parse_project_document(
        load_yaml_document(template),
        project_id=None,
        project_root=template.parent,
    )

    assert document["schema_version"] == 1
    assert set(document) == {"schema_version", "project", "runtime", "verifier", "metadata"}
    assert document["runtime"]["mode"] == "uploaded_output_evaluation"
    assert document["verifier"]["attribution"]["enabled"] is False


def test_existing_projects_load_from_canonical_sections():
    for project_id in list_projects():
        spec = load_project(project_id)

        assert spec.project_id == project_id
        assert spec.name
        assert spec.adapter == "adapter.py"
        assert spec.schema_version == 1
        assert spec.project["id"] == project_id
        assert spec.runtime["mode"]
        assert isinstance(spec.verifier["attribution"]["enabled"], bool)
        assert (Path(spec.root) / "adapter.py").exists()


def test_default_documents_are_discovered():
    qa = load_project("QA")

    assert qa.documents["application"] == "application.md"
    assert qa.documents["evaluation"] == "evaluation.md"
    assert qa.documents["attribution"] == "attribution.md"
    assert qa.documents["checklist"] == "checklist.md"
