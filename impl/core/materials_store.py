"""资料系统 V1：资料实体存储 + 槽位 + binding/reference 消费。

协议见 docs/materials-system-implementation.md。要点：
- 槽位由项目声明（impl/projects/<project>/materials.yaml），是项目契约，随代码版本管理；
- 资料内容存 impl/data/<project>/materials/<id>/（manifest.json + content.md），
  manifest 走 materials_store artifact family 校验，内容哈希封口；
- required 槽位未填 → require_materials 拒跑；binding 注入有预算硬校验；
- `material://<project>/<id>` 由 resolve_material_uri 展开（reference 消费）。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .capability_store import NAME_PATTERN, PROJECT_PATTERN
from .portable_artifact import write_active_artifact

ROOT = Path(__file__).resolve().parents[1]

CONTENT_FILENAME = "content.md"
MAX_CONTENT_CHARS = 1_000_000
BINDING_BUDGET_CHARS = 30_000
REFERENCE_EXPAND_BUDGET_CHARS = 50_000
ALLOWED_FILL = ("upload", "investigate_http", "source_bind")
ALLOWED_PROVENANCE = ("user_upload", "investigation", "derived")
ALLOWED_ROLES = ("judge", "mock", "attribute")
ALLOWED_STORES = ("capability_map",)
# 唯一合法记号：{material://<project>/<id>}。定界符让解析器和周围文本无关。
_MATERIAL_REF_TOKEN = re.compile(r"\{material://[A-Za-z][A-Za-z0-9_-]*/[a-z][a-z0-9_-]*\}")
_MATERIAL_URI_LOOSE = re.compile(r"material://[^\s，。；）\]\}\>\"'`]+")


def _require_name(value: str, kind: str) -> str:
    if not NAME_PATTERN.fullmatch(str(value or "")):
        raise ValueError(f"非法{kind}: {value!r}（小写字母开头，可含数字/_/-）")
    return str(value)


def _require_project(value: str) -> str:
    if not PROJECT_PATTERN.fullmatch(str(value or "")):
        raise ValueError(f"非法 project id: {value!r}")
    return str(value)


def materials_root(project_id: str) -> Path:
    return ROOT / "data" / _require_project(project_id) / "materials"


def _material_dir(project_id: str, material_id: str) -> Path:
    return materials_root(project_id) / _require_name(material_id, "资料 id")


def _slots_path(project_id: str) -> Path:
    return ROOT / "projects" / _require_project(project_id) / "materials.yaml"


def _load_declaration(project_id: str) -> Dict[str, Any]:
    path = _slots_path(project_id)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 YAML 对象")
    return data


def load_stores(project_id: str) -> List[str]:
    """项目声明的结构化资料 store（如 llm_probe 的 capability_map）；未声明不展示。"""
    stores = _load_declaration(project_id).get("stores") or []
    if not isinstance(stores, list):
        raise ValueError(f"{_slots_path(project_id)} stores 必须是列表")
    invalid = [str(item) for item in stores if str(item) not in ALLOWED_STORES]
    if invalid:
        raise ValueError(f"{_slots_path(project_id)} stores 不支持: {invalid}")
    return [str(item) for item in stores]


def load_slots(project_id: str) -> List[Dict[str, Any]]:
    """读项目槽位声明；无声明文件或未声明槽位返回空列表。"""
    path = _slots_path(project_id)
    raw_slots = _load_declaration(project_id).get("slots") or []
    if not isinstance(raw_slots, list):
        raise ValueError(f"{path} slots 必须是列表")
    slots = []
    seen = set()
    for index, raw in enumerate(raw_slots):
        if not isinstance(raw, dict):
            raise ValueError(f"{path} slots[{index}] 必须是对象")
        slot_id = _require_name(str(raw.get("slot_id") or ""), "槽位 id")
        if slot_id in seen:
            raise ValueError(f"{path} 槽位 id 重复: {slot_id}")
        seen.add(slot_id)
        fill = [str(item) for item in (raw.get("fill") or ["upload"])]
        invalid_fill = [item for item in fill if item not in ALLOWED_FILL]
        if invalid_fill:
            raise ValueError(f"{path} slots[{slot_id}].fill 不支持: {invalid_fill}")
        roles = [str(item) for item in (raw.get("roles") or [])]
        invalid_roles = [item for item in roles if item not in ALLOWED_ROLES]
        if invalid_roles:
            raise ValueError(f"{path} slots[{slot_id}].roles 不支持: {invalid_roles}")
        slots.append({
            "slot_id": slot_id,
            "title": str(raw.get("title") or slot_id),
            "description": str(raw.get("description") or ""),
            "required": bool(raw.get("required") or False),
            "roles": roles,
            "fill": fill,
            "source": str(raw.get("source") or ""),
        })
    return slots


def load_manifest(project_id: str, material_id: str) -> Optional[Dict[str, Any]]:
    path = _material_dir(project_id, material_id) / "manifest.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 JSON 对象")
    return data


def read_content(project_id: str, material_id: str) -> str:
    manifest = load_manifest(project_id, material_id)
    if manifest is None:
        raise ValueError(f"资料 {project_id}/{material_id} 不存在")
    path = _material_dir(project_id, material_id) / CONTENT_FILENAME
    content = path.read_text(encoding="utf-8")
    actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if actual != manifest.get("sha256"):
        raise ValueError(
            f"资料 {project_id}/{material_id} 内容哈希与 manifest 不符（内容被绕过资料 API 修改）"
        )
    return content


def get_material(project_id: str, material_id: str) -> Dict[str, Any]:
    """资料页编辑器用：manifest 摘要 + 正文。"""
    manifest = load_manifest(project_id, material_id)
    if manifest is None:
        raise ValueError(f"资料 {project_id}/{material_id} 不存在")
    return {**_manifest_summary(manifest), "content": read_content(project_id, material_id)}


def validate_manifest_payload(path: Path, payload: Any) -> None:
    """artifact family 的 payload 校验：形状 + 路径身份。"""
    if not isinstance(payload, dict):
        raise TypeError("material manifest must be a JSON object")
    material_id = Path(path).parent.name
    project_id = Path(path).parents[2].name
    if payload.get("id") != material_id or payload.get("project_id") != project_id:
        raise ValueError(f"material manifest identity mismatch: {path}")
    for field in ("sha256", "title"):
        if not str(payload.get(field) or "").strip():
            raise ValueError(f"material manifest missing {field}: {path}")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("source") not in ALLOWED_PROVENANCE:
        raise ValueError(f"material manifest provenance.source 必须是 {ALLOWED_PROVENANCE}")
    size = payload.get("size_chars")
    if not isinstance(size, int) or size <= 0 or size > MAX_CONTENT_CHARS:
        raise ValueError(f"material manifest size_chars 必须在 1..{MAX_CONTENT_CHARS}")


def verify_content_seal(manifest_path: Path, payload: Dict[str, Any]) -> None:
    """artifact family 的文件校验：内容哈希封口。"""
    content_path = Path(manifest_path).parent / CONTENT_FILENAME
    if not content_path.is_file():
        raise ValueError(f"material content file missing: {content_path}")
    actual = hashlib.sha256(content_path.read_bytes()).hexdigest()
    if actual != payload.get("sha256"):
        raise ValueError(
            f"material content hash mismatch: expected={payload.get('sha256')}, actual={actual}"
        )


def save_material(
    project_id: str,
    material_id: str,
    *,
    content: str,
    title: str = "",
    description: str = "",
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _require_name(material_id, "资料 id")
    content = str(content or "")
    if not content.strip():
        raise ValueError("资料内容不能为空")
    if len(content) > MAX_CONTENT_CHARS:
        raise ValueError(f"资料内容超过 {MAX_CONTENT_CHARS} 字符上限，请拆分或裁剪")
    existing = load_manifest(project_id, material_id)
    content_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    prov = _next_provenance(existing, content_sha, provenance)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    directory = _material_dir(project_id, material_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CONTENT_FILENAME).write_text(content, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "id": material_id,
        "project_id": project_id,
        "title": str(title or (existing or {}).get("title") or material_id),
        "description": str(description or (existing or {}).get("description") or ""),
        "media_type": "text/markdown",
        "sha256": content_sha,
        "size_chars": len(content),
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
        "provenance": prov,
        "consumption": {"reference": True},
    }
    write_active_artifact(
        "materials_store",
        directory / "manifest.json",
        manifest,
        repository_root=ROOT.parent,
    )
    return manifest


def _next_provenance(
    existing: Optional[Dict[str, Any]],
    content_sha: str,
    provenance: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """信任分档纪律：手改调查/派生资料，provenance 降级 derived 并标记内容已非原样。"""
    if provenance is not None:
        prov = dict(provenance)
        if prov.get("source") not in ALLOWED_PROVENANCE:
            raise ValueError(f"provenance.source 必须是 {ALLOWED_PROVENANCE}")
        return prov
    prev = dict((existing or {}).get("provenance") or {})
    if existing and existing.get("sha256") == content_sha:
        return prev or {"source": "user_upload"}
    if prev.get("source") in ("investigation", "derived"):
        downgraded = {"source": "derived", "edited": True}
        if prev.get("detail"):
            downgraded["detail"] = prev["detail"]
        if prev.get("source") == "investigation":
            downgraded["derived_from"] = "investigation"
        elif prev.get("derived_from"):
            downgraded["derived_from"] = prev["derived_from"]
        return downgraded
    return {"source": "user_upload"}


def delete_material(project_id: str, material_id: str) -> Dict[str, Any]:
    directory = _material_dir(project_id, material_id)
    existed = directory.is_dir()
    if existed:
        shutil.rmtree(directory)
    return {"project_id": project_id, "id": material_id, "deleted": existed}


def _manifest_summary(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: manifest.get(key)
        for key in (
            "id", "title", "description", "sha256", "size_chars",
            "created_at", "updated_at", "provenance",
        )
    }


def list_materials(project_id: str) -> Dict[str, Any]:
    """资料页主数据：槽位清单（含状态）+ 自由资料。"""
    slots = load_slots(project_id)
    slot_ids = {slot["slot_id"] for slot in slots}
    slot_views = []
    for slot in slots:
        manifest = load_manifest(project_id, slot["slot_id"])
        slot_views.append({
            **slot,
            "status": "filled" if manifest else "missing",
            "manifest": _manifest_summary(manifest) if manifest else None,
        })
    free = []
    root = materials_root(project_id)
    if root.is_dir():
        for directory in sorted(root.iterdir()):
            if not directory.is_dir() or directory.name in slot_ids:
                continue
            manifest = load_manifest(project_id, directory.name)
            if manifest:
                free.append(_manifest_summary(manifest))
    references = []
    seen = set()
    for slot in slots:
        manifest = load_manifest(project_id, slot["slot_id"])
        if not manifest:
            continue
        uri = f"material://{project_id}/{slot['slot_id']}"
        seen.add(uri)
        references.append({
            "uri": uri,
            "id": slot["slot_id"],
            "title": manifest.get("title") or slot["title"],
            "kind": "slot",
        })
    for manifest in free:
        uri = f"material://{project_id}/{manifest['id']}"
        if uri in seen:
            continue
        references.append({
            "uri": uri,
            "id": manifest["id"],
            "title": manifest.get("title") or manifest["id"],
            "kind": "free",
        })
    return {"project_id": project_id, "slots": slot_views, "free": free, "references": references}


def missing_required_slots(project_id: str) -> List[Dict[str, Any]]:
    return [
        slot
        for slot in load_slots(project_id)
        if slot["required"] and load_manifest(project_id, slot["slot_id"]) is None
    ]


def require_materials(project_id: str) -> None:
    """评测 preflight 门禁：必填槽位缺失即拒跑。"""
    missing = missing_required_slots(project_id)
    if missing:
        names = "、".join(f"{slot['title']}({slot['slot_id']})" for slot in missing)
        raise ValueError(
            f"项目 {project_id} 缺少必填资料槽位：{names}。请到资料管理页（materials.html）填充后再运行评测。"
        )


def binding_materials_for_role(project_id: str, role: str) -> List[Dict[str, Any]]:
    """按角色装载 binding 槽位资料；required 未填即抛错；预算硬校验。"""
    bound = []
    for slot in load_slots(project_id):
        if role not in slot["roles"]:
            continue
        manifest = load_manifest(project_id, slot["slot_id"])
        if manifest is None:
            if slot["required"]:
                raise ValueError(
                    f"项目 {project_id} 角色 {role} 的必填资料槽位 {slot['title']}({slot['slot_id']}) 未填充，"
                    "请到资料管理页填充。"
                )
            continue
        bound.append({
            "id": slot["slot_id"],
            "title": manifest.get("title") or slot["title"],
            "uri": f"material://{project_id}/{slot['slot_id']}",
            "sha256": str(manifest.get("sha256") or ""),
            "content": read_content(project_id, slot["slot_id"]),
        })
    total = sum(len(item["content"]) for item in bound)
    if total > BINDING_BUDGET_CHARS:
        raise ValueError(
            f"项目 {project_id} 角色 {role} 的 binding 资料共 {total} 字符，超过 {BINDING_BUDGET_CHARS} 预算。"
            "请裁剪资料内容（大体量资料应改为检索消费，见资料协议）。"
        )
    return bound


def resolve_material_uri(uri: str) -> str:
    """展开 material://<project>/<id> 引用为资料正文。"""
    text = str(uri or "").strip()
    prefix = "material://"
    if not text.startswith(prefix):
        raise ValueError(f"不是 material 引用: {uri!r}")
    parts = text[len(prefix):].split("/")
    if len(parts) != 2:
        raise ValueError(f"material 引用格式必须是 material://<project>/<id>: {uri!r}")
    return read_content(parts[0], parts[1])


