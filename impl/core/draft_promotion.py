from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .project_loader import load_adapter, load_project, load_project_role_instance, resolve_role_assets
from .schema import ProjectSpec


def plan_draft_promotion(spec: ProjectSpec, role: str) -> Dict[str, Any]:
    normalized_role = str(role or "").strip()
    draft_config = getattr(spec, f"{normalized_role}_draft", {}) or {}
    if draft_config.get("enabled") is not True:
        raise ValueError(f"{normalized_role}_draft.enabled must be true before promotion")
    root = Path(spec.root).resolve()
    module = str(draft_config.get("module") or f"draft/{normalized_role}.py")
    candidate_role = _safe_path(root, module, "draft role")
    draft_root = (root / "draft").resolve()
    if not candidate_role.is_relative_to(draft_root) or not candidate_role.is_file():
        raise FileNotFoundError(f"draft role is missing or outside draft/: {candidate_role}")
    production_role = _safe_path(root, f"{normalized_role}.py", "production role")

    operations: List[Dict[str, Any]] = [
        _operation(
            item_id=f"role:{normalized_role}",
            source=candidate_role,
            target=production_role,
            action="move",
            replace=True,
        )
    ]
    assets = resolve_role_assets(spec, normalized_role, use_candidate=True)
    for item in assets:
        mapping = item["mapping"]
        candidate = item["candidate_path"]
        if candidate is None:
            continue
        shared_consumers = [
            other_role
            for other_role in mapping.roles
            if other_role != normalized_role
            and bool((getattr(spec, f"{other_role}_draft", {}) or {}).get("enabled"))
        ]
        action = "copy" if shared_consumers else "move"
        operation = _operation(
            item_id=f"asset:{mapping.asset_id}",
            source=candidate,
            target=item["production_path"],
            action=action,
            replace=mapping.replace,
            shared_consumers=shared_consumers,
        )
        operation["candidate_config_path"] = mapping.candidate_path if action == "move" else ""
        operations.append(operation)

    _validate_operation_set(operations)
    return {
        "project_id": spec.project_id,
        "role": normalized_role,
        "project_yaml": str(root / "project.yaml"),
        "draft_switch": f"{normalized_role}_draft.enabled",
        "operations": operations,
    }


def apply_draft_promotion(spec: ProjectSpec, role: str) -> Dict[str, Any]:
    plan = plan_draft_promotion(spec, role)
    root = Path(spec.root).resolve()
    config_path = root / "project.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"project.yaml not found: {config_path}")
    transaction_root = Path(tempfile.mkdtemp(prefix=".draft-promotion-", dir=str(root)))
    snapshots: List[Dict[str, Any]] = []
    config_backup = transaction_root / "project.yaml"
    shutil.copy2(config_path, config_backup)
    try:
        for index, operation in enumerate(plan["operations"]):
            source = Path(operation["source"])
            target = Path(operation["target"])
            snapshot = {
                "source": source,
                "target": target,
                "source_backup": transaction_root / f"source-{index}",
                "target_backup": transaction_root / f"target-{index}",
                "target_existed": target.exists(),
            }
            _copy_path(source, snapshot["source_backup"])
            if target.exists():
                _copy_path(target, snapshot["target_backup"])
            snapshots.append(snapshot)
            _install_operation(operation)

        _update_project_config(config_path, plan)
        promoted = load_project(spec.project_id)
        adapter = load_adapter(promoted)
        instance = load_project_role_instance(promoted, plan["role"], adapter)
        if instance is None:
            raise RuntimeError(f"promoted role cannot be loaded: {plan['project_id']}/{plan['role']}")
    except Exception:
        shutil.copy2(config_backup, config_path)
        for snapshot in reversed(snapshots):
            _remove_path(snapshot["source"])
            _copy_path(snapshot["source_backup"], snapshot["source"])
            _remove_path(snapshot["target"])
            if snapshot["target_existed"]:
                _copy_path(snapshot["target_backup"], snapshot["target"])
        raise
    finally:
        shutil.rmtree(transaction_root, ignore_errors=True)

    return {**plan, "applied": True, "draft_enabled": False}


