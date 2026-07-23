"""Mock 数据完整性检查套件（统一入口）

覆盖三个维度：
  1. Fixture 数据检查 — 所有 mock_cases.json 格式正确、schema 一致、无冗余
  2. Mock 生成机制检查 — build_intent → build_request 管道正常产出合法数据
  3. Schema 一致性检查 — live_schema / REQUEST_SCHEMA / MockCase 三层对齐

运行方式：
  python -m pytest tests/test_mock_data_check.py -v
  python -m impl.core.mock_data_check  # 直接运行检查报告

合并了以下现有检查点：
  - pipeline.check_mock_data()       (impl/core/pipeline.py)
  - fixture_check_registry.py        (hooks/fixture-check/)
  - test_live_schema_check.py        (tests/)
  - 存储层手动校验逻辑               (本轮对话中多次执行的验证脚本)
"""
from __future__ import annotations

import dataclasses
import importlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pathlib import Path

from impl.core.mock_agent import load_live_schema
from impl.core.project_loader import list_projects, load_project
from impl.core.schema.normalize import normalize_mock_case
from impl.core.schema import MockCase, MockIntentOutput, SingleTurnCase
from impl.core.schema.occam import PUBLIC_SCHEMA_FIELDS, SCHEMA_FIELD_ROLES, PUBLIC_DROP_KEYS
from impl.core.mock import single_turn_to_mock_case, mock_case_to_single_turn

IMPL_ROOT = Path(__file__).resolve().parents[1] if "__file__" in dir() else Path.cwd() / "impl"

# ── 全局 schema 类名 → dataclass 映射（用于 Occam 同步检查） ──
_SCHEMA_MODULES = [
    "impl.core.schema.mock", "impl.core.schema.trace", "impl.core.schema.judge",
    "impl.core.schema.attribute", "impl.core.schema.live", "impl.core.schema.base",
    "impl.core.schema.evidence", "impl.core.schema.fallback", "impl.core.schema.table",
    "impl.core.schema.frontend", "impl.core.schema.cluster", "impl.core.schema.check",
    "impl.core.schema.project", "impl.core.schema.api", "impl.core.schema.batch",
    "impl.core.schema.context",
]
_SCHEMA_CLASSES: Dict[str, type] = {}
for _mod_name in _SCHEMA_MODULES:
    try:
        _mod = importlib.import_module(_mod_name)
        for _name in dir(_mod):
            _cls = getattr(_mod, _name)
            if dataclasses.is_dataclass(_cls) and isinstance(_cls, type):
                _SCHEMA_CLASSES[_name] = _cls
    except Exception:
        pass


# ── 数据类 ──

@dataclass
class CheckItem:
    name: str
    passed: bool = False
    detail: str = ""
    errors: List[str] = field(default_factory=list)


@dataclass
class CheckReport:
    project_id: str
    items: List[CheckItem] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(item.passed for item in self.items)

    @property
    def passed_count(self) -> int:
        return sum(1 for item in self.items if item.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if not item.passed)


# ── 1. Fixture 数据检查 ──

def check_fixture_file_exists(project_id: str) -> CheckItem:
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    if path.exists():
        return CheckItem("fixture_file_exists", True, str(path))
    return CheckItem("fixture_file_exists", False, f"missing: {path}")


def check_fixture_is_valid_json(project_id: str) -> CheckItem:
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return CheckItem("fixture_is_valid_json", True, f"{len(data)} cases")
        return CheckItem("fixture_is_valid_json", False, "not a list")
    except Exception as e:
        return CheckItem("fixture_is_valid_json", False, str(e))


def check_fixture_mockcase_format(project_id: str) -> CheckItem:
    """检查所有 case 是否都是 MockCase 格式（intent + live_request）。"""
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    bad = []
    for i, c in enumerate(cases):
        if not isinstance(c.get("intent"), dict) or not isinstance(c.get("live_request"), dict):
            bad.append((i, c.get("id") or c.get("case_id") or f"case[{i}]"))
    if bad:
        return CheckItem("fixture_mockcase_format", False, f"{len(bad)} cases not MockCase format", [f"{cid}: missing intent or live_request" for _, cid in bad])
    return CheckItem("fixture_mockcase_format", True, f"{len(cases)} cases OK")