def _format_near_reference_error(raw: str) -> str:
    hints = []
    for match in _MATERIAL_URI_LOOSE.finditer(raw):
        hints.append(match.group(0))
    if not hints:
        return ""
    return (
        "发现疑似资料引用但不是合法记号："
        + "、".join(hints)
        + "。合法形式是 {material://<project>/<id>}（必须有 {} 定界，资料 id 小写字母开头，可含数字/_/-）。"
    )


def expand_material_uris(
    text: str,
    *,
    budget: int | None = None,
) -> str:
    """把正文里的 {material://} 记号替换为封口正文。超预算报错，不静默截断。

    裸写 material:// 会被判定为疑似记号并报错，引导加 {} 定界。
    """
    if budget is None:
        budget = REFERENCE_EXPAND_BUDGET_CHARS
    raw = str(text or "")
    if not raw:
        return raw

    near_error = _format_near_reference_error(_MATERIAL_REF_TOKEN.sub(" ", raw))
    if near_error:
        raise ValueError(near_error)

    stripped = raw.strip()
    if _MATERIAL_REF_TOKEN.fullmatch(stripped):
        expanded = resolve_material_uri(stripped[1:-1])
    elif _MATERIAL_REF_TOKEN.search(raw):
        def replace(match: re.Match[str]) -> str:
            uri = match.group(0)[1:-1]
            body = resolve_material_uri(uri)
            return f"\n--- {uri} ---\n{body.rstrip()}\n--- end {uri} ---\n"

        expanded = _MATERIAL_REF_TOKEN.sub(replace, raw)
    else:
        expanded = raw
    if len(expanded) > budget:
        raise ValueError(
            f"资料引用展开后共 {len(expanded)} 字符，超过 {budget} 上限。请精简资料或拆分引用。"
        )
    return expanded


