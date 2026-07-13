#!/usr/bin/env python3
"""scaffold_project.py — 动态生成项目骨架

按 spec/adapter.md 的协议分层，扫描 impl/core 下的协议基类，
现场生成 impl/projects/<project>/ 下的项目层骨架。

不写死方法名/基类文件名：角色基类从 *_protocol.py 的 Project<Role> 发现，
必须实现项从 __abstractmethods__ 发现，adapter 基类动态发现。
协议演进（新增抽象方法、新增角色、基类改名）时，生成内容自动跟着变。

用法:
    bash run.sh python scripts/scaffold_project.py --project <id> [--force]
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Type

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._protocol_discovery import (
    class_prefix,
    discover_adapter_base,
    discover_role_bases,
)


def adapter_load_methods(adapter_base: Type) -> List[str]:
    """返回 adapter 基类的 _load_* 抽象方法名列表。"""
    return sorted(getattr(adapter_base, "__abstractmethods__", set()))


def role_required_methods(role_base: Type) -> List[str]:
    """返回角色基类必须实现的抽象方法名（@abstractmethod）。"""
    return sorted(getattr(role_base, "__abstractmethods__", set()))


def _method_signature(cls: Type, name: str) -> str:
    """尽力还原方法的签名片段（参数列表），用于生成 stub。失败则返回空。"""
    func = getattr(cls, name, None)
    if func is None:
        return ""
    try:
        sig = inspect.signature(func)
        params = []
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            params.append(pname)
        return ", ".join(params)
    except (TypeError, ValueError):
        return ""


def render_role_stub(project_id: str, role: str, role_base: Type) -> str:
    """生成 <role>.py 的 stub：继承 Project<Role>，实现必须项（带协议基类 docstring + raise NotImplementedError）。

    每个扩展点方法的 docstring 从协议基类复制过来，让接入者直接在 stub 上看到语义契约
    （定位/目标/参数），不必再去翻 impl/core/*_protocol.py。
    """
    prefix = class_prefix(project_id)
    class_name = f"{prefix}{role.title()}"
    base_module = role_base.__module__
    base_name = role_base.__name__
    required = role_required_methods(role_base)
    lines = [
        f'"""{project_id} 项目的 {role} 实现（scaffold 生成，待填充）。',
        "",
        f"继承 {base_name}（来自 {base_module}）。",
        "必须实现的扩展点已生成 stub，含协议基类的语义契约 docstring。",
        "按项目业务填充方法体后删除 NotImplementedError。",
        '"""',
        "from __future__ import annotations",
        "",
        f"from {base_module} import {base_name}",
        "",
        "",
        f"class {class_name}({base_name}):",
        f'    """{project_id} 项目 {role} 实现（scaffold 待填充）。"""',
        "",
    ]
    if not required:
        lines.append("    pass")
    for mname in required:
        sig = _method_signature(role_base, mname)
        params = f"self{', ' + sig if sig else ''}"
        lines.append(f"    def {mname}({params}):")
        # 从协议基类复制该方法的 docstring（扩展点语义契约）
        base_method = getattr(role_base, mname, None)
        doc = inspect.getdoc(base_method) if base_method is not None else None
        if doc:
            lines.append('        """')
            for doc_line in doc.splitlines():
                lines.append(f"        {doc_line}" if doc_line else "        ")
            lines.append('        """')
        lines.append(f'        raise NotImplementedError("{class_name}.{mname} 待实现")')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_adapter_stub(project_id: str, adapter_base: Type, roles: List[Tuple[str, Type]]) -> str:
    """生成 adapter.py：继承 ProjectAdapter，实现所有 _load_* 方法。"""
    base_module = adapter_base.__module__
    base_name = adapter_base.__name__
    class_name = f"Adapter"
    loads = adapter_load_methods(adapter_base)
    lines = [
        f'"""{project_id} 项目的 Adapter（scaffold 生成，待填充）。',
        "",
        f"继承 {base_name}（来自 {base_module}），只做加载和暴露，不承载业务逻辑。",
        "合规检查要求：adapter 只允许 _load_* 方法，禁止业务方法（build_*/normalize_* 等）。",
        '"""',
        "from __future__ import annotations",
        "",
        f"from {base_module} import {base_name}",
        "",
        "",
        f"class {class_name}({base_name}):",
        f'    """{project_id} 项目 Adapter（scaffold 待填充）。"""',
        "",
        "    metadata_fields = set()",
        "",
    ]
    # 角色 -> 实现类名映射，用于 _load_* 体内 import
    role_to_impl = {}
    prefix = class_prefix(project_id)
    for role, role_base in roles:
        impl_name = f"{prefix}{role.title()}"
        role_to_impl[role] = impl_name

    for load_method in loads:
        # _load_<role> -> role 名
        if not load_method.startswith("_load_"):
            continue
        role = load_method[len("_load_"):]
        # 去掉 _draft 后缀（draft 是可选，scaffold 不生成 draft 方法体）
        is_draft = role.endswith("_draft")
        bare_role = role[:-len("_draft")] if is_draft else role
        impl_name = role_to_impl.get(bare_role)
        lines.append(f"    def {load_method}(self):")
        if impl_name and not is_draft:
            lines.append(
                f'        from impl.projects.{project_id}.{bare_role} import {impl_name}'
            )
            lines.append(f"        return {impl_name}(self.spec)")
        else:
            lines.append(
                f'        raise NotImplementedError("{class_name}.{load_method} 待实现")'
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_live_schema_stub(project_id: str) -> str:
    """生成 live_schema.py 骨架（按命名规范导出）。"""
    prefix = class_prefix(project_id)
    return f'''"""{project_id} live schema（scaffold 生成，待冻结为不变量）。

按命名规范导出 REQUEST_SCHEMA / EXTRACT_OUTPUT_SCHEMA / SCENARIO_ENUM / check。
dataclass 定义在 schema/__init__.py。
"""
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.projects.{project_id}.schema import {prefix}Request, {prefix}ExtractOutput

SCENARIO_ENUM: list[str] = [
    # TODO: 从业务需求文档抽取场景枚举
]

INTENT_LABELS: list[str] = []
REQUIRED_INPUT_FIELDS = ["query"]
READY: list[str] = []

REQUEST_SCHEMA = {prefix}Request
EXTRACT_OUTPUT_SCHEMA = {prefix}ExtractOutput

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA, READY)
'''


def render_schema_init_stub(project_id: str) -> str:
    """生成 schema/__init__.py 骨架（dataclass）。"""
    prefix = class_prefix(project_id)
    return f'''"""{project_id} 项目 dataclass schema（scaffold 生成，待填充）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class {prefix}Request:
    """mock_agent 产出的 case.input 形状 / 真实 API 请求体。"""
    query: str = ""


@dataclass
class {prefix}ExtractOutput:
    """adapter.extract_output 产出的标准化输出形状。"""
    pass
'''


def scaffold(project_id: str, force: bool = False) -> Dict[str, str]:
    """生成项目骨架。返回 {相对路径: 'created'/'skipped'}。"""
    roles = discover_role_bases()
    if not roles:
        raise RuntimeError("未发现任何 Project<Role> 协议基类，请检查 impl/core/*_protocol.py")

    adapter_base = discover_adapter_base()

    project_dir = ROOT / "impl" / "projects" / project_id
    schema_dir = project_dir / "schema"
    project_dir.mkdir(parents=True, exist_ok=True)
    schema_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, str] = {}

    def write(rel: str, content: str):
        path = project_dir / rel
        if path.exists() and not force:
            results[rel] = "skipped"
            return
        path.write_text(content, encoding="utf-8")
        results[rel] = "created"

    # 各角色 stub
    for role, role_base in roles:
        write(f"{role}.py", render_role_stub(project_id, role, role_base))

    # adapter
    write("adapter.py", render_adapter_stub(project_id, adapter_base, roles))

    # live_schema + schema
    write("live_schema.py", render_live_schema_stub(project_id))
    write("schema/__init__.py", render_schema_init_stub(project_id))

    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="动态生成项目骨架")
    parser.add_argument("--project", required=True, help="项目 id（impl/projects/<id>）")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    parser.add_argument("--dry-run", action="store_true", help="只打印将生成的文件，不写盘")
    args = parser.parse_args(argv)

    if args.dry_run:
        roles = discover_role_bases()
        adapter_base = discover_adapter_base()
        print(f"[scaffold] project={args.project}")
        print(f"[scaffold] adapter base: {adapter_base.__module__}.{adapter_base.__name__}")
        print(f"[scaffold] adapter _load_* : {adapter_load_methods(adapter_base)}")
        for role, base in roles:
            print(f"[scaffold] role={role} base={base.__name__} required={role_required_methods(base)}")
        return

    results = scaffold(args.project, force=args.force)
    print(f"[scaffold] 项目 {args.project} 骨架生成结果：")
    for rel, status in results.items():
        marker = "✚" if status == "created" else "·"
        print(f"  {marker} impl/projects/{args.project}/{rel}  ({status})")
    created = sum(1 for s in results.values() if s == "created")
    skipped = sum(1 for s in results.values() if s == "skipped")
    print(f"[scaffold] 完成：{created} 新建，{skipped} 跳过（已存在）")
    if skipped and not args.force:
        print("[scaffold] 提示：跳过的文件用 --force 覆盖")
    print("[scaffold] 下一步：冻结 live_schema（不变量），填充各角色 stub")


if __name__ == "__main__":
    main()
