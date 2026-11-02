"""目录化后的公共入口、依赖方向与源码指纹边界。行为由原有 ToolLoop 回归覆盖。"""
import ast
import importlib
from pathlib import Path

import pytest

from impl.core import tool_loop
from impl.core.tool_loop import hooks, outputs, runtime, types

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "impl/core/tool_loop"
SOURCE_FILES = tuple(sorted(path.relative_to(ROOT).as_posix() for path in PACKAGE.glob("*.py")))


def test_public_entry_exports_the_same_component_objects():
    expected = {
        types: ["Abort", "Allow", "Call", "Continue", "Deny", "Done", "Failed", "History", "Hook", "HOOK_EVENTS",
                "LoopContext", "LoopResult", "PreDecision", "Step", "StepClient", "StopVerdict"],
        hooks: ["BudgetStop", "DEFAULT_BUDGET", "DependsOn", "RequireDone", "Rule", "after", "cites_read", "is_accepted", "until_accepted"],
        outputs: ["last_assistant_text", "take_accepted"],
        runtime: ["ToolLoop"],
    }
    assert set(tool_loop.__all__) == {name for names in expected.values() for name in names}
    for module, names in expected.items():
        for name in names:
            assert getattr(tool_loop, name) is getattr(module, name)
    assert tool_loop.ToolLoop.__module__ == "impl.core.tool_loop.runtime"
    assert runtime.DEFAULT_BUDGET is hooks.DEFAULT_BUDGET
    assert not (ROOT / "impl/core/tool_loop.py").exists()


def test_internal_modules_depend_downwards_not_on_public_entry():
    allowed = {"types": set(), "hooks": {"types"}, "outputs": {"types", "hooks"}, "runtime": {"types", "hooks", "outputs"}}
    for module, dependencies in allowed.items():
        tree = ast.parse((PACKAGE / f"{module}.py").read_text())
        local_imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 1}
        assert local_imports <= dependencies
        assert None not in local_imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert not (node.module or "").startswith(("impl.projects", "impl.server", "impl.core.llm_client"))


@pytest.mark.parametrize("module", [
    "impl.core.llm_client",
    "impl.projects.llm_probe.process_loop.analysis",
])
def test_existing_consumers_import_the_package(module):
    assert importlib.import_module(module)


def test_implementation_fingerprints_cover_every_package_source(tmp_path, monkeypatch):
    from impl.projects.llm_probe.eval_axes import runner
    from impl.projects.llm_probe.eval_axes.adapters.trace_analysis import AXIS_TYPE

    assert set(SOURCE_FILES) <= set(AXIS_TYPE.implementation_files)
    assert "impl/core/tool_loop.py" not in AXIS_TYPE.implementation_files

    for name in AXIS_TYPE.implementation_files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("initial source\n")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "_IMPLEMENTATION_FINGERPRINTS", {})

    def fingerprints():
        runner._IMPLEMENTATION_FINGERPRINTS.clear()
        return runner.implementation_fingerprint(AXIS_TYPE)

    baseline = fingerprints()
    for name in SOURCE_FILES:
        path = tmp_path / name
        path.write_text("changed source\n")
        changed = fingerprints()
        assert baseline != changed, name
        path.write_text("initial source\n")
        assert fingerprints() == baseline
