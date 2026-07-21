from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .config import ROOT, resolve_runtime_config
from .config_bootstrap import render_env_example
from .config_schema import ConfigError


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
    expected_example = render_env_example(resolved.environment)
    actual_example = env_example_path.read_text(encoding="utf-8") if env_example_path.is_file() else ""
    if actual_example != expected_example:
        report.add(
            ConfigCheckIssue(
                code="env_example_stale",
                message=".env.example must be generated from impl/config.yaml",
                path=str(env_example_path),
            )
        )

    for issue in _scan_public_config_bypasses(root, resolved.environment.accepted_names()):
        report.add(issue)
    return report


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
    parser = argparse.ArgumentParser(description="Validate the verifier public configuration contract")
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