def check_fixture_no_legacy_fields(project_id: str) -> CheckItem:
    """检查是否还有旧格式字段（input, source, status, metadata 在顶层）。"""
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    legacy_keys = {"input", "source", "status", "table_row", "expected_intent", "user_context"}
    warnings = []
    for i, c in enumerate(cases):
        found = legacy_keys & set(c.keys())
        if found:
            warnings.append(f"{c.get('id', f'case[{i}]')}: legacy fields {found}")
    if warnings:
        return CheckItem("fixture_no_legacy_fields", False, f"{len(warnings)} cases with legacy fields", warnings)
    return CheckItem("fixture_no_legacy_fields", True, f"{len(cases)} cases clean")


def check_fixture_schema_validation(project_id: str) -> CheckItem:
    """live_schema.check_all() 校验所有 fixture case。"""
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    ls = load_live_schema(project_id)
    if ls is None:
        return CheckItem("fixture_schema_validation", False, "live_schema not found")
    r = ls.check.check_all(cases)
    if r["failed"] == 0:
        return CheckItem("fixture_schema_validation", True, f"{r['passed']}/{r['total']} passed")
    errors = [f"{d['case_id']}: {d['errors']}" for d in r["details"] if not d["passed"]]
    return CheckItem("fixture_schema_validation", False, f"{r['failed']}/{r['total']} failed", errors)


def check_fixture_normalize_roundtrip(project_id: str) -> CheckItem:
    """MockCase → normalize_mock_case → SingleTurnCase → MockCase 往返一致。"""
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    errors = []
    for c in cases:
        stc = normalize_mock_case(c)
        if stc is None:
            errors.append(f"{c.get('id')}: normalize_mock_case returned None")
            continue
        mc = single_turn_to_mock_case(stc, project_id)
        if mc.id != c["id"]:
            errors.append(f"{c['id']}: id mismatch {mc.id}")
        if mc.live_request != c["live_request"]:
            errors.append(f"{c['id']}: live_request mismatch")
    if errors:
        return CheckItem("fixture_normalize_roundtrip", False, f"{len(errors)} errors", errors)
    return CheckItem("fixture_normalize_roundtrip", True, f"{len(cases)} cases OK")


def check_fixture_scenario_coverage(project_id: str) -> CheckItem:
    """检查 fixture 场景覆盖是否与 ProjectSpec 场景目录对齐。"""
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    defined = set(load_project(project_id).scenarios)
    actual = set(c.get("scenario", "") for c in cases)
    uncovered = defined - actual
    unknown = actual - defined
    messages = []
    if uncovered:
        messages.append(f"uncovered: {sorted(uncovered)}")
    if unknown:
        messages.append(f"unknown: {sorted(unknown)}")
    if messages:
        return CheckItem("fixture_scenario_coverage", not uncovered, "; ".join(messages))
    return CheckItem("fixture_scenario_coverage", True, f"{len(actual)} scenarios, all defined")


# ── 2. Mock 生成机制检查 ──

def check_mock_build_intent_shape(project_id: str) -> CheckItem:
    """mock_build_intent 产出完整 MockCase 格式（7 个字段）。"""
    from impl.core.pipeline import mock_build_intent
    from impl.core.schema.base import to_dict
    try:
        result = mock_build_intent(project_id)
        expected = {"id", "project_id", "scenario", "intent", "live_request", "output", "reference"}
        if isinstance(result, MockCase):
            keys = set(to_dict(result).keys())
        elif isinstance(result, dict):
            keys = set(result.keys())
        else:
            keys = set()
        if keys == expected:
            return CheckItem("mock_build_intent_shape", True, "all 7 keys present")
        missing = expected - keys
        extra = keys - expected
        return CheckItem("mock_build_intent_shape", False, f"missing={missing}, extra={extra}")
    except Exception as e:
        return CheckItem("mock_build_intent_shape", False, str(e))


def check_mock_build_intent_schema(project_id: str) -> CheckItem:
    """mock_build_intent 产出的 live_request 符合 REQUEST_SCHEMA。"""
    from impl.core.pipeline import mock_build_intent
    try:
        result = mock_build_intent(project_id)
        if isinstance(result, MockCase):
            live_request = result.live_request
        else:
            live_request = result.get("live_request", {})
        if not live_request:
            return CheckItem("mock_build_intent_schema", False, "live_request is empty — LLM failed to generate")
        ls = load_live_schema(project_id)
        if ls and hasattr(ls, "check"):
            ok = ls.check.request(live_request)
            if ok:
                return CheckItem("mock_build_intent_schema", True, "live_request passes REQUEST_SCHEMA")
            return CheckItem("mock_build_intent_schema", False, "live_request fails REQUEST_SCHEMA")
        return CheckItem("mock_build_intent_schema", True, "no schema checker (skip)")
    except Exception as e:
        return CheckItem("mock_build_intent_schema", False, str(e))


