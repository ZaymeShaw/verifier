#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    import yaml
except Exception:  # pragma: no cover - exercised by shell usage when pyyaml missing
    yaml = None

HOOK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = HOOK_DIR.parent.parent
CONFIG_FILE = HOOK_DIR / "config.yaml"


CANONICAL_PROJECT_FIELD_NAMES = {
    "reference",
    "reference_contract",
    "expected",
    "golden_answer",
    "gold_answer",
    "scenario",
    "execution_mode",
    "output_source",
    "application_boundary",
    "expected_intent",
    "metadata",
    "data_quality_flags",
    "case_id",
    "conversation_summary",
    "conversation_transcript",
    "multi_turn_input",
}

PROJECT_FIELDS_ALLOWED_CONTEXTS = {
    "schema_protocol_extensions",
    "build_frontend_extensions",
    "_compact_mapping(compact_trace.pop(\"project_fields\"",
    "_compact_mapping(compact_trace.pop('project_fields'",
}


@dataclass
class Issue:
    kind: str
    severity: str
    file: str
    message: str
    line: int | None = None
    symbol: str = ""
    direction: str = ""
    detected_format: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "kind": self.kind,
            "severity": self.severity,
            "file": self.file,
            "message": self.message,
        }
        if self.line is not None:
            data["line"] = self.line
        if self.symbol:
            data["symbol"] = self.symbol
        if self.direction:
            data["direction"] = self.direction
        if self.detected_format:
            data["detected_format"] = self.detected_format
        if self.evidence:
            data["evidence"] = self.evidence
        return data


def _load_config() -> Dict[str, Any]:
    text = CONFIG_FILE.read_text(encoding="utf-8")
    if yaml:
        return yaml.safe_load(text)
    return _minimal_yaml(text)


