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
    assert document["runtime"]["application"]["interface"]["shape"]
    assert document["runtime"]["adapter"]["request_construction"]["required_inputs"] == ["query"]
    assert document["verifier"]["attribution"]["enabled"] is False
    assert document["verifier"]["judge"]["boundary"]["gate"]


def test_existing_projects_load_from_canonical_sections():
    for project_id in list_projects():
        spec = load_project(project_id)

        assert spec.project_id == project_id
        assert spec.name
        assert spec.schema_version == 1
        assert spec.project["id"] == project_id
        assert spec.runtime["mode"]
        assert isinstance(spec.verifier["attribution"]["enabled"], bool)
        assert spec.adapter_path().exists()


def test_documents_are_exposed_from_canonical_project_resources():
    qa = load_project("QA")

    assert qa.document_paths["application"] == "project://application.md"
    assert qa.document_paths["evaluation"] == "project://evaluation.md"
    assert qa.document_paths["attribution"] == "project://attribution.md"
    assert qa.document_paths["checklist"] == "project://checklist.md"
