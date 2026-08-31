"""资料页 read model：把四层资料按项目声明聚合为 section 列表。

分层（协议见 impl/protocols/materials.md）：
- slots / free       用户生产资料（materials_store，可编辑，内容哈希封口）
- investigation      调查产物（project.yaml assets kind=investigation，只读，哈希链保护）
- system_assets      系统资产（其余 assets，只读，随代码版本）
- 结构化 store       项目在 materials.yaml stores 里声明才出现（如 llm_probe capability_map）

页面按 section.kind 渲染，项目差异全部由声明驱动，前端不硬编码板块。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import capability_store, materials_store
from .materials_materialize import cli_hint
from .path_contract import PathScope

ASSET_CONTENT_MAX_CHARS = 60_000
ASSET_FILE_LIST_LIMIT = 200


def project_overview(project_id: str) -> Dict[str, Any]:
    listing = materials_store.list_materials(project_id)
    sections: List[Dict[str, Any]] = [
        {"kind": "slots", "title": "资料槽位", "editable": True, "slots": listing["slots"]},
        {"kind": "free", "title": "自由资料", "editable": True, "items": listing["free"]},
    ]
    investigation_items, asset_items, assets_error = _asset_items(project_id)
    if investigation_items or assets_error:
        sections.append({
            "kind": "investigation",
            "title": "调查产物（对业务系统的调查）",
            "editable": False,
            "items": investigation_items,
            **({"error": assets_error} if assets_error else {}),
        })
    if asset_items:
        sections.append({
            "kind": "system_assets",
            "title": "系统资产（怎么评，随代码）",
            "editable": False,
            "items": asset_items,
        })
    for store in materials_store.load_stores(project_id):
        if store == "capability_map":
            capabilities = capability_store.load_capability_map(project_id)
            sections.append({
                "kind": "capability_map",
                "title": "capability 预设",
                "editable": True,
                "capabilities": capabilities,
            })
    return {
        "project_id": project_id,
        "sections": sections,
        "references": list(listing.get("references") or []),
    }


def _asset_selection(spec: Any, mapping: Any) -> Dict[str, Any]:
    """按 runtime 规则选出实际生效的资产路径：role draft.enabled 时用 candidate。

    与 project_loader.resolve_role_assets 的 use_candidate 选择保持一致，
    资料页展示的就是运行时真正读到的那个包。
    """
    production = _resolve_optional(spec, mapping.logical_production_path, f"verifier.assets.{mapping.asset_id}.production_path")
    candidate = _resolve_optional(spec, mapping.logical_candidate_path, f"verifier.assets.{mapping.asset_id}.candidate_path")
    use_candidate = candidate is not None and any(
        spec.role_draft(role).get("enabled") is True for role in mapping.roles
    )
    return {
        "production": production,
        "candidate": candidate,
        "active_source": "candidate" if use_candidate else "production",
        "active": candidate if use_candidate else production,
        "active_logical": (
            mapping.logical_candidate_path if use_candidate else mapping.logical_production_path
        ),
    }


def _asset_items(project_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """project.yaml assets 的只读投影；项目声明缺失/损坏不阻塞资料页，但要如实报错。"""
    try:
        mappings, spec = _load_asset_mappings(project_id)
    except Exception as exc:
        return [], [], f"资产声明加载失败: {exc}"
    investigation_items: List[Dict[str, Any]] = []
    asset_items: List[Dict[str, Any]] = []
    for mapping in mappings:
        selection = _asset_selection(spec, mapping)
        production = selection["production"]
        candidate = selection["candidate"]
        item: Dict[str, Any] = {
            "asset_id": mapping.asset_id,
            "asset_kind": mapping.kind,
            "roles": list(mapping.roles),
            "enabled": mapping.enabled,
            "production_path": mapping.logical_production_path,
            "production_exists": production is not None and production.exists(),
            "candidate_path": mapping.logical_candidate_path,
            "candidate_exists": candidate is not None and candidate.exists(),
            "active_source": selection["active_source"],
        }
        if mapping.kind == "investigation":
            item["manifest"] = _investigation_summary(selection["active"])
            investigation_items.append(item)
        else:
            asset_items.append(item)
    return investigation_items, asset_items, ""


def asset_view(project_id: str, asset_id: str) -> Dict[str, Any]:
    """单个资产的只读查看：调查包给 overview + 文件清单，文档/工具给正文截断。

    展示实际生效的那个包（role draft.enabled 时是 candidate），与 runtime 一致；
    active_source/active_path 明示当前读的是哪份。
    """
    mappings, spec = _load_asset_mappings(project_id)
    mapping = next((m for m in mappings if m.asset_id == str(asset_id or "")), None)
    if mapping is None:
        raise ValueError(f"项目 {project_id} 没有资产 {asset_id!r}")
    selection = _asset_selection(spec, mapping)
    active = selection["active"]
    view: Dict[str, Any] = {
        "project_id": project_id,
        "asset_id": mapping.asset_id,
        "asset_kind": mapping.kind,
        "roles": list(mapping.roles),
        "enabled": mapping.enabled,
        "production_path": mapping.logical_production_path,
        "candidate_path": mapping.logical_candidate_path,
        "active_source": selection["active_source"],
        "active_path": selection["active_logical"],
    }
    if active is None or not active.exists():
        view["missing"] = True
        return view
    if active.is_dir():
        manifest = _load_manifest_raw(active)
        view["manifest"] = _summarize_manifest(manifest) if manifest else None
        if manifest:
            evidence = [_evidence_ref_view(ref) for ref in manifest.get("evidence_refs") or [] if isinstance(ref, dict)]
            # 业务源码证据排最前：这是使用者最关心的"调查了业务系统什么"
            view["evidence_refs"] = sorted(evidence, key=lambda ref: 0 if ref.get("scope") == "business_source" else 1)
            view["artifact_refs"] = [_artifact_ref_view(ref) for ref in manifest.get("artifact_refs") or [] if isinstance(ref, dict)]
            if any(ref.get("scope") == "business_source" for ref in view["evidence_refs"]):
                view["materialize_hint"] = cli_hint(project_id, list(mapping.roles))
        overview_path = active / "overview.md"
        if overview_path.is_file():
            view["content"] = _truncate(overview_path.read_text(encoding="utf-8"))
        view["files"] = _file_list(active)
    else:
        view["content"] = _truncate(active.read_text(encoding="utf-8"))
    return view


def asset_file(project_id: str, asset_id: str, scope: str, relative_path: str) -> Dict[str, Any]:
    """打开资产条目背后的具体文件（只读）。

    scope 决定根：artifact_package=调查包目录；project_package=项目包；
    business_source=业务源码根（远程环境通常不可达，如实报错）。
    """
    relative = str(relative_path or "").strip()
    if not relative:
        raise ValueError("path 不能为空")
    mappings, spec = _load_asset_mappings(project_id)
    mapping = next((m for m in mappings if m.asset_id == str(asset_id or "")), None)
    if mapping is None:
        raise ValueError(f"项目 {project_id} 没有资产 {asset_id!r}")
    root = _scope_root(spec, mapping, str(scope or ""))
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"路径越界: {relative!r}")
    if not resolved.is_file():
        extra = ""
        if scope == "business_source":
            extra = " " + cli_hint(project_id, list(mapping.roles))
        raise ValueError(
            f"文件不可达: {relative}（{scope}）。业务源码类文件只在有业务代码的机器上可读。"
            + extra
        )
    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{relative} 不是文本文件，无法在页面查看")
    return {
        "project_id": project_id,
        "asset_id": asset_id,
        "scope": scope,
        "path": relative,
        "content": _truncate(content),
    }


def _scope_root(spec: Any, mapping: Any, scope: str) -> Path:
    if scope == "artifact_package":
        # 与 asset_view 一致：文件清单来自生效包，打开也必须从生效包读
        active = _asset_selection(spec, mapping)["active"]
        if active is None or not active.is_dir():
            raise ValueError(f"资产 {mapping.asset_id} 没有包目录")
        return active
    if scope == "project_package":
        from .project_loader import resolve_project_package_root

        return resolve_project_package_root(spec)
    if scope == "business_source":
        from .project_loader import resolve_project_source_root

        try:
            root = resolve_project_source_root(spec)
        except Exception:
            root = None
        if root is None or not root.is_dir():
            raise ValueError(
                "业务源码根在本机不可达（远程部署环境没有业务代码）。"
                + cli_hint(spec.project_id, list(mapping.roles))
            )
        return root
    raise ValueError(f"不支持的 scope: {scope!r}")


def _load_manifest_raw(production: Path) -> Optional[Dict[str, Any]]:
    manifest_path = production / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _evidence_ref_view(ref: Dict[str, Any]) -> Dict[str, Any]:
    """调查对象清单项：这份调查检查过业务/项目的哪个文件、哪个版本。"""
    location = ref.get("location") or {}
    metadata = ref.get("metadata") or {}
    return {
        "ref_id": ref.get("ref_id"),
        "source": ref.get("source"),
        "stage": ref.get("stage"),
        "scope": location.get("location_scope"),
        "path": location.get("location"),
        "sha256": str(location.get("sha256") or metadata.get("sha256") or "")[:12],
        "source_revision": metadata.get("source_revision"),
        "summary": ref.get("summary"),
    }


def _artifact_ref_view(ref: Dict[str, Any]) -> Dict[str, Any]:
    location = ref.get("location") or {}
    return {
        "path": location.get("location"),
        "scope": location.get("location_scope"),
        "purpose": ref.get("purpose"),
    }


def _load_asset_mappings(project_id: str):
    from .project_loader import load_project

    spec = load_project(project_id)
    return spec.asset_mappings(), spec


def _resolve_optional(spec: Any, logical: str, field_path: str) -> Optional[Path]:
    if not logical:
        return None
    try:
        return spec.resolve_path(
            logical,
            field_path=field_path,
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            must_exist=False,
        )
    except Exception:
        return None


def _investigation_summary(production: Optional[Path]) -> Optional[Dict[str, Any]]:
    if production is None or not production.is_dir():
        return None
    manifest = _load_manifest_raw(production)
    return _summarize_manifest(manifest) if manifest else None


def _summarize_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        key: manifest.get(key)
        for key in ("role", "source_revision", "schema_version", "unresolved_reason")
        if manifest.get(key) not in (None, "")
    }
    for key in ("artifact_refs", "evidence_refs", "key_indexes", "tool_requirements"):
        value = manifest.get(key)
        if isinstance(value, (list, dict)):
            summary[f"{key}_count"] = len(value)
    return summary


def _file_list(directory: Path) -> List[Dict[str, Any]]:
    files = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        files.append({
            "path": str(path.relative_to(directory)),
            "size_bytes": path.stat().st_size,
        })
        if len(files) >= ASSET_FILE_LIST_LIMIT:
            files.append({"path": f"…（仅显示前 {ASSET_FILE_LIST_LIMIT} 个文件）", "size_bytes": 0})
            break
    return files


def _truncate(text: str) -> str:
    if len(text) <= ASSET_CONTENT_MAX_CHARS:
        return text
    return text[:ASSET_CONTENT_MAX_CHARS] + f"\n\n…（已截断，共 {len(text):,} 字符）"
