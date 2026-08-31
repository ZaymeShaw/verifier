"""g-provider 装载合同的 fail-fast（judge.md §8：不再是散落的 getattr 约定）。

四种装载失败各有其名、不互相伪装：
- 模块不存在 / 未声明 capability_provider / 声明不可调用 →
  CapabilityCarrierNotBound（接入未完成）；
- live 模块存在但装载崩溃 → 原始异常原样上抛，不得伪装成"缺 provider"。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import impl.projects as projects_pkg
from impl.core.capability_carrier import (
    CapabilityCarrierNotBound,
    bind_capability_carrier,
    resolve_capability_provider,
)


def _spec(project_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        project_id=project_id,
        verifier={"authority": {"enabled_scopes": ["capability_carrier"]}},
    )


@pytest.fixture()
def project_root(tmp_path, monkeypatch) -> Path:
    # impl.projects 是命名空间包：把临时目录挂进 __path__，即可放置夹具项目。
    monkeypatch.setattr(
        projects_pkg, "__path__", [*projects_pkg.__path__, str(tmp_path)],
    )
    return tmp_path


def _write_live(root: Path, project_id: str, body: str) -> None:
    package = root / project_id
    package.mkdir()
    (package / "live.py").write_text(body, encoding="utf-8")


def test_scope_off_never_binds() -> None:
    spec = SimpleNamespace(project_id="no_such_project", verifier={})
    assert bind_capability_carrier(spec) is None


def test_missing_module_is_not_bound() -> None:
    with pytest.raises(CapabilityCarrierNotBound) as exc:
        resolve_capability_provider(_spec("no_such_project_xyz"))
    assert "capability_provider" in str(exc.value)
    assert "不存在" in str(exc.value)


def test_missing_project_id_is_not_bound() -> None:
    with pytest.raises(CapabilityCarrierNotBound):
        resolve_capability_provider(SimpleNamespace(project_id=""))


def test_module_without_declaration_is_not_bound(project_root) -> None:
    _write_live(project_root, "undeclared_proj", "VALUE = 1\n")
    with pytest.raises(CapabilityCarrierNotBound) as exc:
        resolve_capability_provider(_spec("undeclared_proj"))
    assert "未声明 capability_provider" in str(exc.value)
    assert "undeclared_proj" in str(exc.value)


def test_non_callable_declaration_is_not_bound(project_root) -> None:
    _write_live(project_root, "noncallable_proj", "capability_provider = 42\n")
    with pytest.raises(CapabilityCarrierNotBound) as exc:
        resolve_capability_provider(_spec("noncallable_proj"))
    assert "不可调用" in str(exc.value)


def test_broken_module_surfaces_real_error(project_root) -> None:
    _write_live(
        project_root,
        "broken_proj",
        "raise RuntimeError('live module crashed at import')\n",
    )
    with pytest.raises(RuntimeError) as exc:
        resolve_capability_provider(_spec("broken_proj"))
    assert "live module crashed at import" in str(exc.value)


def test_bound_provider_resolves(project_root) -> None:
    _write_live(
        project_root,
        "bound_proj",
        "def capability_provider(spec):\n    return {'fields': {}}\n",
    )
    provider = resolve_capability_provider(_spec("bound_proj"))
    assert callable(provider)


def test_config_check_reports_unbound_and_import_error(project_root) -> None:
    from impl.core.config_check import ConfigCheckReport, _check_capability_carrier_binding

    _write_live(
        project_root,
        "broken_cfg_proj",
        "raise RuntimeError('boom')\n",
    )
    report = ConfigCheckReport()
    _check_capability_carrier_binding(
        report, _spec("missing_cfg_proj"), Path("impl/projects/missing_cfg_proj/project.yaml"),
    )
    _check_capability_carrier_binding(
        report, _spec("broken_cfg_proj"), Path("impl/projects/broken_cfg_proj/project.yaml"),
    )
    codes = {issue.code for issue in report.issues}
    assert codes == {"capability_carrier_unbound", "capability_provider_import_error"}
    unbound = next(i for i in report.issues if i.code == "capability_carrier_unbound")
    assert "capability_provider" in unbound.message
    crashed = next(i for i in report.issues if i.code == "capability_provider_import_error")
    assert "boom" in crashed.message
