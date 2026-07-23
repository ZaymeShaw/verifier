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
import difflib
import hashlib
import inspect
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple, Type

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._protocol_discovery import (  # noqa: E402
    class_prefix,
    discover_adapter_base,
    discover_role_bases,
)
from impl.core.knowledge_route import ProjectKnowledgeRoute, load_project_knowledge_route  # noqa: E402
from impl.core.project_config import parse_project_document  # noqa: E402


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
    class_name = "Adapter"
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

按命名规范导出 REQUEST_SCHEMA / EXTRACT_OUTPUT_SCHEMA / JSON schema / check。
dataclass 定义在 schema/__init__.py。
ready、scenario 和 intent 配置只来自 ProjectSpec，不在审核器模块重复声明。
"""
from __future__ import annotations

from impl.core.live_schema_check import LiveSchemaCheck
from impl.core.structured_output import dataclass_to_json_schema
from impl.projects.{project_id}.schema import {prefix}Request, {prefix}ExtractOutput

REQUIRED_INPUT_FIELDS = ["query"]

REQUEST_SCHEMA = {prefix}Request
EXTRACT_OUTPUT_SCHEMA = {prefix}ExtractOutput
REQUEST_JSON_SCHEMA = dataclass_to_json_schema(REQUEST_SCHEMA)
EXTRACT_OUTPUT_JSON_SCHEMA = dataclass_to_json_schema(EXTRACT_OUTPUT_SCHEMA)

check = LiveSchemaCheck(REQUEST_SCHEMA, EXTRACT_OUTPUT_SCHEMA)
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


def render_project_config(route: ProjectKnowledgeRoute) -> str:
    """Render a reviewable canonical ProjectConfig from the sole knowledge route."""
    uploaded = "output" in route.ready
    document = {
        "schema_version": 1,
        "project": {
            "id": route.project_id,
            "name": route.name,
            "description": route.description,
            "capabilities": [route.interaction],
        },
        "runtime": {
            "mode": "uploaded_output_evaluation" if uploaded else "existing_service_optional",
            "application": {
                "interface": {
                    "shape": "project input/output shape to be completed during implementation",
                    "source": "adapter.py and the approved project application documents",
                },
                "start_run": (
                    "no service; normalize uploaded output"
                    if uploaded
                    else "reuse the configured existing service after its health contract passes"
                ),
                "boundary": "complete the evaluated application responsibility boundary before acceptance",
            },
            "interaction": {"mode": route.interaction},
            "ready": list(route.ready),
            "adapter": {
                "request_construction": {
                    "builder": "Adapter.build_request must be completed during project implementation",
                    "required_inputs": ["query"],
                },
                "output_extraction": {
                    "extractor": "Adapter.extract_output must be completed during project implementation",
                    "normalized_output": "project-specific normalized output contract",
                },
                "reference_handling": {
                    "source_priority": ["input_reference", "judge_generated", "missing"],
                    "alignment": "compare reference and output through one normalized business shape",
                },
            },
            "batch_persistence": {
                "case_shape": "id, selected, input, output, reference, metadata, scenario, source, status, error",
                "transient_results": "do not persist trace, judge, attribute, or frontend_view as durable case-pool data",
            },
        },
        "verifier": {
            "attribution": {
                "enabled": False,
                "trace": {
                    "document": "attribution.md",
                    "trace_nodes": ["request_normalization", "output_extraction", "judge", "attribution"],
                },
            },
            "judge": {
                "boundary": {
                    "document": "judge_boundary.md",
                    "gate": "declare the evaluable boundary before expected/actual comparison",
                }
            },
            "presentation": {
                "frontend_view": {
                    "live": "render normalized protocol objects",
                    "summary": "render the durable case shape with compact runtime summaries",
                }
            },
            "check_rules": {
                "evidence": {
                    "documents": [document.document_id for document in route.documents.values()],
                    "tests": [],
                }
            },
        },
        "metadata": {
            "initialized_from": "route://project.yaml",
            "source_revision": _sha256_bytes((route.root / "project.yaml").read_bytes()),
        },
    }
    if route.source_repository:
        document["project"]["resources"] = {"source": {"repository": ""}}
        document["environment"] = {
            "variables": {
                variable.name: {
                    "bind": "project.resources.source.repository",
                    "type": variable.type,
                    "required": variable.required,
                    "secret": variable.secret,
                    "description": variable.description,
                }
                for variable in route.environment.variables.values()
            }
        }
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)


def project_config_proposal_candidate(
    route: ProjectKnowledgeRoute,
    formal_config: Path,
) -> str:
    """Start updates from the human-owned config; only first setup is generated."""
    if formal_config.is_file():
        return formal_config.read_text(encoding="utf-8")
    return render_project_config(route)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _proposal_directory(path: Path, *, root: Path = ROOT) -> Path:
    proposal_dir = Path(path)
    if not proposal_dir.is_absolute():
        proposal_dir = root / proposal_dir
    proposal_dir = proposal_dir.resolve(strict=False)
    proposals_root = (root / "report" / "config-proposals").resolve(strict=False)
    if not proposal_dir.is_relative_to(proposals_root):
        raise ValueError(f"proposal must stay under {proposals_root}")
    relative = proposal_dir.relative_to(proposals_root)
    if len(relative.parts) != 2:
        raise ValueError("proposal path must be <proposal-root>/<project>/<proposal-id>")
    return proposal_dir


def _validate_proposed_project_config(
    content: str,
    *,
    project_id: str,
    project_root: Path,
) -> tuple[str, list[str]]:
    try:
        document = yaml.safe_load(content)
        if not isinstance(document, dict):
            raise ValueError("candidate project.yaml must be a YAML mapping")
        parse_project_document(
            document,
            project_id=project_id,
            project_root=project_root,
        )
    except Exception as exc:
        return "failed", [f"{type(exc).__name__}: {exc}"]
    return "passed", []


def seal_project_config_proposal(
    proposal: Path,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    proposal_dir = _proposal_directory(proposal, root=root)
    project_id = proposal_dir.parent.name
    candidate_path = proposal_dir / "project.yaml"
    if not candidate_path.is_file():
        raise FileNotFoundError(f"proposal candidate not found: {candidate_path}")
    candidate = candidate_path.read_text(encoding="utf-8")
    candidate_hash = _sha256_bytes(candidate.encode("utf-8"))
    route_path = root / "projects" / project_id / "project.yaml"
    if not route_path.is_file():
        raise FileNotFoundError(f"knowledge route not found: {route_path}")
    route_hash = _sha256_bytes(route_path.read_bytes())
    target = root / "impl" / "projects" / project_id / "project.yaml"
    validation_status, validation_errors = _validate_proposed_project_config(
        candidate,
        project_id=project_id,
        project_root=target.parent,
    )
    manifest = {
        "schema_version": 1,
        "proposal_id": proposal_dir.name,
        "project_id": project_id,
        "candidate": {
            "file": "project.yaml",
            "sha256": candidate_hash,
        },
        "source": {
            "knowledge_route": "route://project.yaml",
            "sha256": route_hash,
        },
        "target": {
            "file": f"impl/projects/{project_id}/project.yaml",
            "current_sha256": _sha256_bytes(target.read_bytes()) if target.is_file() else None,
        },
        "validation": {
            "status": validation_status,
            "errors": validation_errors,
        },
    }
    _atomic_write_text(
        proposal_dir / "proposal.yaml",
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
    )
    return manifest


def create_project_config_proposal(
    route: ProjectKnowledgeRoute,
    candidate: str,
    *,
    root: Path = ROOT,
) -> tuple[Path, str]:
    candidate_hash = _sha256_bytes(candidate.encode("utf-8"))
    proposal_dir = root / "report" / "config-proposals" / route.project_id / candidate_hash[:16]
    candidate_path = proposal_dir / "project.yaml"
    status = "proposal_created"
    if candidate_path.is_file() and candidate_path.read_text(encoding="utf-8") != candidate:
        status = "proposal_review_required"
    else:
        _atomic_write_text(candidate_path, candidate)
    seal_project_config_proposal(proposal_dir, root=root)
    return proposal_dir, status


def accept_project_config_proposal(
    proposal: Path,
    *,
    expected_hash: str,
    root: Path = ROOT,
    update: bool = False,
    expected_current_hash: str | None = None,
) -> Path:
    proposal_dir = _proposal_directory(proposal, root=root)
    manifest_path = proposal_dir / "proposal.yaml"
    candidate_path = proposal_dir / "project.yaml"
    if not manifest_path.is_file() or not candidate_path.is_file():
        raise FileNotFoundError(f"proposal is incomplete: {proposal_dir}")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("proposal manifest must be a YAML mapping")
    project_id = str(manifest.get("project_id") or "")
    if project_id != proposal_dir.parent.name:
        raise ValueError("proposal project identity does not match its directory")
    candidate = candidate_path.read_text(encoding="utf-8")
    actual_hash = _sha256_bytes(candidate.encode("utf-8"))
    sealed_hash = str(((manifest.get("candidate") or {}).get("sha256") or ""))
    if actual_hash != sealed_hash or actual_hash != expected_hash:
        raise ValueError("proposal candidate hash changed after review")
    if ((manifest.get("validation") or {}).get("status")) != "passed":
        raise ValueError("proposal validation has not passed; edit and seal it before accept")
    route_path = root / "projects" / project_id / "project.yaml"
    route_hash = _sha256_bytes(route_path.read_bytes()) if route_path.is_file() else ""
    if route_hash != str(((manifest.get("source") or {}).get("sha256") or "")):
        raise ValueError("knowledge route changed after proposal sealing")

    target = root / "impl" / "projects" / project_id / "project.yaml"
    if target.exists() and not update:
        raise FileExistsError(f"formal project config already exists: {target}")
    if update:
        if not target.is_file():
            raise FileNotFoundError(f"formal project config does not exist for update: {target}")
        actual_current_hash = _sha256_bytes(target.read_bytes())
        sealed_current_hash = ((manifest.get("target") or {}).get("current_sha256"))
        if not expected_current_hash or actual_current_hash != expected_current_hash:
            raise ValueError("current formal project config hash does not match explicit update approval")
        if actual_current_hash != sealed_current_hash:
            raise ValueError("formal project config changed after proposal sealing")

    document = yaml.safe_load(candidate)
    metadata = document.setdefault("metadata", {})
    metadata["accepted_proposal_sha256"] = actual_hash
    final_content = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    validation_status, validation_errors = _validate_proposed_project_config(
        final_content,
        project_id=project_id,
        project_root=target.parent,
    )
    if validation_status != "passed":
        raise ValueError(f"accepted project config failed validation: {validation_errors[0]}")
    _atomic_write_text(target, final_content)
    return target


def _write_scaffold_file(path: Path, content: str, *, force: bool, protected: bool = False) -> str:
    """Write generated code, while never overwriting a human-owned formal config."""
    if not path.exists():
        path.write_text(content, encoding="utf-8")
        return "created"
    current = path.read_text(encoding="utf-8")
    if current == content:
        return "unchanged"
    if protected:
        return "review_required"
    if not force:
        return "skipped"
    path.write_text(content, encoding="utf-8")
    return "created"


def _project_config_diff(path: Path, proposed: str) -> str:
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    return "".join(difflib.unified_diff(
        current.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile=str(path),
        tofile=f"{path} (proposed)",
    ))


def scaffold(project_id: str, force: bool = False) -> Dict[str, str]:
    """生成项目骨架。返回 {相对路径: 'created'/'skipped'}。"""
    route = load_project_knowledge_route(project_id)
    roles = discover_role_bases()
    if not roles:
        raise RuntimeError("未发现任何 Project<Role> 协议基类，请检查 impl/core/*_protocol.py")

    adapter_base = discover_adapter_base()

    project_dir = ROOT / "impl" / "projects" / project_id
    schema_dir = project_dir / "schema"
    project_dir.mkdir(parents=True, exist_ok=True)
    schema_dir.mkdir(parents=True, exist_ok=True)

    results: Dict[str, str] = {}

    def write(rel: str, content: str, *, protected: bool = False):
        path = project_dir / rel
        results[rel] = _write_scaffold_file(path, content, force=force, protected=protected)

    # 各角色 stub
    for role, role_base in roles:
        write(f"{role}.py", render_role_stub(project_id, role, role_base))

    # adapter
    write("adapter.py", render_adapter_stub(project_id, adapter_base, roles))

    # live_schema + schema
    write("live_schema.py", render_live_schema_stub(project_id))
    write("schema/__init__.py", render_schema_init_stub(project_id))
    # AI 生成的项目配置只能进入非运行 proposal；显式 accept 后才创建正式 project.yaml。
    proposal_dir, proposal_status = create_project_config_proposal(
        route,
        project_config_proposal_candidate(route, project_dir / "project.yaml"),
    )
    results[proposal_dir.relative_to(ROOT).as_posix()] = proposal_status

    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="动态生成项目骨架")
    parser.add_argument("--project", help="项目 id（impl/projects/<id>）")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的代码骨架；永不覆盖人工 project.yaml")
    parser.add_argument("--dry-run", action="store_true", help="只打印将生成的文件，不写盘")
    parser.add_argument("--seal-proposal", type=Path, help="重新校验并封存已编辑的 project config proposal")
    parser.add_argument("--accept-proposal", type=Path, help="显式接受已封存 proposal")
    parser.add_argument("--expected-hash", help="人工审核确认的 proposal candidate sha256")
    parser.add_argument("--update", action="store_true", help="接受为已有正式配置的更新 proposal")
    parser.add_argument("--expected-current-hash", help="更新时人工确认的当前正式配置 sha256")
    args = parser.parse_args(argv)

    if args.seal_proposal is not None:
        manifest = seal_project_config_proposal(args.seal_proposal)
        print(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), end="")
        return

    if args.accept_proposal is not None:
        if not args.expected_hash:
            parser.error("--accept-proposal requires --expected-hash")
        target = accept_project_config_proposal(
            args.accept_proposal,
            expected_hash=args.expected_hash,
            update=args.update,
            expected_current_hash=args.expected_current_hash,
        )
        print(f"[scaffold] accepted formal config: {target.relative_to(ROOT)}")
        return

    if not args.project:
        parser.error("--project is required unless sealing or accepting a proposal")

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
        display_path = rel if rel.startswith("report/config-proposals/") else f"impl/projects/{args.project}/{rel}"
        print(f"  {marker} {display_path}  ({status})")
        if rel.startswith("report/config-proposals/"):
            manifest = yaml.safe_load((ROOT / rel / "proposal.yaml").read_text(encoding="utf-8"))
            target = ROOT / "impl" / "projects" / args.project / "project.yaml"
            print(_project_config_diff(target, (ROOT / rel / "project.yaml").read_text(encoding="utf-8")))
            print(f"  review hash: {manifest['candidate']['sha256']}")
    created = sum(1 for s in results.values() if s == "created")
    skipped = sum(1 for s in results.values() if s in {"skipped", "unchanged", "review_required", "proposal_review_required"})
    print(f"[scaffold] 完成：{created} 新建，{skipped} 未覆盖")
    if skipped and not args.force:
        print("[scaffold] 提示：代码骨架可用 --force 覆盖；project.yaml 只能通过 proposal 显式 accept")
    print("[scaffold] 下一步：冻结 live_schema（不变量），填充各角色 stub")


if __name__ == "__main__":
    main()