def _operation(
    *,
    item_id: str,
    source: Path,
    target: Path,
    action: str,
    replace: bool,
    shared_consumers: Iterable[str] = (),
) -> Dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(f"promotion source not found: {source}")
    if source.resolve() == target.resolve():
        raise ValueError(f"promotion source and target are identical: {source}")
    source_digest = _path_digest(source)
    target_digest = _path_digest(target) if target.exists() else ""
    if target.exists() and source_digest != target_digest and not replace:
        raise FileExistsError(f"promotion target differs and replace=false: {target}")
    return {
        "item_id": item_id,
        "source": str(source),
        "target": str(target),
        "action": action,
        "replace": replace,
        "shared_consumers": sorted(shared_consumers),
        "source_sha256": source_digest,
        "target_sha256": target_digest,
        "target_identical": bool(target_digest and target_digest == source_digest),
    }


def _validate_operation_set(operations: Iterable[Dict[str, Any]]) -> None:
    operations = list(operations)
    sources: set[str] = set()
    targets: set[str] = set()
    for operation in operations:
        source = str(Path(operation["source"]).resolve())
        target = str(Path(operation["target"]).resolve())
        if source in sources:
            raise ValueError(f"duplicate promotion source: {source}")
        if target in targets:
            raise ValueError(f"duplicate promotion target: {target}")
        sources.add(source)
        targets.add(target)
    all_paths = [
        (operation["item_id"], label, Path(operation[label]).resolve())
        for operation in operations
        for label in ("source", "target")
    ]
    for index, (item_id, label, path) in enumerate(all_paths):
        for other_id, other_label, other_path in all_paths[index + 1 :]:
            if path == other_path:
                continue
            if path.is_relative_to(other_path) or other_path.is_relative_to(path):
                raise ValueError(
                    "promotion paths overlap by ancestry: "
                    f"{item_id}.{label}={path}, {other_id}.{other_label}={other_path}"
                )


def _install_operation(operation: Dict[str, Any]) -> None:
    source = Path(operation["source"])
    target = Path(operation["target"])
    identical = operation["target_identical"]
    if identical:
        if operation["action"] == "move":
            _remove_path(source)
        return
    _remove_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if operation["action"] == "copy":
        _copy_path(source, target)
    elif operation["action"] == "move":
        shutil.move(str(source), str(target))
    else:
        raise ValueError(f"unsupported promotion action: {operation['action']}")


def _update_project_config(path: Path, plan: Dict[str, Any]) -> None:
    role = str(plan["role"])
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(?ms)^(?P<header>{re.escape(role)}_draft:\s*\n)(?P<body>(?:^[ \t]+.*\n?)*)"
    )
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"project.yaml has no {role}_draft block")
    body = match.group("body")
    replaced, count = re.subn(r"(?m)^(\s*enabled:\s*)true\s*$", r"\1false", body, count=1)
    if count != 1:
        raise ValueError(f"project.yaml {role}_draft.enabled is not true")
    updated = text[: match.start("body")] + replaced + text[match.end("body") :]
    for operation in plan["operations"]:
        candidate_path = str(operation.get("candidate_config_path") or "")
        if not candidate_path:
            continue
        value = re.escape(candidate_path)
        candidate_pattern = re.compile(
            rf"(?m)^(?P<indent>[ \t]*)candidate_path:\s*(?:{value}|\"{value}\"|'{value}')\s*$"
        )
        updated, candidate_count = candidate_pattern.subn(
            r'\g<indent>candidate_path: ""', updated, count=1
        )
        if candidate_count != 1:
            raise ValueError(f"project.yaml candidate_path not found exactly once: {candidate_path}")
    path.write_text(updated, encoding="utf-8")


def _safe_path(root: Path, value: str, label: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} path must stay under project root: {value}")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{label} path escapes project root: {value}")
    return resolved


def _path_digest(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    if not path.is_dir():
        return ""
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(str(item.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