def check_mock_build_intent_pipeline_path(project_id: str) -> CheckItem:
    """mock_build_intent → normalize_mock_case → _fixture_mock_cases 全链路通。"""
    from impl.core.pipeline import mock_build_intent
    from impl.core.schema.base import to_dict
    try:
        result = mock_build_intent(project_id)
        if isinstance(result, MockCase):
            d = to_dict(result)
        else:
            d = result
        stc = normalize_mock_case(d)
        if stc is None:
            return CheckItem("mock_build_intent_pipeline", False, "normalize_mock_case returned None")
        if not stc.input:
            return CheckItem("mock_build_intent_pipeline", False, "parsed input is empty")
        return CheckItem("mock_build_intent_pipeline", True, f"input keys: {list(stc.input.keys())[:5]}")
    except Exception as e:
        return CheckItem("mock_build_intent_pipeline", False, str(e))


# ── 3. Schema 一致性检查 ──

def check_live_schema_dataclass_export(project_id: str) -> CheckItem:
    """live_schema 导出 REQUEST_SCHEMA 和 EXTRACT_OUTPUT_SCHEMA 且都是 dataclass。"""
    import dataclasses
    ls = load_live_schema(project_id)
    if ls is None:
        return CheckItem("live_schema_dataclass", False, "live_schema not found")
    req = getattr(ls, "REQUEST_SCHEMA", None)
    out = getattr(ls, "EXTRACT_OUTPUT_SCHEMA", None)
    errors = []
    if not dataclasses.is_dataclass(req):
        errors.append("REQUEST_SCHEMA is not a dataclass")
    if not dataclasses.is_dataclass(out):
        errors.append("EXTRACT_OUTPUT_SCHEMA is not a dataclass")
    if errors:
        return CheckItem("live_schema_dataclass", False, "; ".join(errors))
    return CheckItem("live_schema_dataclass", True, f"{req.__name__} / {out.__name__}")


def check_live_schema_fields_match_fixture(project_id: str) -> CheckItem:
    """fixture 的 live_request 字段是 REQUEST_SCHEMA 字段的子集（不额外）。"""
    import dataclasses
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    ls = load_live_schema(project_id)
    req_schema = ls.REQUEST_SCHEMA
    allowed = {f.name for f in dataclasses.fields(req_schema)}
    issues = []
    for c in cases:
        extra = set(c.get("live_request", {}).keys()) - allowed
        if extra:
            issues.append(f"{c['id']}: extra fields {extra}")
    if issues:
        return CheckItem("live_schema_fields_match", False, f"{len(issues)} cases with extra fields", issues[:3])
    return CheckItem("live_schema_fields_match", True, f"{len(cases)} cases OK")


def check_mockcase_intent_consistency(project_id: str) -> CheckItem:
    """fixture 的 intent 层字段一致（user_intent/query 至少有一个非空）。"""
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    issues = []
    for c in cases:
        intent = c.get("intent", {})
        if not isinstance(intent, dict):
            issues.append(f"{c['id']}: intent is not a dict")
            continue
        if not intent.get("user_intent") and not intent.get("query"):
            issues.append(f"{c['id']}: intent.user_intent and intent.query both empty")
    if issues:
        return CheckItem("mockcase_intent_consistency", False, f"{len(issues)} issues", issues[:5])
    return CheckItem("mockcase_intent_consistency", True, f"{len(cases)} cases OK")


def check_mockcase_ready_protocol(project_id: str) -> CheckItem:
    """ready 协议一致性：output/reference 按声明存在。"""
    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    ready = set(load_project(project_id).ready)
    issues = []
    for c in cases:
        if "output" in ready:
            if c.get("output") is None:
                issues.append(f"{c['id']}: ready contains output but case has None")
        else:
            if c.get("output") is not None:
                issues.append(f"{c['id']}: ready does not contain output but case has value")
        if "reference" in ready:
            if c.get("reference") is None:
                issues.append(f"{c['id']}: ready contains reference but case has None")
        else:
            if c.get("reference") is not None:
                issues.append(f"{c['id']}: ready does not contain reference but case has value")
    if issues:
        return CheckItem("mockcase_ready_protocol", False, f"{len(issues)} issues", issues[:5])
    return CheckItem("mockcase_ready_protocol", True, f"ready={sorted(ready)}, {len(cases)} cases OK")


# ── 4. Occam / Schema 全局一致性检查（不依赖具体项目） ──

def _is_required_field(f: dataclasses.Field) -> bool:
    """判断 dataclass 字段是否为必须（无默认值且非 Optional）。"""
    return (f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING)


