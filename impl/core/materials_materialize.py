"""资料系统 V1.5：调查产物物化导出。

在有业务源码的机器上读取调查包 evidence_refs，校验源文件哈希后把正文内联成
自包含资料（provenance=investigation）。远程消费只验内容哈希，不再摸业务源码。

物化结果默认是自由资料（reference），不写入绑定 judge 的槽位——业务 yaml 体积
会撑爆 30k binding 预算。远程阅读靠资料页打开这些自由资料，不靠现场读源码。

协议：impl/protocols/materials.md；设计：docs/materials-system-implementation.md §2.3 / V1.5。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import materials_store
from .capability_store import NAME_PATTERN
from .path_contract import PathScope
from .project_loader import load_project, resolve_project_source_root, resolve_role_assets
from .schema.investigation import InvestigationManifest, load_investigation_manifest
from .source_staleness import file_sha256


class MaterializeError(ValueError):
    """物化失败：源漂移、源码不可达、或单份资料超上限。"""


def cli_hint(project_id: str, roles: Optional[List[str]] = None) -> str:
    """资料页 / 打开失败时展示的本地物化命令。"""
    role = "judge"
    for item in roles or []:
        if item in ("judge", "attribute", "mock"):
            role = item
            break
    return (
        f"业务源码正文不在调查包内。请在有业务代码的机器运行："
        f"`bash run.sh cli materialize --project {project_id} --role {role} --apply`。"
        "结果写入自由资料（不注入 judge）；同步到评测机用 scripts/sync_materials.sh"
        "（或 materialize --push），只拷贝对应 materials 目录，不要全量覆盖 impl/data。"
    )


def _use_candidate_for_source(spec: Any, role: str, source: str) -> bool:
    """物化用哪个调查包：auto 跟随 runtime（role draft.enabled），或显式强制。"""
    if source == "auto":
        return spec.role_draft(role).get("enabled") is True
    if source == "candidate":
        return True
    if source == "production":
        return False
    raise MaterializeError(f"不支持的 source: {source!r}（auto|candidate|production）")


def materialize_project(
    project_id: str,
    role: str,
    *,
    apply: bool = False,
    source: str = "auto",
    slot_id: str = "",
) -> Dict[str, Any]:
    """从项目角色调查包物化 business_source 证据。

    调查包选择与 runtime 一致：role draft.enabled 时用 candidate，否则 production；
    source=candidate/production 可显式强制。
    """
    spec = load_project(project_id)
    use_candidate = _use_candidate_for_source(spec, role, source)
    try:
        packages = [
            item
            for item in resolve_role_assets(spec, role, use_candidate=use_candidate)
            if item["mapping"].kind == "investigation"
        ]
    except FileNotFoundError as exc:
        raise MaterializeError(str(exc)) from exc
    if len(packages) != 1:
        raise MaterializeError(
            f"项目 {project_id} 角色 {role} 期望恰好一份 investigation 资产，实际 {len(packages)}。"
            "请检查 project.yaml assets。"
        )
    selected = packages[0]
    package_source = str(selected.get("source") or "production")
    package = Path(selected["path"])
    if package_source == "candidate":
        # 增量门禁出口条件（spec/alg/investigate.md）：候选包必须先过
        # baseline + increment 闭合，才允许物化导出。
        from .investigation_lifecycle import (
            InvestigationLifecycleError,
            require_increment_closed,
        )

        try:
            require_increment_closed(spec, role)
        except InvestigationLifecycleError as exc:
            raise MaterializeError(str(exc)) from exc
    if not package.is_dir():
        hint = (
            "（可试 --candidate 使用 draft 调查包）"
            if package_source == "production"
            else "（可试 --production 使用生产调查包）"
        )
        raise MaterializeError(f"{role} 调查包目录不存在: {package}{hint}")
    manifest_path = package / "manifest.json"
    if not manifest_path.is_file():
        raise MaterializeError(f"调查包缺少 manifest.json: {manifest_path}")
    manifest = load_investigation_manifest(manifest_path)
    source_root = None
    if spec.has_business_source:
        try:
            source_root = resolve_project_source_root(spec)
        except Exception:
            source_root = None
    return materialize_evidence(
        project_id=project_id,
        role=role,
        manifest=manifest,
        source_root=source_root,
        apply=apply,
        slot_id=slot_id.strip(),
        package_source=package_source,
    )


def materialize_evidence(
    *,
    project_id: str,
    role: str,
    manifest: InvestigationManifest,
    source_root: Optional[Path],
    apply: bool = False,
    slot_id: str = "",
    package_source: str = "production",
) -> Dict[str, Any]:
    """核心物化：校验 business_source 哈希并内联正文。

    candidate 来源的资料 id 带 `-draft-` 中缀（{role}-draft-{ref_id}），
    与 production 物化结果并存，互不覆盖。
    """
    slot_id = str(slot_id or "").strip()
    if package_source not in ("production", "candidate"):
        raise MaterializeError(f"不支持的 package_source: {package_source!r}")
    id_prefix = f"{role}-draft" if package_source == "candidate" else role
    business_refs = [
        evidence
        for evidence in manifest.evidence_refs
        if evidence.location_ref is not None
        and evidence.location_ref.location_scope == PathScope.BUSINESS_SOURCE
    ]
    if not business_refs:
        raise MaterializeError(
            f"调查包 {project_id}/{role} 没有 business_source 证据，无需物化。"
        )
    if source_root is None or not Path(source_root).is_dir():
        raise MaterializeError(
            "业务源码根不可达。请在有业务代码的环境运行 "
            f"`bash run.sh cli materialize --project {project_id} --role {role} --apply`。"
        )

    snapshots: List[Dict[str, Any]] = []
    for evidence in business_refs:
        snapshots.append(
            _snapshot_business_ref(
                evidence,
                source_root=Path(source_root),
                source_revision=manifest.source_revision,
                role=role,
                id_prefix=id_prefix,
                package_source=package_source,
            )
        )

    index_id = _material_id(f"{id_prefix}-investigation-snapshot")
    if slot_id:
        if not NAME_PATTERN.fullmatch(slot_id):
            raise MaterializeError(f"非法槽位 id: {slot_id!r}")
        reserved = {index_id} | {item["id"] for item in snapshots}
        if slot_id in reserved:
            raise MaterializeError(
                f"--slot {slot_id} 与逐份资料 id 冲突，请换一个 id。"
            )
        for slot in materials_store.load_slots(project_id):
            if slot["slot_id"] == slot_id and slot["roles"]:
                raise MaterializeError(
                    f"槽位 {slot_id} 绑定了角色 {slot['roles']}，不能写入大体量调查快照"
                    "（会撑爆 binding 预算）。去掉 --slot 让快照进入自由资料，"
                    "或声明一个 roles 为空的槽位。"
                )
        pack = "\n\n-----\n\n".join(item["content"] for item in snapshots)
        if len(pack) > materials_store.MAX_CONTENT_CHARS:
            raise MaterializeError(
                f"槽位 {slot_id} 的拼接正文 {len(pack)} 字符，超过 "
                f"{materials_store.MAX_CONTENT_CHARS} 上限。去掉 --slot，改用逐份自由资料。"
            )
    else:
        pack = ""

    index_body = _index_markdown(project_id, role, manifest, snapshots)
    written: List[Dict[str, Any]] = []
    if apply:
        for item in snapshots:
            written.append(
                materials_store.save_material(
                    project_id,
                    item["id"],
                    content=item["content"],
                    title=item["title"],
                    description=item["description"],
                    provenance=item["provenance"],
                )
            )
        title_suffix = "（draft 调查包）" if package_source == "candidate" else ""
        written.append(
            materials_store.save_material(
                project_id,
                index_id,
                content=index_body,
                title=f"{role} 调查物化目录{title_suffix}",
                description=f"source_revision {manifest.source_revision}",
                provenance=_investigation_provenance(
                    role=role,
                    source_revision=manifest.source_revision,
                    package_source=package_source,
                    extra={"kind": "index"},
                ),
            )
        )
        if slot_id:
            written.append(
                materials_store.save_material(
                    project_id,
                    slot_id,
                    content=pack,
                    title=f"{role} 调查物化（业务源码快照）{title_suffix}",
                    description=f"source_revision {manifest.source_revision}；{len(snapshots)} 份证据内联",
                    provenance=_investigation_provenance(
                        role=role,
                        source_revision=manifest.source_revision,
                        package_source=package_source,
                        extra={"kind": "slot_pack", "evidence_count": len(snapshots)},
                    ),
                )
            )

    return {
        "project_id": project_id,
        "role": role,
        "package_source": package_source,
        "source_revision": manifest.source_revision,
        "applied": apply,
        "slot_id": slot_id or None,
        "index_id": index_id,
        "hint": (
            None
            if apply
            else "未加 --apply，只校验不写盘。确认后加 --apply 写入 impl/data/<project>/materials/。"
        ),
        "snapshots": [
            {
                "id": item["id"],
                "ref_id": item["ref_id"],
                "path": item["path"],
                "source_sha256": item["source_sha256"],
                "size_chars": len(item["content"]),
                "title": item["title"],
            }
            for item in snapshots
        ],
        "written": [
            {"id": item.get("id"), "sha256": item.get("sha256"), "size_chars": item.get("size_chars")}
            for item in written
        ],
    }


def _snapshot_business_ref(
    evidence: Any,
    *,
    source_root: Path,
    source_revision: str,
    role: str,
    id_prefix: str,
    package_source: str,
) -> Dict[str, Any]:
    location_ref = evidence.location_ref
    relative = str(location_ref.location or "").strip()
    root = source_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise MaterializeError(f"证据 {evidence.ref_id} 路径越界: {relative}")
    if not path.is_file():
        raise MaterializeError(
            f"证据 {evidence.ref_id} 对应的业务文件不存在: {relative}。请确认业务仓库路径。"
        )
    actual = file_sha256(path)
    declared = str(location_ref.sha256 or (evidence.metadata or {}).get("sha256") or "")
    if not declared:
        raise MaterializeError(
            f"证据 {evidence.ref_id} 未登记源哈希，无法校验。请先重新调查再物化。"
        )
    if actual != declared:
        raise MaterializeError(
            f"证据 {evidence.ref_id} 源文件哈希与调查登记不符（declared={declared[:12]} actual={actual[:12]}）。"
            "请先重新调查再物化。"
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise MaterializeError(
            f"证据 {evidence.ref_id} 不是 UTF-8 文本，无法物化: {relative}"
        ) from exc
    material_id = _material_id(f"{id_prefix}-{evidence.ref_id}")
    title = Path(relative).name
    revision = str((evidence.metadata or {}).get("source_revision") or source_revision)
    body = _snapshot_markdown(
        title=title,
        ref_id=str(evidence.ref_id),
        relative=relative,
        source_revision=revision,
        source_sha256=actual,
        summary=str(evidence.summary or ""),
        raw=raw,
    )
    if len(body) > materials_store.MAX_CONTENT_CHARS:
        raise MaterializeError(
            f"证据 {evidence.ref_id} 物化后 {len(body)} 字符，超过 "
            f"{materials_store.MAX_CONTENT_CHARS} 上限，请拆分调查对象或裁剪源文件。"
        )
    return {
        "id": material_id,
        "ref_id": str(evidence.ref_id),
        "path": relative,
        "source_sha256": actual,
        "title": title,
        "description": str(evidence.summary or relative),
        "content": body,
        "provenance": _investigation_provenance(
            role=role,
            source_revision=revision,
            package_source=package_source,
            extra={
                "evidence_ref_id": str(evidence.ref_id),
                "source_ref": {
                    "location_scope": "business_source",
                    "location": relative,
                    "sha256": actual,
                },
            },
        ),
    }


def _snapshot_markdown(
    *,
    title: str,
    ref_id: str,
    relative: str,
    source_revision: str,
    source_sha256: str,
    summary: str,
    raw: str,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- evidence_ref: `{ref_id}`",
        f"- location: `business://{relative}`",
        f"- source_revision: `{source_revision}`",
        f"- source_sha256: `{source_sha256}`",
    ]
    if summary:
        lines.extend(["", summary.strip()])
    lines.extend(["", "---", "", raw.rstrip(), ""])
    return "\n".join(lines)


def _index_markdown(
    project_id: str,
    role: str,
    manifest: InvestigationManifest,
    snapshots: List[Dict[str, Any]],
) -> str:
    lines = [
        f"# {project_id} / {role} 调查物化目录",
        "",
        f"source_revision: `{manifest.source_revision}`",
        "",
        "以下资料由 `materialize` 从 business_source 证据内联，远程可直接阅读正文。",
        "",
    ]
    for item in snapshots:
        lines.append(
            f"- `{item['id']}` ← `{item['ref_id']}` (`business://{item['path']}`, "
            f"sha256 `{item['source_sha256'][:12]}…`)"
        )
        lines.append(f"  - 引用: `material://{project_id}/{item['id']}`")
    lines.append("")
    return "\n".join(lines)


def _investigation_provenance(
    *,
    role: str,
    source_revision: str,
    package_source: str = "production",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source": "investigation",
        "execution": "local",
        "role": role,
        "source_revision": source_revision,
        "package_source": package_source,
    }
    if extra:
        payload.update(extra)
    return payload


def _material_id(raw: str) -> str:
    text = "".join(
        ch if ch.isalnum() or ch in "-_" else "-"
        for ch in str(raw or "").strip().lower()
    )
    while "--" in text:
        text = text.replace("--", "-")
    text = text.strip("-_")
    if not NAME_PATTERN.fullmatch(text):
        raise MaterializeError(f"无法从 {raw!r} 生成合法资料 id")
    return text
