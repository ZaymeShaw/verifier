from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Optional

from .config import ROOT, resolve_runtime_config
from .config_bootstrap import render_env_example
from .config_schema import ConfigError, EnvironmentRegistry, EnvironmentVariableSpec, load_yaml_document
from .knowledge_route import load_project_knowledge_route
from .project_config import parse_project_document, resolve_project_config


_PERSONAL_PATH = re.compile(r"/(?:Users|home)/[^/\s]+/")


@dataclass(frozen=True)
class ConfigCheckIssue:
    code: str
    message: str
    path: str = ""
    line: int = 0


@dataclass
class ConfigCheckReport:
    ok: bool = True
    issues: list[ConfigCheckIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def add(self, issue: ConfigCheckIssue) -> None:
        self.ok = False
        self.issues.append(issue)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "fingerprint": self.fingerprint,
            "issues": [issue.__dict__ for issue in self.issues],
            "warnings": list(self.warnings),
        }


def check_runtime_config_contract(
    *,
    root: Path = ROOT,
    environ: Optional[Mapping[str, str]] = None,
    require_runtime_secrets: bool = False,
) -> ConfigCheckReport:
    report = ConfigCheckReport()
    config_path = root / "impl" / "config.yaml"
    dotenv_path = root / ".env"
    try:
        resolved = resolve_runtime_config(
            config_path=config_path,
            dotenv_path=dotenv_path,
            environ=environ,
        )
    except ConfigError as exc:
        report.add(ConfigCheckIssue(code="config_invalid", message=str(exc), path=str(config_path)))
        return report

    report.fingerprint = resolved.fingerprint()
    report.warnings.extend(resolved.warnings)
    if resolved.missing_required:
        message = f"missing required runtime values: {', '.join(resolved.missing_required)}"
        if require_runtime_secrets:
            report.add(ConfigCheckIssue(code="required_value_missing", message=message))
        else:
            report.warnings.append(message)

    project_registries: dict[str, EnvironmentRegistry] = {}
    knowledge_registries: dict[str, EnvironmentRegistry] = {}
    impl_projects = {
        path.parent.name: path
        for path in sorted((root / "impl" / "projects").glob("*/project.yaml"))
    }
    knowledge_projects = {
        path.parent.name: path
        for path in sorted((root / "projects").glob("*/project.yaml"))
    }
    if set(impl_projects) != set(knowledge_projects):
        missing_impl = sorted(set(knowledge_projects) - set(impl_projects))
        missing_route = sorted(set(impl_projects) - set(knowledge_projects))
        report.add(
            ConfigCheckIssue(
                code="project_route_mismatch",
                message=f"impl-only={missing_route}; knowledge-only={missing_impl}",
                path=str(root / "projects"),
            )
        )
    for project_id, config_file in impl_projects.items():
        try:
            spec = resolve_project_config(
                project_id,
                projects_dir=root / "impl" / "projects",
                dotenv_path=dotenv_path,
                environ=environ,
            )
            project_registries[project_id] = spec.environment or EnvironmentRegistry(MappingProxyType({}))
            report.warnings.extend(spec.metadata.get("warnings") or [])
        except (ConfigError, OSError) as exc:
            report.add(ConfigCheckIssue(code="project_config_invalid", message=str(exc), path=str(config_file)))
        for line, value in _personal_paths(config_file.read_text(encoding="utf-8")):
            report.add(ConfigCheckIssue("personal_path", f"project config contains personal path: {value}", str(config_file), line))
    for project_id, route_file in knowledge_projects.items():
        try:
            route = load_project_knowledge_route(project_id, knowledge_root=root / "projects")
            knowledge_registries[project_id] = route.environment
        except (ConfigError, OSError) as exc:
            report.add(ConfigCheckIssue(code="knowledge_route_invalid", message=str(exc), path=str(route_file)))
        for line, value in _personal_paths(route_file.read_text(encoding="utf-8")):
            report.add(ConfigCheckIssue("personal_path", f"knowledge route contains personal path: {value}", str(route_file), line))
    _check_cross_layer_environments(report, project_registries, knowledge_registries)

    template_path = root / "impl" / "projects" / "project.template.yaml"
    try:
        parse_project_document(load_yaml_document(template_path), project_id=None, project_root=template_path.parent)
    except (ConfigError, OSError) as exc:
        report.add(ConfigCheckIssue("project_template_invalid", str(exc), str(template_path)))

    for line, value in _personal_paths(config_path.read_text(encoding="utf-8")):
        report.add(
            ConfigCheckIssue(
                code="personal_path",
                message=f"public config contains a developer-specific absolute path: {value}",
                path=str(config_path),
                line=line,
            )
        )

    gitignore_path = root / ".gitignore"
    ignored = {
        line.strip()
        for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    } if gitignore_path.is_file() else set()
    if ".env" not in ignored:
        report.add(
            ConfigCheckIssue(
                code="dotenv_not_ignored",
                message="repository root .env must be ignored by Git",
                path=str(gitignore_path),
            )
        )

    env_example_path = root / ".env.example"
    combined_environment = _combined_environment(
        report,
        resolved.environment,
        project_registries,
        knowledge_registries,
    )
    expected_example = render_env_example(combined_environment)
    actual_example = env_example_path.read_text(encoding="utf-8") if env_example_path.is_file() else ""
    if actual_example != expected_example:
        report.add(
            ConfigCheckIssue(
                code="env_example_stale",
                message=".env.example must be generated from impl/config.yaml",
                path=str(env_example_path),
            )
        )

    for issue in _scan_public_config_bypasses(root, combined_environment.accepted_names()):
        report.add(issue)
    return report