def _catalog_entry(project_id: str, material_id: str) -> Dict[str, Any]:
    manifest = load_manifest(project_id, material_id)
    if manifest is None:
        raise ValueError(f"资料 {project_id}/{material_id} 不存在")
    return {
        "uri": f"material://{project_id}/{material_id}",
        "project_id": project_id,
        "id": material_id,
        "title": str(manifest.get("title") or material_id),
        "description": str(manifest.get("description") or ""),
        "size_chars": int(manifest.get("size_chars") or 0),
        "sha256": str(manifest.get("sha256") or ""),
    }


def _catalog_stub(entry: Dict[str, Any]) -> str:
    description = entry["description"] or entry["title"]
    return (
        f"\n[大资料未内联] {entry['uri']} · {entry['title']} · "
        f"{entry['size_chars']} 字符 · sha256 {entry['sha256'][:8]}\n"
        f"描述：{description}\n"
        f"正文未进上下文，用检索工具查询（material_id=\"{entry['id']}\"）。\n"
    )


def expand_material_uris_with_catalog(
    text: str,
    *,
    budget: int | None = None,
) -> tuple[str, List[Dict[str, Any]]]:
    """检索式消费的展开：装得下预算的资料内联，装不下的转可检索目录条目。

    返回 (expanded_text, catalog)。与 expand_material_uris 的区别：
    - 单个资料内联后累计超预算 → 不报错，改为目录 stub 进文本 + catalog 条目；
    - 格式错误（裸 material://）和资料不存在照旧报错——引用有效性不因大小豁免。
    catalog 条目字段：uri/project_id/id/title/description/size_chars/sha256。
    """
    if budget is None:
        budget = REFERENCE_EXPAND_BUDGET_CHARS
    raw = str(text or "")
    if not raw:
        return raw, []

    near_error = _format_near_reference_error(_MATERIAL_REF_TOKEN.sub(" ", raw))
    if near_error:
        raise ValueError(near_error)

    catalog: List[Dict[str, Any]] = []
    tokens = list(_MATERIAL_REF_TOKEN.finditer(raw))
    if not tokens:
        if len(raw) > budget:
            raise ValueError(
                f"能力边界文本共 {len(raw)} 字符，超过 {budget} 上限。请精简为陈述句并把细节放进资料。"
            )
        return raw, []

    whole = _MATERIAL_REF_TOKEN.fullmatch(raw.strip()) is not None
    parts: List[str] = []
    cursor = 0
    length = 0
    for match in tokens:
        parts.append(raw[cursor:match.start()])
        length += len(parts[-1])
        uri = match.group(0)[1:-1]
        project_id, material_id = uri[len("material://"):].split("/")
        entry = _catalog_entry(project_id, material_id)
        body = read_content(project_id, material_id)
        inline = (
            body.rstrip() if whole
            else f"\n--- {uri} ---\n{body.rstrip()}\n--- end {uri} ---\n"
        )
        if length + len(inline) <= budget:
            parts.append(inline)
            length += len(inline)
        else:
            stub = _catalog_stub(entry)
            parts.append(stub)
            length += len(stub)
            catalog.append(entry)
        cursor = match.end()
    parts.append(raw[cursor:])
    expanded = "".join(parts)
    return expanded, catalog
