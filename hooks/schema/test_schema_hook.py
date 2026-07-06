from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = HOOK_DIR.parent.parent
CONFIG_FILE = HOOK_DIR / "config.yaml"
AUDIT_SCRIPT = HOOK_DIR / "schema_audit.py"
HOOK_SCRIPT = HOOK_DIR / "schema-hook.sh"

sys.path.insert(0, str(HOOK_DIR))
import schema_audit  # noqa: E402


def test_schema_hook_files_exist():
    assert CONFIG_FILE.exists()
    assert AUDIT_SCRIPT.exists()
    assert HOOK_SCRIPT.exists()
    assert (HOOK_DIR / "README.md").exists()


def test_config_declares_required_schema_layers_and_monitored_files():
    cfg = schema_audit._load_config()

    assert {"mock", "live", "trace", "judge", "attribute", "frontend", "table"}.issubset(set(cfg["required_layers"]))
    assert "core" in cfg["scan_modes"]
    assert "full" in cfg["scan_modes"]
    assert cfg["default_scan_mode"] == "core"
    assert "impl/core/pipeline.py" in cfg["scan_modes"]["core"]["python_files"]
    assert "impl/projects/*/adapter.py" in cfg["scan_modes"]["core"]["python_files"]
    assert "impl/core/interaction_protocol.py" in cfg["scan_modes"]["core"]["python_files"]
    assert "impl/core/check.py" in cfg["scan_modes"]["core"]["python_files"]
    assert "impl/frontend/live.html" in cfg["scan_modes"]["core"]["frontend_files"]
    assert "impl/**/*.py" in cfg["scan_modes"]["full"]["python_files"]
    assert "impl/core/schema/*.py" in cfg["schema_source_whitelist"]
    assert "impl/core/schema/**/*.py" in cfg["schema_source_whitelist"]
    assert "impl/core/schema/**/*.py" not in cfg["scan_modes"]["full"]["exclude_python_files"]
    assert "*_from_run" in cfg["allowed_compat_wrapper_patterns"]


def test_wildcard_file_matching_supports_star_patterns():
    cfg = schema_audit._scan_mode_config(schema_audit._load_config(), "full")
    paths = [str(path.relative_to(PROJECT_ROOT)) for path in schema_audit._iter_paths(cfg["monitored_python_files"], cfg["exclude_python_files"])]

    assert "impl/core/pipeline.py" in paths
    assert "impl/server.py" in paths
    assert "impl/core/schema/table.py" not in paths


def test_schema_source_whitelist_filters_schema_files_from_function_scan():
    cfg = schema_audit._scan_mode_config(schema_audit._load_config(), "full")
    paths = [str(path.relative_to(PROJECT_ROOT)) for path in schema_audit._iter_paths(cfg["monitored_python_files"], cfg["exclude_python_files"])]

    assert "impl/core/schema/table.py" not in paths
    assert "impl/core/schema/judge.py" not in paths


def test_core_and_full_scan_modes_have_different_scope():
    core = schema_audit.audit("core")
    full = schema_audit.audit("full")

    assert core["summary"]["scan_mode"] == "core"
    assert full["summary"]["scan_mode"] == "full"
    assert full["summary"]["functions"] >= core["summary"]["functions"]


def test_audit_returns_structured_schema_report():
    result = schema_audit.audit()

    assert set(result) == {"passed", "summary", "functions", "schema_issues"}
    assert isinstance(result["passed"], bool)
    assert {"total", "by_severity", "errors", "warnings", "info", "functions", "schema_issues"}.issubset(result["summary"])
    assert isinstance(result["functions"], list)
    for item in result["functions"]:
        assert {"file", "function", "inputs", "outputs"}.issubset(item)
        assert isinstance(item["inputs"], list)
        assert isinstance(item["outputs"], list)
        for field in item["inputs"] + item["outputs"]:
            assert ": " in field
    assert isinstance(result["schema_issues"], list)


def test_required_layers_are_registered_without_error():
    issues = schema_audit.check_schema_registry(schema_audit._load_config())

    assert [issue.to_dict() for issue in issues if issue.severity == "error"] == []


def test_frontend_row_schema_scan_does_not_report_unknown_row_fields():
    issues = schema_audit.check_frontend_table_contract(schema_audit._load_config())
    unknown_row_field_errors = [issue for issue in issues if issue.kind == "frontend_row_field_not_in_trace_table_row"]

    assert unknown_row_field_errors == []


def test_python_boundary_scan_covers_schema_inputs_and_outputs():
    cfg = schema_audit._scan_mode_config(schema_audit._load_config(), "core")
    kinds = {issue.kind for issue in schema_audit.check_python_boundaries(cfg)}

    assert "dict_param_for_schema_concept" in kinds or "missing_input_schema_annotation" in kinds


def test_project_fields_boundary_scan_blocks_canonical_fact_reads():
    issues = schema_audit.check_project_fields_boundary(schema_audit._scan_mode_config(schema_audit._load_config(), "core"))

    assert [issue.to_dict() for issue in issues if issue.kind == "canonical_fact_from_project_fields"] == []


def test_audit_writes_report_file(tmp_path):
    cfg = schema_audit._load_config()
    cfg["audit"] = {**cfg.get("audit", {}), "report_file": str(tmp_path / "schema-report.json")}
    result = schema_audit.audit()
    report_path = schema_audit.write_report(result, cfg)

    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert set(data) == {"passed", "summary", "functions", "schema_issues"}


def test_hook_script_writes_report_and_prints_summary():
    proc = subprocess.run(["bash", str(HOOK_SCRIPT)], cwd=PROJECT_ROOT, text=True, capture_output=True)

    assert proc.stdout.strip(), proc.stderr
    assert "schema audit report:" in proc.stdout
    assert (HOOK_DIR / "schema-audit-report.json").exists()
    data = json.loads((HOOK_DIR / "schema-audit-report.json").read_text())
    assert set(data) == {"passed", "summary", "functions", "schema_issues"}
    assert proc.returncode == (0 if data["passed"] else 1)