def _check_cross_layer_environments(
    report: ConfigCheckReport,
    project_registries: Mapping[str, EnvironmentRegistry],
    knowledge_registries: Mapping[str, EnvironmentRegistry],
) -> None:
    for project_id in sorted(set(project_registries) & set(knowledge_registries)):
        impl_variables = project_registries[project_id].variables
        route_variables = knowledge_registries[project_id].variables
        for name in sorted(set(impl_variables) & set(route_variables)):
            impl = impl_variables[name]
            route = route_variables[name]
            if (impl.type, impl.required, impl.secret) != (route.type, route.required, route.secret):
                report.add(
                    ConfigCheckIssue(
                        code="environment_contract_mismatch",
                        message=f"{name} has inconsistent type/required/secret across project and knowledge route",
                        path=project_id,
                    )
                )


def _combined_environment(
    report: ConfigCheckReport,
    public: EnvironmentRegistry,
    project_registries: Mapping[str, EnvironmentRegistry],
    knowledge_registries: Mapping[str, EnvironmentRegistry],
) -> EnvironmentRegistry:
    variables: dict[str, EnvironmentVariableSpec] = dict(public.variables)
    owners: dict[str, str] = {name: "public" for name in variables}
    for layer, registries in (("project", project_registries), ("knowledge", knowledge_registries)):
        for project_id, registry in registries.items():
            for name, variable in registry.variables.items():
                existing = variables.get(name)
                if existing is None:
                    variables[name] = variable
                    owners[name] = f"{layer}:{project_id}"
                    continue
                same_project_pair = owners[name] in {f"project:{project_id}", f"knowledge:{project_id}"}
                compatible = (existing.type, existing.required, existing.secret) == (
                    variable.type,
                    variable.required,
                    variable.secret,
                )
                if not same_project_pair or not compatible:
                    report.add(
                        ConfigCheckIssue(
                            code="environment_name_duplicate",
                            message=f"{name} is defined by both {owners[name]} and {layer}:{project_id}",
                        )
                    )
                elif layer == "project":
                    variables[name] = variable
                    owners[name] = f"project:{project_id}"
    return EnvironmentRegistry(variables=MappingProxyType(variables))


def _scan_public_config_bypasses(root: Path, registered_names: Iterable[str]) -> list[ConfigCheckIssue]:
    names = frozenset(registered_names)
    issues: list[ConfigCheckIssue] = []
    scan_roots = [root / "impl" / "core", root / "impl" / "server", root / "impl" / "checklist"]
    excluded = {
        (root / "impl" / "core" / "config.py").resolve(),
        (root / "impl" / "core" / "config_schema.py").resolve(),
        (root / "impl" / "core" / "config_bootstrap.py").resolve(),
        (root / "impl" / "core" / "config_check.py").resolve(),
    }
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob("*.py")):
            if path.resolve() in excluded:
                continue
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text, filename=str(path))
            except (OSError, SyntaxError) as exc:
                issues.append(
                    ConfigCheckIssue(
                        code="scan_failed",
                        message=str(exc),
                        path=str(path),
                    )
                )
                continue
            visitor = _EnvironmentReadVisitor(names)
            visitor.visit(tree)
            for line, name in visitor.reads:
                issues.append(
                    ConfigCheckIssue(
                        code="public_env_bypass",
                        message=f"registered public variable {name} must be read by RuntimeConfigResolver",
                        path=str(path),
                        line=line,
                    )
                )
            for line, marker in _forbidden_markers(text):
                issues.append(
                    ConfigCheckIssue(
                        code="public_config_fallback",
                        message=f"forbidden public config fallback marker: {marker}",
                        path=str(path),
                        line=line,
                    )
                )
            for line, value in _personal_paths(text):
                issues.append(
                    ConfigCheckIssue(
                        code="personal_path",
                        message=f"runtime consumer contains a developer-specific absolute path: {value}",
                        path=str(path),
                        line=line,
                    )
                )
    return issues


class _EnvironmentReadVisitor(ast.NodeVisitor):
    def __init__(self, names: frozenset[str]):
        self.names = names
        self.reads: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        if _is_os_getenv(node.func) or _is_os_environ_get(node.func):
            name = _literal_name(node.args[0]) if node.args else None
            if name in self.names:
                self.reads.append((node.lineno, str(name)))
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_os_environ(node.value):
            name = _literal_name(node.slice)
            if name in self.names:
                self.reads.append((node.lineno, str(name)))
        self.generic_visit(node)


def _is_os_getenv(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "getenv"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _is_os_environ_get(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "get" and _is_os_environ(node.value)


def _literal_name(node: ast.AST) -> Optional[str]:
    return str(node.value) if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _forbidden_markers(text: str) -> list[tuple[int, str]]:
    markers = ("load_env_md_key", "load_bailian_env_md_key", "MODEL_DEFAULT", "BASE_URL_DEFAULT")
    found: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for marker in markers:
            if marker in line:
                found.append((line_number, marker))
    return found


def _personal_paths(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = _PERSONAL_PATH.search(line)
        if match:
            found.append((line_number, match.group(0).rstrip("/")))
    return found


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the verifier configuration contract")
    parser.add_argument("--require-runtime-secrets", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    report = check_runtime_config_contract(require_runtime_secrets=args.require_runtime_secrets)
    if args.as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"config-check: {'ok' if report.ok else 'failed'} ({report.fingerprint or 'unresolved'})")
        for warning in report.warnings:
            print(f"warning: {warning}")
        for issue in report.issues:
            location = f"{issue.path}:{issue.line}" if issue.line else issue.path
            print(f"error[{issue.code}] {location}: {issue.message}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
