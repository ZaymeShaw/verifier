#!/usr/bin/env python3
"""verify_protocol_compliance.py — 协议符合性探针

动态发现协议基类要求，校验项目是否完整实现：
  1. 角色发现：扫描 impl/core/*_protocol.py 的 Project<Role>，确认项目每个角色都有 <role>.py
  2. adapter 加载方法：确认 adapter 实现了所有 _load_*（对应每个角色）
  3. 实例化校验：import 项目各 <role>.py 的继承类，实例化，检查是否报
     TypeError: Can't instantiate abstract class（即 @abstractmethod 是否都实现了）

不写死方法名/基类文件名，从协议层现场读取要求。协议加新方法/新角色时，本探针自动卡住项目。
这是接入门禁的硬约束（区别于 check_adapter_compliance 的 adapter 静态合规检查）。

用法:
    bash run.sh python scripts/verify_protocol_compliance.py [--project <id>]
    不指定 --project 时检查所有项目。
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Type

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._protocol_discovery import (
    discover_adapter_bases,
    discover_role_bases,
)


def adapter_is_legacy(adapter_cls: Type, legacy_base: Type) -> bool:
    """adapter 是否走 LegacyProjectAdapter 兼容路径。"""
    return legacy_base is not None and issubclass(adapter_cls, legacy_base)


@dataclass
class Finding:
    level: str  # "error" | "warn"
    role: str
    message: str


@dataclass
class ProjectReport:
    project_id: str
    findings: List[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.level == "error" for f in self.findings)


def list_projects() -> List[str]:
    projects_dir = ROOT / "impl" / "projects"
    if not projects_dir.exists():
        return []
    return sorted(
        p.name for p in projects_dir.iterdir()
        if p.is_dir() and (p / "project.yaml").exists()
    )


def verify_project(project_id: str, roles: List[Tuple[str, Type]], adapter_base: Type, legacy_base: Type) -> ProjectReport:
    """校验单个项目。

    新协议项目（继承中转站 ProjectAdapter）：完整校验角色文件 + _load_* + 实例化。
    Legacy 兼容项目（继承 LegacyProjectAdapter）：只校验已实现 _load_* 的角色，缺失角色 warn。
    旧形态项目（继承旧版 impl.core.adapter.ProjectAdapter）：跳过新协议检查，warn 提示未迁移。
    """
    report = ProjectReport(project_id=project_id)
    project_dir = ROOT / "impl" / "projects" / project_id

    required_loads = sorted(getattr(adapter_base, "__abstractmethods__", set()))

    # 加载项目 adapter 模块
    adapter_path = project_dir / "adapter.py"
    adapter_cls = None
    if not adapter_path.exists():
        report.findings.append(Finding("error", "adapter", "adapter.py 不存在"))
    else:
        adapter_mod_name = f"impl_project_{project_id}_adapter_verify"
        try:
            spec = importlib.util.spec_from_file_location(adapter_mod_name, adapter_path)
            adapter_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter_mod)
        except Exception as exc:
            report.findings.append(Finding("error", "adapter", f"adapter.py 导入失败: {exc}"))
            adapter_mod = None
        if adapter_mod is not None:
            adapter_cls = getattr(adapter_mod, "Adapter", None)
            if adapter_cls is None:
                report.findings.append(Finding("error", "adapter", "adapter.py 未定义 Adapter 类"))

    # 判断 adapter 形态
    is_legacy = adapter_cls is not None and adapter_is_legacy(adapter_cls, legacy_base)
    is_station = adapter_cls is not None and issubclass(adapter_cls, adapter_base) and not is_legacy
    if adapter_cls is not None and not is_legacy and not is_station:
        # 旧形态（继承旧版 impl.core.adapter.ProjectAdapter，非 v2）
        report.findings.append(Finding(
            "warn", "adapter",
            "项目使用旧版 adapter（非 v2 中转站形态），未迁移到新协议，跳过新协议符合性检查。"
            "建议按 spec/adapter.md 迁移到 ProjectAdapter。"
        ))
        return report

    # 各角色：文件存在 + 类可实例化
    # Legacy 项目：只校验已实现 _load_<role> 的角色；缺失的 warn（兼容期允许）
    for role, role_base in roles:
        role_path = project_dir / f"{role}.py"
        load_method = f"_load_{role}"
        role_required = load_method in required_loads

        # Legacy 项目：项目自己没重写 _load_<role> 的角色，跳过（走旧路径）
        if is_legacy and adapter_cls is not None:
            project_defined = load_method in adapter_cls.__dict__
            if not project_defined:
                if role_required:
                    report.findings.append(Finding(
                        "warn", role,
                        f"Legacy 项目未迁移 {role} 角色（_load_{role} 未实现，走旧路径）。"
                    ))
                continue

        if not role_path.exists():
            if role_required and not is_legacy:
                report.findings.append(Finding("error", role, f"{role}.py 不存在"))
            else:
                report.findings.append(Finding("warn", role, f"{role}.py 不存在"))
            continue

        mod_name = f"impl_project_{project_id}_{role}_verify"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, role_path)
            role_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(role_mod)
        except Exception as exc:
            report.findings.append(Finding("error", role, f"{role}.py 导入失败: {exc}"))
            continue

        # 找继承 Project<Role> 的类
        impl_cls = None
        for attr in dir(role_mod):
            obj = getattr(role_mod, attr)
            if isinstance(obj, type) and issubclass(obj, role_base) and obj is not role_base:
                impl_cls = obj
                break
        if impl_cls is None:
            report.findings.append(Finding("error", role, f"{role}.py 未找到 {role_base.__name__} 的子类"))
            continue

        # 实例化校验：abstract 没全实现会报 TypeError: Can't instantiate abstract class
        missing = set(getattr(impl_cls, "__abstractmethods__", set()))
        if missing:
            report.findings.append(Finding(
                "error", role,
                f"{impl_cls.__name__} 未实现抽象方法: {sorted(missing)}（实例化会报 TypeError）"
            ))
        else:
            try:
                impl_cls(spec=None)
            except TypeError as exc:
                msg = str(exc)
                if "abstract" in msg.lower() or "Can't instantiate" in msg:
                    report.findings.append(Finding(
                        "error", role, f"{impl_cls.__name__} 实例化失败（abstract）: {msg}"
                    ))
                # else: __init__ 参数问题（如需要 adapter），忽略
            except Exception:
                pass

    # 新协议项目：adapter 的 _load_* 必须齐全
    if is_station and adapter_cls is not None:
        for load_method in required_loads:
            if not load_method.startswith("_load_") or load_method.endswith("_draft"):
                continue
            method = getattr(adapter_cls, load_method, None)
            if method is None or getattr(method, "__isabstractmethod__", False):
                report.findings.append(Finding(
                    "error", "adapter",
                    f"adapter 未实现 {load_method}()（仍是抽象方法）"
                ))

    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="协议符合性探针（实例化+角色发现）")
    parser.add_argument("--project", help="检查指定项目，默认检查所有项目")
    args = parser.parse_args(argv)

    roles = discover_role_bases()
    adapter_base, legacy_base = discover_adapter_bases()
    print(f"[verify] adapter 基类: {adapter_base.__module__}.{adapter_base.__name__}")
    if legacy_base:
        print(f"[verify] Legacy 兼容层: {legacy_base.__module__}.{legacy_base.__name__}")
    print(f"[verify] 发现角色: {[r for r, _ in roles]}")
    print(f"[verify] adapter _load_* 要求: {sorted(getattr(adapter_base, '__abstractmethods__', set()))}")
    print()

    projects = [args.project] if args.project else list_projects()
    if not projects:
        print("[verify] 没有可检查的项目")
        return 1

    all_passed = True
    for pid in projects:
        report = verify_project(pid, roles, adapter_base, legacy_base)
        status = "✅ 通过" if report.passed else "❌ 不通过"
        print(f"[verify] {pid}: {status}")
        for f in report.findings:
            tag = "ERROR" if f.level == "error" else "WARN"
            print(f"    [{tag}] {f.role}: {f.message}")
        if not report.passed:
            all_passed = False
        print()

    if all_passed:
        print(f"[verify] 全部通过（{len(projects)} 个项目）")
        return 0
    print(f"[verify] 存在不通过的项目")
    return 1


if __name__ == "__main__":
    sys.exit(main())