def check_occam_public_fields_sync(project_id: str = "") -> CheckItem:
    """PUBLIC_SCHEMA_FIELDS 是否与实际 dataclass fields 同步。

    检查每个在 PUBLIC_SCHEMA_FIELDS 中声明了字段列表的 schema，
    其列表是否与实际 dataclass 的 fields 一致：无多余（stale）、无遗漏（missing）。
    """
    issues = []
    tracked = 0
    for schema_name, declared_fields in PUBLIC_SCHEMA_FIELDS.items():
        if declared_fields is None:
            continue
        tracked += 1
        cls = _SCHEMA_CLASSES.get(schema_name)
        if cls is None:
            issues.append(f"{schema_name}: class not found in any schema module")
            continue
        actual = {f.name for f in dataclasses.fields(cls)}
        declared = set(declared_fields)
        stale = declared - actual
        missing = actual - declared
        if stale:
            issues.append(f"{schema_name}: stale fields in PUBLIC_SCHEMA_FIELDS → {sorted(stale)}")
        if missing:
            issues.append(f"{schema_name}: missing from PUBLIC_SCHEMA_FIELDS → {sorted(missing)}")
    if issues:
        return CheckItem("occam_public_fields_sync", False, f"{len(issues)} sync gaps", issues)
    return CheckItem("occam_public_fields_sync", True, f"{tracked} schemas, all synced")


def check_occam_field_roles_completeness(project_id: str = "") -> CheckItem:
    """SCHEMA_FIELD_ROLES 是否覆盖了每个 schema 的全部字段。

    对每个在 SCHEMA_FIELD_ROLES 中出现的 schema，检查其所有 dataclass fields
    是否都有角色标注。未被标注的字段视为遗漏。
    """
    issues = []
    for schema_name, roles in SCHEMA_FIELD_ROLES.items():
        classified = set()
        for field_list in roles.values():
            classified.update(field_list)
        cls = _SCHEMA_CLASSES.get(schema_name)
        if cls is None:
            issues.append(f"{schema_name}: class not found")
            continue
        actual = {f.name for f in dataclasses.fields(cls)}
        unclassified = actual - classified
        if unclassified:
            issues.append(f"{schema_name}: unclassified fields → {sorted(unclassified)}")
    if issues:
        return CheckItem("occam_field_roles_completeness", False, f"{len(issues)} gaps", issues)
    return CheckItem("occam_field_roles_completeness", True,
                     f"{len(SCHEMA_FIELD_ROLES)} schemas, all fields classified")


def check_public_drop_keys_validity(project_id: str = "") -> CheckItem:
    """PUBLIC_DROP_KEYS 中的 key 是否至少出现在某个 schema dataclass 中。

    防止残留了已被重构删除的字段名在过滤列表中。
    """
    all_fields: set[str] = set()
    for cls in _SCHEMA_CLASSES.values():
        all_fields.update(f.name for f in dataclasses.fields(cls))
    phantom = PUBLIC_DROP_KEYS - all_fields
    if phantom:
        return CheckItem("public_drop_keys_validity", False,
                         f"{len(phantom)} phantom keys", [f"'{k}' not in any dataclass" for k in sorted(phantom)])
    return CheckItem("public_drop_keys_validity", True, f"{len(PUBLIC_DROP_KEYS)} keys, all valid")


def check_fixture_id_uniqueness(project_id: str = "") -> CheckItem:
    """所有项目的 MockCase ID 是否全局唯一（无跨项目重复）。"""
    project_ids = list_projects()
    seen: Dict[str, str] = {}
    duplicates: List[str] = []
    for pid in project_ids:
        path = IMPL_ROOT / "data" / pid / "mock_cases.json"
        if not path.exists():
            continue
        with open(path) as f:
            cases = json.load(f)
        for c in cases:
            cid = c.get("id", "")
            if not cid:
                continue
            if cid in seen:
                duplicates.append(f"'{cid}' appears in both {seen[cid]} and {pid}")
            seen[cid] = pid
    if duplicates:
        return CheckItem("fixture_id_uniqueness", False, f"{len(duplicates)} duplicates", duplicates)
    return CheckItem("fixture_id_uniqueness", True, f"{len(seen)} IDs across {len(project_ids)} projects, all unique")


# ── 5. 必需字段完整性检查（按项目） ──