def _minimal_yaml(text: str) -> Dict[str, Any]:
    # Fallback parser for this config's simple top-level/list/dict shape.
    result: Dict[str, Any] = {}
    stack: List[tuple[int, Any, str | None]] = [(-1, result, None)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            if not isinstance(parent, list):
                continue
            parent.append(_scalar(line[2:].strip()))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            parent[key] = _scalar(value)
            continue
        # Guess child type from next meaningful line by defaulting to dict, then fix lists lazily.
        child: Any = [] if key in {"required_layers", "monitored_python_files", "monitored_frontend_files", "allowed_compat_wrapper_patterns", "support_only_layers", "support_only_schemas", "keywords", "schemas", "block_on"} else {}
        parent[key] = child
        stack.append((indent, child, key))
    return result


def _scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.startswith("[") and value.endswith("]"):
        return [item.strip().strip('"').strip("'") for item in value[1:-1].split(",") if item.strip()]
    return value


def _rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _schema_classes(schema_dir: Path) -> Dict[str, str]:
    classes: Dict[str, str] = {}
    for path in schema_dir.glob("*.py"):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(_read(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = _rel(path)
    return classes


def _exported_names(exports_file: Path) -> set[str]:
    text = _read(exports_file)
    names = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', text))
    names.update(re.findall(r"from \.[a-z_]+ import ([^\n]+)", text))
    expanded: set[str] = set()
    for item in names:
        for part in item.split(","):
            name = part.strip().split(" as ")[0].strip()
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                expanded.add(name)
    return expanded


def _registry_layers(registry_file: Path) -> set[str]:
    text = _read(registry_file)
    return set(re.findall(r'"([a-z_]+)"\s*:', text))


def _is_compat(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _annotation_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _contains_schema_keyword(name: str, cfg: Dict[str, Any]) -> bool:
    lowered = name.lower()
    for spec in (cfg.get("schema_concepts") or {}).values():
        for keyword in spec.get("keywords", []):
            if keyword.lower() in lowered:
                return True
    return False


def check_schema_registry(cfg: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    registry = _registry_layers(PROJECT_ROOT / cfg["schema_registry_file"])
    required = set(cfg.get("required_layers") or [])
    missing = sorted(required - registry)
    for layer in missing:
        issues.append(
            Issue(
                kind="missing_required_schema_layer",
                severity="error",
                file=cfg["schema_registry_file"],
                symbol=layer,
                message=f"Required schema layer '{layer}' from demand/schema.md is not registered in SCHEMA_LAYERS.",
                detected_format="missing registry entry",
            )
        )
    return issues


def check_schema_exports(cfg: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    schema_dir = PROJECT_ROOT / cfg["schema_modules_dir"]
    classes = _schema_classes(schema_dir)
    exported = _exported_names(PROJECT_ROOT / cfg["schema_exports_file"])
    support = set(cfg.get("support_only_schemas") or [])
    for cls, file in sorted(classes.items()):
        if cls.startswith("_"):
            continue
        if cls not in exported and cls not in support:
            issues.append(
                Issue(
                    kind="schema_class_not_exported",
                    severity="error",
                    file=file,
                    symbol=cls,
                    message=f"Schema class '{cls}' exists but is not exported from impl.core.schema.",
                    detected_format="schema class not exported",
                )
            )
    return issues


def _scan_mode_config(cfg: Dict[str, Any], mode: str | None = None) -> Dict[str, Any]:
    modes = cfg.get("scan_modes") or {}
    selected = mode or cfg.get("default_scan_mode") or "core"
    if selected not in modes:
        raise ValueError(f"unknown schema scan mode: {selected}")
    mode_cfg = modes[selected]
    merged = dict(cfg)
    merged["scan_mode"] = selected
    merged["monitored_python_files"] = mode_cfg.get("python_files", [])
    merged["monitored_frontend_files"] = mode_cfg.get("frontend_files", [])
    merged["exclude_python_files"] = list(mode_cfg.get("exclude_python_files", [])) + list(cfg.get("schema_source_whitelist") or [])
    merged["exclude_frontend_files"] = mode_cfg.get("exclude_frontend_files", [])
    return merged


def _iter_paths(patterns: Iterable[str], exclude_patterns: Iterable[str] = ()) -> List[Path]:
    paths: set[Path] = set()
    excludes = list(exclude_patterns or [])
    for pattern in patterns or []:
        matches = PROJECT_ROOT.glob(pattern) if any(ch in pattern for ch in "*?[]") else [PROJECT_ROOT / pattern]
        for path in matches:
            if not path.is_file():
                continue
            rel = _rel(path)
            if any(fnmatch.fnmatch(rel, ex) for ex in excludes):
                continue
            paths.add(path)
    return sorted(paths)


def _runtime_text(cfg: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for path in _iter_paths(cfg.get("monitored_python_files") or [], cfg.get("exclude_python_files") or []):
        chunks.append(_read(path))
    return "\n".join(chunks)


def check_schema_usage(cfg: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    classes = _schema_classes(PROJECT_ROOT / cfg["schema_modules_dir"])
    support = set(cfg.get("support_only_schemas") or [])
    runtime = _runtime_text(cfg)
    for cls, file in sorted(classes.items()):
        if cls in support or cls.startswith("_"):
            continue
        count = len(re.findall(rf"\b{re.escape(cls)}\b", runtime))
        if count == 0:
            issues.append(
                Issue(
                    kind="schema_declared_but_not_used",
                    severity="warning",
                    file=file,
                    symbol=cls,
                    message=f"Schema class '{cls}' is declared/exported but not used in monitored runtime handoff modules.",
                    detected_format="declared schema class with no monitored runtime usage",
                )
            )
    return issues


def check_python_boundaries(cfg: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    compat_patterns = cfg.get("allowed_compat_wrapper_patterns") or []
    for path in _iter_paths(cfg.get("monitored_python_files") or [], cfg.get("exclude_python_files") or []):
        rel = _rel(path)
        try:
            tree = ast.parse(_read(path))
        except SyntaxError as exc:
            issues.append(Issue("python_parse_error", "error", rel, str(exc), getattr(exc, "lineno", None)))
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            compat = _is_compat(name, compat_patterns)
            schema_like_function = _contains_schema_keyword(name, cfg)
            returns = _annotation_text(node.returns)

            # Output scan: schema-like functions should make their output contract explicit and schema-backed.
            if schema_like_function and not returns and not compat:
                issues.append(
                    Issue(
                        kind="missing_output_schema_annotation",
                        severity="warning",
                        file=rel,
                        line=node.lineno,
                        symbol=name,
                        message=f"Function '{name}' appears to be a schema boundary but has no return annotation.",
                        direction="output",
                        detected_format="missing return annotation",
                    )
                )
            if schema_like_function and returns in {"dict", "Dict[str, Any]", "Dict", "Any"} and not compat:
                issues.append(
                    Issue(
                        kind="dict_return_for_schema_concept",
                        severity="error",
                        file=rel,
                        line=node.lineno,
                        symbol=name,
                        message=f"Function '{name}' appears to be a schema boundary but returns '{returns}'.",
                        direction="output",
                        detected_format=returns,
                    )
                )

            # Input scan: schema-like parameters should be typed as schema objects, not loose dict/Any/missing.
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if arg.arg in {"self", "cls"}:
                    continue
                annotation = _annotation_text(arg.annotation)
                schema_like_param = _contains_schema_keyword(arg.arg, cfg) or schema_like_function
                if not schema_like_param:
                    continue
                if not annotation and not compat:
                    issues.append(
                        Issue(
                            kind="missing_input_schema_annotation",
                            severity="warning",
                            file=rel,
                            line=node.lineno,
                            symbol=f"{name}.{arg.arg}",
                            message=f"Parameter '{arg.arg}' in '{name}' is schema-like but has no type annotation.",
                            direction="input",
                            detected_format="missing parameter annotation",
                        )
                    )
                    continue
                if annotation in {"dict", "Dict[str, Any]", "Dict", "Any"}:
                    issues.append(
                        Issue(
                            kind="dict_param_for_schema_concept",
                            severity="info" if compat else "warning",
                            file=rel,
                            line=node.lineno,
                            symbol=f"{name}.{arg.arg}",
                            message=f"Parameter '{arg.arg}' in '{name}' uses '{annotation}' for a schema-like concept.",
                            direction="input",
                            detected_format=annotation,
                        )
                    )
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict) and schema_like_function and not compat:
                    issues.append(
                        Issue(
                            kind="literal_dict_return_in_schema_boundary",
                            severity="warning",
                            file=rel,
                            line=getattr(child, "lineno", node.lineno),
                            symbol=name,
                            message=f"Function '{name}' returns a literal dict while its name suggests a schema boundary.",
                            direction="output",
                            detected_format="literal dict",
                        )
                    )
    return issues


def _literal_string(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _source_segment(text: str, node: ast.AST) -> str:
    try:
        return ast.get_source_segment(text, node) or ""
    except Exception:
        return ""


def check_project_fields_boundary(cfg: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    for path in _iter_paths(cfg.get("monitored_python_files") or [], cfg.get("exclude_python_files") or []):
        rel = _rel(path)
        text = _read(path)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Subscript, ast.Call, ast.Attribute)):
                continue
            source = _source_segment(text, node)
            if "project_fields" not in source:
                continue
            if any(marker in source for marker in PROJECT_FIELDS_ALLOWED_CONTEXTS):
                continue
            line = getattr(node, "lineno", None)
            canonical_key = ""
            if isinstance(node, ast.Subscript):
                target = _source_segment(text, node.value)
                key = _literal_string(node.slice)
                if target.endswith("project_fields") or "project_fields" in target:
                    canonical_key = key
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = _source_segment(text, node.func.value)
                if node.func.attr == "get" and (target.endswith("project_fields") or "project_fields" in target):
                    canonical_key = _literal_string(node.args[0]) if node.args else ""
            elif isinstance(node, ast.Attribute):
                if node.attr == "project_fields" and "schema_protocol_extensions" not in source:
                    issues.append(
                        Issue(
                            kind="project_fields_boundary_read",
                            severity="warning",
                            file=rel,
                            line=line,
                            symbol="project_fields",
                            message="project_fields is adapter-private; runtime consumers should prefer typed schema fields unless this is only extension display.",
                            detected_format=source.strip(),
                        )
                    )
                    continue
            if canonical_key in CANONICAL_PROJECT_FIELD_NAMES:
                issues.append(
                    Issue(
                        kind="canonical_fact_from_project_fields",
                        severity="error",
                        file=rel,
                        line=line,
                        symbol=canonical_key,
                        message=f"Canonical protocol fact '{canonical_key}' must not be read from project_fields/schema_protocol_extensions.",
                        detected_format=source.strip(),
                    )
                )
            elif canonical_key:
                issues.append(
                    Issue(
                        kind="project_fields_boundary_read",
                        severity="warning",
                        file=rel,
                        line=line,
                        symbol=canonical_key,
                        message="project_fields reads are extension-only; promote consumed runtime facts into typed schema fields or extracted_output.",
                        detected_format=source.strip(),
                    )
                )
    return issues
def check_occam_field_roles(cfg: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    try:
        from impl.core.schema.occam import SCHEMA_FIELD_ROLES, field_role
    except Exception as exc:
        return [Issue("occam_roles_unavailable", "error", "impl/core/schema/occam.py", f"Occam field role map cannot be imported: {exc}")]

    for schema_name, role_map in SCHEMA_FIELD_ROLES.items():
        for role, fields in role_map.items():
            for field_name in fields:
                if field_role(schema_name, field_name) != role:
                    issues.append(
                        Issue(
                            kind="occam_field_role_inconsistent",
                            severity="error",
                            file="impl/core/schema/occam.py",
                            symbol=f"{schema_name}.{field_name}",
                            message=f"Occam role map cannot resolve {schema_name}.{field_name} as {role}.",
                            detected_format=role,
                        )
                    )
    return issues


def check_occam_runtime_invariants(cfg: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    try:
        from impl.core.schema.fixture import load_fixture
    except Exception as exc:
        return [Issue("occam_fixture_unavailable", "error", "impl/core/schema/fixture", f"Schema fixtures cannot be loaded for Occam invariant check: {exc}")]

    trace = load_fixture("impl.core.schema.trace.RunTrace")
    live = getattr(trace, "live_result", None)
    if live is not None:
        paired_fields = [
            ("normalized_request", trace.normalized_request, live.normalized_request),
            ("raw_response", trace.raw_response, live.raw_response),
            ("extracted_output", trace.extracted_output, live.extracted_output),
            ("output_source", trace.output_source, live.output_source),
            ("application_boundary", trace.application_boundary, live.application_boundary),
            ("project_fields", trace.project_fields, live.project_fields),
        ]
        for field_name, trace_value, live_value in paired_fields:
            if trace_value != live_value:
                issues.append(
                    Issue(
                        kind="run_trace_live_result_derived_alias_diverged",
                        severity="error",
                        file="impl/core/schema/trace.py",
                        symbol=f"RunTrace.{field_name}",
                        message=f"RunTrace.{field_name} is a derived_alias of live_result.{field_name} but the fixture values diverge.",
                        detected_format="derived_alias divergence",
                    )
                )

    judge = load_fixture("impl.core.schema.judge.JudgeResult")
    statuses = [getattr(item, "status", "") if not isinstance(item, dict) else item.get("status", "") for item in judge.fulfillment_assessments]
    if statuses:
        expected_status = "not_fulfilled" if any(status == "not_fulfilled" for status in statuses) else "fulfilled" if all(status == "fulfilled" for status in statuses) else "not_evaluable"
        actual_status = (judge.overall_fulfillment or {}).get("status")
        if actual_status != expected_status:
            issues.append(
                Issue(
                    kind="judge_overall_fulfillment_diverged",
                    severity="error",
                    file="impl/core/schema/judge.py",
                    symbol="JudgeResult.overall_fulfillment",
                    message="JudgeResult.overall_fulfillment.status must remain derived from fulfillment_assessments in canonical fixtures.",
                    detected_format=f"{actual_status} != {expected_status}",
                )
            )

    attribute = load_fixture("impl.core.schema.attribute.AttributeResult")
    divergence = attribute.earliest_divergence if isinstance(attribute.earliest_divergence, dict) else {}
    if attribute.causal_category and not (divergence.get("stage") or divergence.get("node")):
        issues.append(
            Issue(
                kind="attribute_missing_canonical_divergence",
                severity="error",
                file="impl/core/schema/attribute.py",
                symbol="AttributeResult.earliest_divergence",
                message="AttributeResult should locate causal_category through earliest_divergence.stage or earliest_divergence.node in canonical fixtures.",
                detected_format="missing earliest_divergence stage/node",
            )
        )
    return issues

def _table_fields() -> set[str]:
    path = PROJECT_ROOT / "impl/core/schema/table.py"
    tree = ast.parse(_read(path))
    fields: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "TraceTableRow":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fields.add(stmt.target.id)
    return fields


def check_frontend_table_contract(cfg: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    table_fields = _table_fields()
    allowed = table_fields | {"table_row", "run", "case_id", "id", "selected", "source", "input", "output", "reference", "metadata", "dataset_id", "dimension_type", "dataset_name", "error", "trace", "judge", "attribute", "frontend_view", "cluster", "check"}
    for path in _iter_paths(cfg.get("monitored_frontend_files") or [], cfg.get("exclude_frontend_files") or []):
        rel = _rel(path)
        text = _read(path)
        if "function tableRow" not in text:
            issues.append(
                Issue(
                    kind="frontend_missing_table_row_accessor",
                    severity="error",
                    file=rel,
                    message="Frontend summary does not define tableRow(item); table display should read TraceTableRow schema first.",
                    detected_format="missing tableRow accessor",
                )
            )
        for match in re.finditer(r"\brow\.([A-Za-z_][A-Za-z0-9_]*)", text):
            field = match.group(1)
            if field not in table_fields:
                line = text[: match.start()].count("\n") + 1
                issues.append(
                    Issue(
                        kind="frontend_row_field_not_in_trace_table_row",
                        severity="error",
                        file=rel,
                        line=line,
                        symbol=field,
                        message=f"Frontend reads row.{field}, but TraceTableRow does not declare this field.",
                        detected_format="frontend row field outside TraceTableRow",
                    )
                )
        # High-signal direct item fields in renderCasePool can indicate bypassing row schema.
        render_case_pool = re.search(r"function renderCasePool\(\).*?function outputSummary", text, flags=re.S)
        if render_case_pool:
            block = render_case_pool.group(0)
            for match in re.finditer(r"\bx\.([A-Za-z_][A-Za-z0-9_]*)", block):
                field = match.group(1)
                if field not in allowed and field not in {"selected"}:
                    line = text[: render_case_pool.start() + match.start()].count("\n") + 1
                    issues.append(
                        Issue(
                            kind="frontend_table_direct_field_bypass",
                            severity="warning",
                            file=rel,
                            line=line,
                            symbol=field,
                            message=f"Summary table render reads x.{field} directly; table columns should prefer tableRow(item).",
                            detected_format="direct frontend item field",
                        )
                    )
    return issues


def _function_report(issues: List[Issue]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for issue in issues:
        if issue.direction not in {"input", "output"}:
            continue
        function = issue.symbol.split(".", 1)[0] if issue.symbol else ""
        field = issue.symbol.split(".", 1)[1] if "." in issue.symbol else "return"
        if issue.direction == "output":
            field = "return"
        key = (issue.file, function)
        item = grouped.setdefault(
            key,
            {
                "file": issue.file,
                "line": issue.line,
                "function": function,
                "inputs": [],
                "outputs": [],
            },
        )
        if item.get("line") is None or (issue.line is not None and issue.line < item["line"]):
            item["line"] = issue.line
        entry = f"{field}: {issue.detected_format or 'unknown'}"
        target = "inputs" if issue.direction == "input" else "outputs"
        if entry not in item[target]:
            item[target].append(entry)
    return sorted(grouped.values(), key=lambda item: (item["file"], item.get("line") or 0, item["function"]))


def _schema_issue_report(issues: List[Issue]) -> List[Dict[str, Any]]:
    result = []
    for issue in issues:
        if issue.direction in {"input", "output"}:
            continue
        result.append(
            {
                "kind": issue.kind,
                "severity": issue.severity,
                "file": issue.file,
                "line": issue.line,
                "field": issue.symbol,
                "detected_format": issue.detected_format or "unknown",
            }
        )
    return result


def audit(mode: str | None = None) -> Dict[str, Any]:
    cfg = _scan_mode_config(_load_config(), mode)
    issues: List[Issue] = []
    for check in (check_schema_registry, check_schema_exports, check_schema_usage, check_python_boundaries, check_project_fields_boundary, check_frontend_table_contract, check_occam_field_roles, check_occam_runtime_invariants):
        issues.extend(check(cfg))
    block_on = set((cfg.get("audit") or {}).get("block_on") or ["error"])
    passed = not any(issue.severity in block_on for issue in issues)
    counts: Dict[str, int] = {}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return {
        "passed": passed,
        "summary": {
            "scan_mode": cfg.get("scan_mode", "core"),
            "total": len(issues),
            "by_severity": counts,
            "errors": counts.get("error", 0),
            "warnings": counts.get("warning", 0),
            "info": counts.get("info", 0),
            "functions": len(_function_report(issues)),
            "schema_issues": len(_schema_issue_report(issues)),
        },
        "functions": _function_report(issues),
        "schema_issues": _schema_issue_report(issues),
    }


def _report_path(cfg: Dict[str, Any]) -> Path:
    report_file = (cfg.get("audit") or {}).get("report_file") or "hooks/schema/schema-audit-report.json"
    path = Path(report_file)
    return path if path.is_absolute() else PROJECT_ROOT / path


def write_report(result: Dict[str, Any], cfg: Dict[str, Any] | None = None) -> Path:
    cfg = cfg or _load_config()
    path = _report_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit schema-centric propagation.")
    parser.add_argument("--mode", choices=["core", "full"], default=None, help="Scan mode: core boundary files or full project patterns.")
    args = parser.parse_args()
    cfg = _scan_mode_config(_load_config(), args.mode)
    result = audit(args.mode)
    report_path = write_report(result, cfg)
    print(f"schema audit report: {report_path}")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