def check_fixture_required_fields_present(project_id: str) -> CheckItem:
    """Fixture live_request 是否包含 REQUEST_SCHEMA 的所有必需（无默认值）字段。

    与 check_live_schema_fields_match_fixture（只检查无额外字段）互补，
    构成"不多不少"的完整校验。
    """
    ls = load_live_schema(project_id)
    if ls is None:
        return CheckItem("fixture_required_fields_present", False, "live_schema not found")
    req_cls = getattr(ls, "REQUEST_SCHEMA", None)
    if req_cls is None or not dataclasses.is_dataclass(req_cls):
        return CheckItem("fixture_required_fields_present", False, "REQUEST_SCHEMA not a dataclass")
    required = {f.name for f in dataclasses.fields(req_cls) if _is_required_field(f)}

    path = IMPL_ROOT / "data" / project_id / "mock_cases.json"
    with open(path) as f:
        cases = json.load(f)
    issues = []
    for c in cases:
        lr = c.get("live_request", {})
        missing = required - set(lr.keys())
        if missing:
            issues.append(f"{c['id']}: missing required fields {sorted(missing)}")
    if issues:
        return CheckItem("fixture_required_fields_present", False, f"{len(issues)} cases incomplete", issues[:5])
    return CheckItem("fixture_required_fields_present", True, f"{len(cases)} cases, all required fields present")


# ── 完整检查列表 ──

_CHECK_FUNCTIONS = [
    # 1. Fixture 数据
    check_fixture_file_exists,
    check_fixture_is_valid_json,
    check_fixture_mockcase_format,
    check_fixture_no_legacy_fields,
    check_fixture_schema_validation,
    check_fixture_normalize_roundtrip,
    check_fixture_scenario_coverage,
    # 2. Mock 生成机制
    check_mock_build_intent_shape,
    check_mock_build_intent_schema,
    check_mock_build_intent_pipeline_path,
    # 3. Schema 一致性
    check_live_schema_dataclass_export,
    check_live_schema_fields_match_fixture,
    check_mockcase_intent_consistency,
    check_mockcase_ready_protocol,
    # 5. 必需字段完整性
    check_fixture_required_fields_present,
]

_GLOBAL_CHECK_FUNCTIONS = [
    check_occam_public_fields_sync,
    check_occam_field_roles_completeness,
    check_public_drop_keys_validity,
    check_fixture_id_uniqueness,
]


def check_project(project_id: str) -> CheckReport:
    """对单个项目运行完整的 mock 数据检查。"""
    report = CheckReport(project_id=project_id)
    for fn in _CHECK_FUNCTIONS:
        try:
            item = fn(project_id)
            report.items.append(item)
        except Exception as exc:
            report.items.append(CheckItem(fn.__name__, False, str(exc)))
    return report


def check_all() -> Dict[str, CheckReport]:
    """对所有项目运行检查（含全局一致性检查）。"""
    reports = {pid: check_project(pid) for pid in list_projects()}
    # 全局检查（不依赖具体项目）
    global_report = CheckReport(project_id="*global*")
    for fn in _GLOBAL_CHECK_FUNCTIONS:
        try:
            item = fn()
            global_report.items.append(item)
        except Exception as exc:
            global_report.items.append(CheckItem(fn.__name__, False, str(exc)))
    reports["*global*"] = global_report
    return reports


def print_report(reports: Dict[str, CheckReport], verbose: bool = False) -> None:
    """打印检查报告。"""
    total_passed = 0
    total_items = 0
    for pid, report in reports.items():
        if pid == "*global*":
            continue  # 全局结果单独打印
        status = "✅" if report.all_passed else "❌"
        print(f"\n{status} {pid}: {report.passed_count}/{report.passed_count + report.failed_count} passed")
        for item in report.items:
            if item.passed and not verbose:
                continue
            icon = "  ✅" if item.passed else "  ❌"
            print(f"{icon} {item.name}: {item.detail}")
            for err in item.errors:
                print(f"       {err}")
        total_passed += report.passed_count
        total_items += report.passed_count + report.failed_count

    # 全局检查
    global_report = reports.get("*global*")
    if global_report:
        gs = "✅" if global_report.all_passed else "❌"
        print(f"\n{gs} 【全局检查】: {global_report.passed_count}/{global_report.passed_count + global_report.failed_count} passed")
        for item in global_report.items:
            if item.passed and not verbose:
                continue
            icon = "  ✅" if item.passed else "  ❌"
            print(f"{icon} {item.name}: {item.detail}")
            for err in item.errors:
                print(f"       {err}")
        total_passed += global_report.passed_count
        total_items += global_report.passed_count + global_report.failed_count

    print(f"\n{'='*50}")
    print(f"Total: {total_passed}/{total_items} passed ({total_items - total_passed} failed)")


if __name__ == "__main__":
    reports = check_all()
    print_report(reports, verbose=True)
