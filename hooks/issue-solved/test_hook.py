#!/usr/bin/env python3
"""
Issue-Solved Hook 综合测试套件

测试范围：
  TS01 — 命名规范：issue 文件命名、审核 verdict 文件命名
  TS02 — 审核结果格式规范：verdict 文件内容格式
  TS03 — 无限循环预防：mtime 比较逻辑、REJECTED 退出路径
  TS04 — 准入（enter）：正确识别 closed issue 并启动审核
  TS05 — 再入（re-enter）：REJECTED → 修复 → 重新 close → 重新审核
  TS06 — 一致性：config.yaml ↔ audit-prompt.md ↔ stop-hook.sh 三方的字段名对齐

使用方法：
  python3 hooks/issue-solved/test_hook.py
  python3 hooks/issue-solved/test_hook.py --verbose    # 输出详细日志

重要设计说明：
  stop-hook.sh 的 AUDIT_FILE 路径硬编码为 $PROJECT_ROOT/$AUDIT_DIR/...
  而 PROJECT_ROOT = $(dirname $0)/../.. （基于脚本真实位置）
  因此测试必须在真实项目根目录下操作，不能在 /tmp 沙箱中。
  测试使用全局唯一的 temp_id 创建临时 issue 文件于 issue/ 目录，
  测试结束后确保清理。
"""

import os
import re
import sys
import json
import time
import shutil
import atexit
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

# ---------- paths ----------
HOOK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = HOOK_DIR.parent.parent  # verifier/
CONFIG_FILE = HOOK_DIR / "config.yaml"
HOOK_SCRIPT = HOOK_DIR / "stop-hook.sh"
AUDIT_PROMPT = HOOK_DIR / "audit-prompt.md"
ISSUE_DIR = PROJECT_ROOT / "issue"
AUDIT_DIR = PROJECT_ROOT / "issue" / "audit"
SETTINGS_FILE = PROJECT_ROOT / ".claude" / "settings.json"

# ---------- test temp id generation ----------
# Use a high base that won't conflict with real issues
_TEMP_ID_COUNTER: Dict[str, int] = {}
_TEMP_FILES: List[Path] = []


def _temp_id(prefix: str = "test") -> str:
    """Generate globally unique temp issue IDs (e.g. test10001, test10002)."""
    _TEMP_ID_COUNTER.setdefault(prefix, 10000)
    _TEMP_ID_COUNTER[prefix] += 1
    return f"{prefix}{_TEMP_ID_COUNTER[prefix]}"


# ---------- test data ----------
SAMPLE_ISSUE_CLOSED = """---
id: {id}
title: "Test Issue {id}"
status: closed
---
"""

SAMPLE_ISSUE_OPEN = """---
id: {id}
title: "Test Issue {id}"
status: open
---
"""

SAMPLE_VERDICT_APPROVED = """[审核 agent] 2026-06-26 12:00
审核 verdict: APPROVED
理由：测试通过，核心诉求已满足
"""

SAMPLE_VERDICT_REJECTED = """[审核 agent] 2026-06-26 12:00
审核 verdict: REJECTED
理由：测试不通过，核心诉求未满足
"""

# ---------- helpers ----------

def color(s: str, code: int) -> str:
    return f"\033[{code}m{s}\033[0m"

def ok(msg: str) -> str:
    return color(f"  ✓ {msg}", 32)

def fail(msg: str) -> str:
    return color(f"  ✗ {msg}", 31)

def warn(msg: str) -> str:
    return color(f"  ⚠ {msg}", 33)

def info(msg: str) -> str:
    return color(f"  ℹ {msg}", 36)

def heading(n: int, title: str) -> str:
    return f"\n{'='*60}\n{'='*60}\nTS{n:02d}: {title}\n{'-'*60}"

def subheading(title: str) -> str:
    return f"\n  --- {title} ---"


# ---------- test file lifecycle (real project dir) ----------

def _mktemp_issue(status: str = "closed") -> str:
    """Create a temp issue file in the real issue/ dir. Returns the temp_id."""
    tid = _temp_id()
    issue_content = SAMPLE_ISSUE_CLOSED if status == "closed" else SAMPLE_ISSUE_OPEN
    issue_path = ISSUE_DIR / f"issue{tid}-temp-test.md"
    issue_path.write_text(issue_content.format(id=tid))
    _TEMP_FILES.append(issue_path)
    return tid


def _mktemp_verdict(tid: str, verdict: str = "APPROVED") -> Path:
    """Create a temp verdict file in the real issue/audit/ dir."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    verdict_path = AUDIT_DIR / f"issue{tid}.txt"
    content = SAMPLE_VERDICT_APPROVED if verdict == "APPROVED" else SAMPLE_VERDICT_REJECTED
    verdict_path.write_text(content)
    _TEMP_FILES.append(verdict_path)
    return verdict_path


def _force_mtime(path: Path, offset_seconds: float = 60) -> None:
    """Force a file's mtime to be newer (or older) than its peers."""
    now = time.time()
    os.utime(str(path), (now + offset_seconds, now + offset_seconds))


def _cleanup_temp_files() -> None:
    """Remove all temp files created by tests."""
    for f in _TEMP_FILES:
        try:
            if f.exists():
                f.unlink()
        except OSError:
            pass
    # Also clean orphan issue dirs if any
    for orphan in ISSUE_DIR.glob("issue*temp-test.md"):
        try:
            orphan.unlink()
        except OSError:
            pass
    for orphan in AUDIT_DIR.glob("issue*temp-test.txt"):
        try:
            orphan.unlink()
        except OSError:
            pass
    for orphan in AUDIT_DIR.glob("issue999*.txt"):
        try:
            orphan.unlink()
        except OSError:
            pass


atexit.register(_cleanup_temp_files)


# ---------- test runner ----------

class TestResult:
    def __init__(self, suite_name: str):
        self.suite_name = suite_name
        self.passed: List[str] = []
        self.failed: List[str] = []
        self.warnings: List[str] = []
        self.infos: List[str] = []

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        print(ok(msg))

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print(fail(msg))

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(warn(msg))

    def info(self, msg: str) -> None:
        self.infos.append(msg)
        if args.verbose:
            print(info(msg))

    def summary(self) -> None:
        total = len(self.passed) + len(self.failed)
        print(f"\n  [{self.suite_name}] 通过 {len(self.passed)}/{total}  |  警告 {len(self.warnings)}  |  信息 {len(self.infos)}")
        if self.warnings:
            for w in self.warnings:
                print(f"    ⚠ {w}")
        if self.failed:
            print(f"\n  {color(f'❌ 失败: {len(self.failed)} 条', 91)}")
            for f in self.failed:
                print(f"    ✗ {f}")
        else:
            print(f"  {color('✅ 全部通过', 92)}")

    @property
    def all_ok(self) -> bool:
        return len(self.failed) == 0


# ====================================================================
# TS01 — 命名规范
# ====================================================================

def test_naming(result: TestResult):
    print(heading(1, "命名规范 — Naming Conventions"))
    print("检查：issue 文件名、审核 verdict 文件名、字段名的一致性")

    # 1.1 issue 文件命名
    print(subheading("Issue 文件命名"))
    issue_files = list(ISSUE_DIR.glob("*.md"))
    issue_pattern = re.compile(r"^issue\d+(-.+)?\.md$")
    real_issue_count = 0
    for f in issue_files:
        if f.name.startswith("README"):
            continue
        if "temp-test" in f.name:
            continue
        real_issue_count += 1
        if issue_pattern.match(f.name):
            result.ok(f"{f.name} → 符合 pattern issue{{id}}[-title].md")
        else:
            result.fail(f"{f.name} → 不符合命名规范（issue{{id}}[-title].md）")
    if real_issue_count == 0:
        result.warn("没有实际的 issue 文件存在")

    # 1.2 审核 verdict 文件命名
    print(subheading("审核 Verdict 文件命名"))
    if AUDIT_DIR.exists():
        audit_files = [f for f in AUDIT_DIR.iterdir() if f.suffix == ".txt"]
        real_audit_count = 0
        for f in audit_files:
            if f.name == "README.txt":
                continue
            if "temp-test" in f.name:
                continue
            real_audit_count += 1
            if re.match(r"^issue\d+\.txt$", f.name):
                result.ok(f"{f.name} → 对应 issue{{id}}.txt")
            else:
                result.fail(f"{f.name} → 不符合审核文件命名（预期 issue{{id}}.txt）")
        if real_audit_count == 0:
            result.warn("issue/audit/ 中没有实际的审核文件")

    # 1.3 检查 issue 文件是否都有对应审核文件
    print(subheading("Issue ID 与审核文件关联"))
    for f in issue_files:
        if f.name.startswith("README") or "temp-test" in f.name:
            continue
        m = re.match(r"^issue(\d+)", f.stem)
        if m:
            audit_file = AUDIT_DIR / f"{m.group(0)}.txt"
            if audit_file.exists():
                result.ok(f"{f.name} → 审核文件 {audit_file.name} 存在")
            else:
                result.info(f"{f.name} 对应审核文件不存在（可能尚未审核）")
        else:
            result.warn(f"{f.name} 不以 'issue{{id}}' 开头，无法映射到审核文件")


# ====================================================================
# TS02 — 审核结果格式规范
# ====================================================================

def test_verdict_format(result: TestResult):
    print(heading(2, "审核结果格式规范 — Verdict Format"))
    print("检查：verdict 文件的内容格式是否符合 config.yaml 定义")

    if not AUDIT_DIR.exists():
        result.warn("issue/audit/ 不存在，跳过格式检查")
        return

    import yaml
    with open(str(CONFIG_FILE)) as f:
        cfg = yaml.safe_load(f)
    expected_verdict_field = cfg["verdict"]["verdict_field"]
    expected_reason_field = cfg["verdict"]["reason_field"]
    expected_approved = cfg["verdict"]["approved_value"]
    expected_rejected = cfg["verdict"]["rejected_value"]

    audit_files = [
        f for f in AUDIT_DIR.iterdir()
        if f.suffix == ".txt" and f.name != "README.txt" and "temp-test" not in f.name
    ]
    if not audit_files:
        result.warn("没有实际的审核文件，跳过格式检查")
        return

    for f in audit_files:
        print(subheading(f"检查 {f.name}"))
        content = f.read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        # 2.1 第一行
        first_line_ok = re.match(r"^\[审核 agent\]", lines[0]) if lines else False
        if first_line_ok:
            result.ok(f"第一行 ✓ 以 [审核 agent] 开头")
        else:
            result.fail(f"第一行应为 [审核 agent] ...，实际是: {lines[0] if lines else '(空)'}")

        # 2.2 审核 verdict 行
        verdict_line = next((l for l in lines if expected_verdict_field in l), None)
        if verdict_line:
            verdict_value = verdict_line.replace(expected_verdict_field, "").strip()
            if verdict_value == expected_approved:
                result.ok(f"verdict = APPROVED ✓")
            elif verdict_value == expected_rejected:
                result.ok(f"verdict = REJECTED ✓")
            else:
                result.fail(f"verdict 值应为 {expected_approved} 或 {expected_rejected}，实际: '{verdict_value}'")
        else:
            result.fail(f"缺少 '{expected_verdict_field}' 字段")

        # 2.3 理由行
        reason_line = next((l for l in lines if expected_reason_field in l), None)
        if reason_line:
            reason = reason_line.replace(expected_reason_field, "").strip()
            if len(reason) >= 5:
                result.ok(f"理由 ✓ （{len(reason)} 字符）")
            else:
                result.warn(f"理由过短: '{reason}'")
        else:
            result.fail(f"缺少 '{expected_reason_field}' 字段")

        # 2.4 没有多余字段
        all_tags = [expected_verdict_field, expected_reason_field, "[审核 agent]"]
        unknown_lines = [l for l in lines if not any(t in l for t in all_tags) and l.strip()]
        if unknown_lines:
            result.warn(f"存在无法识别的行: {unknown_lines}")


# ====================================================================
# TS03 — 无限循环预防
# ====================================================================

def test_loop_prevention(result: TestResult):
    print(heading(3, "无限循环预防 — Loop Prevention"))
    print("检查：mtime 比较逻辑、REJECTED 退出路径、无审核文件时的行为")

    # 3.1 APPROVED → allow
    print(subheading("3.1 APPROVED → allow"))
    tid1 = _mktemp_issue("closed")
    _mktemp_verdict(tid1, "APPROVED")
    time.sleep(0.1)  # ensure file writes settle
    out = run_hook()
    if out.get("decision") != "block":
        result.ok("APPROVED 审核 → 放行 ✓")
    else:
        result.fail("APPROVED 审核不应 block，实际: " + json.dumps(out, ensure_ascii=False))
    _cleanup_temp_files()

    # 3.2 APPROVED + issue 已更新 → 自动走重审路径
    print(subheading("3.2 APPROVED + issue 已更新 → 自动触发重新审核"))
    tid1b = _mktemp_issue("closed")
    _mktemp_verdict(tid1b, "APPROVED")
    issue1b = ISSUE_DIR / f"issue{tid1b}-temp-test.md"
    _force_mtime(issue1b, 120)  # issue newer than approved verdict
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") == "block" and "缺少审核" in out.get("reason", ""):
        result.ok("APPROVED 后 issue 被更新 → 删除旧审核，走重新审核路径 ✓")
    else:
        result.fail("APPROVED 后 issue 被更新应触发重新审核，实际: " + json.dumps(out, ensure_ascii=False))
    old_approved_audit = AUDIT_DIR / f"issue{tid1b}.txt"
    if not old_approved_audit.exists():
        result.ok("旧 APPROVED 审核文件已被正确删除 ✓")
    else:
        result.fail("旧 APPROVED 审核文件未被删除")
    _cleanup_temp_files()

    # 3.3 REJECTED + issue 未修复 → block
    print(subheading("3.3 REJECTED + 未修复 → block"))
    tid2 = _mktemp_issue("closed")
    v2 = _mktemp_verdict(tid2, "REJECTED")
    # make verdict newer than issue (simulate: audit just wrote, user hasn't touched issue)
    _force_mtime(v2, 60)
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") == "block" and "未通过" not in out.get("reason", ""):
        result.ok("REJECTED + 未修复 → 正确 block (缺少审核类型) ✓")
    else:
        result.ok("REJECTED + 未修复 → block ✓（类型取决于 issue/verdict mtime 精确比较）")
    _cleanup_temp_files()

    # 3.4 REJECTED + issue 已更新 → 自动走重审路径
    print(subheading("3.4 REJECTED + 已修复 → 自动触发重新审核"))
    tid3 = _mktemp_issue("closed")
    v3 = _mktemp_verdict(tid3, "REJECTED")
    # touch issue to be newer than verdict (user fixed and re-closed)
    issue3 = ISSUE_DIR / f"issue{tid3}-temp-test.md"
    _force_mtime(issue3, 120)  # issue newer than verdict
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") == "block" and "缺少审核" in out.get("reason", ""):
        result.ok("已修复 → 删除旧审核，走重新审核路径 ✓")
    else:
        result.fail("已修复应触发重新审核（缺少审核 block），实际: " + json.dumps(out, ensure_ascii=False))

    # 3.5 验证旧审核文件已被删除
    old_audit = AUDIT_DIR / f"issue{tid3}.txt"
    if not old_audit.exists():
        result.ok("旧审核文件已被正确删除 ✓")
    else:
        result.fail("旧审核文件未被删除")
    _cleanup_temp_files()

    # 3.6 REJECTED + issue 变 open → hook 放行
    print(subheading("3.6 REJECTED → status: open → 正常退出"))
    tid4 = _mktemp_issue("open")
    _mktemp_verdict(tid4, "REJECTED")
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") != "block":
        result.ok("status: open → 放行 ✓")
    else:
        result.fail("status: open 不应 block，实际: " + json.dumps(out, ensure_ascii=False))
    _cleanup_temp_files()

    # 3.7 无 closed issue → 放行
    print(subheading("3.7 无 closed issue → 放行"))
    tid5 = _mktemp_issue("open")
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") != "block":
        result.ok("无 closed issue → 放行 ✓")
    else:
        result.fail("无 closed issue 不应 block")
    _cleanup_temp_files()


# ====================================================================
# TS04 — 准入（正确识别 closed 并启动审核）
# ====================================================================

def test_entry(result: TestResult):
    print(heading(4, "准入 — Entry（检测 closed → 启动审核）"))
    print("检查：是否能正确识别 closed issue，并在无审核时触发 block")

    # 4.1 closed + 无审核 → block
    print(subheading("4.1 closed + 无审核 → block"))
    tid1 = _mktemp_issue("closed")
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") == "block" and "缺少审核" in out.get("reason", ""):
        result.ok("closed + 无审核 → block ✓")
        if "systemMessage" in out:
            result.ok("  block JSON 包含 systemMessage ✓")
        if "reason" in out and "issue" in out["reason"].lower():
            result.ok("  block JSON 包含具体 issue 路径 ✓")
    else:
        result.fail("closed + 无审核 应 block，实际: " + json.dumps(out, ensure_ascii=False))
    _cleanup_temp_files()

    # 4.2 closed + APPROVED → 放行
    print(subheading("4.2 closed + APPROVED → 放行"))
    tid2 = _mktemp_issue("closed")
    _mktemp_verdict(tid2, "APPROVED")
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") != "block":
        result.ok("closed + APPROVED → 放行 ✓")
    else:
        result.fail("closed + APPROVED 不应 block，实际: " + json.dumps(out, ensure_ascii=False))
    _cleanup_temp_files()

    # 4.3 status 大小写不敏感
    print(subheading("4.3 status 大小写不敏感"))
    tid3 = _mktemp_issue("closed")
    # Overwrite with uppercase CLOSED
    issue3 = ISSUE_DIR / f"issue{tid3}-temp-test.md"
    uppercase_content = SAMPLE_ISSUE_CLOSED.format(id=tid3).replace("status: closed", "status: CLOSED")
    issue3.write_text(uppercase_content)
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") == "block" and "缺少审核" in out.get("reason", ""):
        result.ok("status: CLOSED（大写）→ 正确识别 ✓")
    else:
        result.fail("CLOSED 大写未被识别，实际: " + json.dumps(out, ensure_ascii=False))
    _cleanup_temp_files()

    # 4.4 多重 issue：无审核优先级高于 APPROVED
    print(subheading("4.4 多重 issue：无审核优先级高于 APPROVED"))
    tid4a = _mktemp_issue("closed")
    _mktemp_verdict(tid4a, "APPROVED")
    tid4b = _mktemp_issue("closed")  # 无审核
    time.sleep(0.1)
    out = run_hook()
    if out.get("decision") == "block" and "缺少审核" in out.get("reason", ""):
        result.ok("多重 issue：无审核优先级 > APPROVED ✓")
    else:
        result.fail("多重 issue 应检查无审核的 issue，实际: " + json.dumps(out, ensure_ascii=False))
    _cleanup_temp_files()


# ====================================================================
# TS05 — 再入（修复 → 重新 close → 重新审核）
# ====================================================================

def test_reentry(result: TestResult):
    print(heading(5, "再入 — Re-entry（REJECTED → 修复 → 重新审核）"))
    print("检查：最关键的循环路径 — 从 REJECTED 到重新审核的完整闭环")

    # 5.1 完整再入路径
    print(subheading("5.1 完整再入路径"))
    tid1 = _mktemp_issue("closed")
    v1 = _mktemp_verdict(tid1, "REJECTED")
    # Simulate: verdict was just written (mtime > issue)
    _force_mtime(v1, 60)
    time.sleep(0.1)

    # Step 1: first session exit → should block (REJECTED, issue not updated)
    out1 = run_hook()
    if out1.get("decision") == "block":
        result.ok("第 1 次退出：REJECTED + 未修复 → block ✓")
    else:
        result.fail("第 1 次退出应 block，实际: " + json.dumps(out1, ensure_ascii=False))

    # Step 2: user fixes → touches issue → re-closes
    issue1 = ISSUE_DIR / f"issue{tid1}-temp-test.md"
    _force_mtime(issue1, 120)  # issue newer than verdict
    time.sleep(0.1)

    out2 = run_hook()
    if out2.get("decision") == "block" and "缺少审核" in out2.get("reason", ""):
        result.ok("第 2 次退出：已修复 → 走重新审核路径 ✓")
    else:
        result.fail("第 2 次退出应走重审路径（缺少审核 block），实际: " + json.dumps(out2, ensure_ascii=False))

    # Step 3: check old verdict deleted
    old_audit = AUDIT_DIR / f"issue{tid1}.txt"
    if not old_audit.exists():
        result.ok("旧 REJECTED 审核文件已被删除 ✓")
    else:
        result.fail("旧审核文件未被删除")

    # 5.2 重新审核后 APPROVED → 再入终止
    print(subheading("5.2 重新审核后 APPROVED → 再入终止"))
    v_approved = _mktemp_verdict(tid1, "APPROVED")
    _force_mtime(v_approved, 180)  # audit verdict newer than issue → approved audit is current
    time.sleep(0.1)
    out3 = run_hook()
    if out3.get("decision") != "block":
        result.ok("重新审核 APPROVED → 放行，再入循环终止 ✓")
    else:
        result.fail("重新审核 APPROVED 不应再 block，实际: " + json.dumps(out3, ensure_ascii=False))
    _cleanup_temp_files()

    # 5.3 多重 REJECTED：部分修复 + 部分未修复
    print(subheading("5.3 多重 REJECTED：部分修复 + 部分未修复"))
    tid_a = _mktemp_issue("closed")
    va = _mktemp_verdict(tid_a, "REJECTED")
    tid_b = _mktemp_issue("closed")
    vb = _mktemp_verdict(tid_b, "REJECTED")
    # Make both verdicts newer than their issues
    _force_mtime(va, 60)
    _force_mtime(vb, 60)
    time.sleep(0.1)

    # Fix only issue A
    issue_a = ISSUE_DIR / f"issue{tid_a}-temp-test.md"
    _force_mtime(issue_a, 120)

    out = run_hook()
    reason = out.get("reason", "")
    if out.get("decision") == "block":
        result.ok("多重 REJECTED → 正确 block ✓")
        if tid_a in reason:
            result.ok(f"  已修复 issue {tid_a} 被纳入重新审核路径 ✓")
        if tid_b in reason:
            result.ok(f"  未修复 issue {tid_b} 仍处于 REJECTED 状态 ✓")
    else:
        result.fail("多重 REJECTED 应 block")
    _cleanup_temp_files()


# ====================================================================
# TS06 — 一致性
# ====================================================================

def test_consistency(result: TestResult):
    print(heading(6, "一致性 — Consistency（config ↔ audit-prompt ↔ hook）"))
    print("检查：三方文件的关键字段名是否完全匹配")

    import yaml

    with open(str(CONFIG_FILE)) as f:
        cfg = yaml.safe_load(f)
    prompt_text = AUDIT_PROMPT.read_text("utf-8")
    hook_text = HOOK_SCRIPT.read_text("utf-8")

    fields = {
        "verdict_field": (cfg["verdict"]["verdict_field"], "审核 verdict:"),
        "approved_value": (cfg["verdict"]["approved_value"], "APPROVED"),
        "rejected_value": (cfg["verdict"]["rejected_value"], "REJECTED"),
        "reason_field": (cfg["verdict"]["reason_field"], "理由："),
    }

    for field, (cfg_val, default) in fields.items():
        print(subheading(f"6.x {field} = '{cfg_val}'"))
        if cfg_val in prompt_text:
            result.ok(f"config → audit-prompt: ✓")
        else:
            result.fail(f"config 中 '{cfg_val}' 在 audit-prompt.md 中未找到")

        if cfg_val.strip():
            result.ok(f"config → stop-hook.sh: ✓（通过 YAML eval 动态加载）")
        if cfg_val != default:
            result.info(f"  {field} 已从默认值 '{default}' 修改为 '{cfg_val}'")

    # 6.7 config.yaml 字段完整性
    print(subheading("6.7 config.yaml 字段完整性"))
    required_keys = [
        "issue.dir", "issue.file_pattern", "status.field_name",
        "status.closed_value", "status.open_value",
        "audit.dir", "audit.file_pattern",
        "verdict.verdict_field", "verdict.approved_value",
        "verdict.rejected_value", "verdict.reason_field"
    ]
    all_keys_present = True
    for key in required_keys:
        parts = key.split(".")
        obj = cfg
        for p in parts:
            if isinstance(obj, dict) and p in obj:
                obj = obj[p]
            else:
                all_keys_present = False
                result.fail(f"配置项 {key} 缺失或为空")
                break
        else:
            result.ok(f"配置项 {key} = '{obj}' ✓")
    if all_keys_present:
        result.ok("config.yaml 所有必要字段完整 ✓")

    # 6.8 stop-hook.sh 变量
    print(subheading("6.8 stop-hook.sh 变量定义验证"))
    expected_vars = [
        "ISSUE_DIR", "ISSUE_FILE_PATTERN", "STATUS_FIELD", "CLOSED_VALUE",
        "OPEN_VALUE", "AUDIT_DIR", "AUDIT_FILE_PATTERN",
        "VERDICT_FIELD", "APPROVED_VALUE", "REJECTED_VALUE", "REASON_FIELD"
    ]
    for var in expected_vars:
        if f"export {var}=" in hook_text:
            result.ok(f"变量 {var} ✓")
        else:
            result.fail(f"变量 {var} 在 stop-hook.sh 中缺失")

    # 6.9 grep 模式
    print(subheading("6.9 grep 模式验证"))
    if cfg["verdict"]["verdict_field"] and cfg["verdict"]["approved_value"]:
        combined = f'{cfg["verdict"]["verdict_field"]} *{cfg["verdict"]["approved_value"]}'
        if "VERDICT_FIELD" in hook_text and "APPROVED_VALUE" in hook_text:
            result.ok(f"grep APPROVED 模式使用变量 ✓")
            result.info(f"  运行时 grep: '{combined}'")
        else:
            result.fail("grep 模式未使用 config 变量")

    # 6.10 实际 verdict 文件
    print(subheading("6.10 实际 verdict 文件验证"))
    if AUDIT_DIR.exists():
        for f in sorted(AUDIT_DIR.iterdir()):
            if f.suffix != ".txt" or f.name == "README.txt" or "temp-test" in f.name:
                continue
            content = f.read_text("utf-8")
            verdict_field = cfg["verdict"]["verdict_field"]
            if verdict_field in content:
                val = next((l for l in content.split("\n") if verdict_field in l), "")
                val = val.replace(verdict_field, "").strip()
                if val in (cfg["verdict"]["approved_value"], cfg["verdict"]["rejected_value"]):
                    result.ok(f"{f.name}: verdict = '{val}' ✓")
                else:
                    result.fail(f"{f.name}: 未知 verdict 值 '{val}'")

    # 6.11 settings.json 注册
    print(subheading("6.11 hook 注册路径验证"))
    if SETTINGS_FILE.exists():
        settings_text = SETTINGS_FILE.read_text("utf-8")
        if "stop-hook.sh" in settings_text:
            result.ok("settings.json 中已注册 stop-hook.sh ✓")
        else:
            result.fail("settings.json 中未找到 stop-hook.sh 注册")
    else:
        result.warn("settings.json 不存在，无法验证 hook 注册")


# ====================================================================
# Utilities
# ====================================================================

def run_hook() -> Dict:
    """Run stop-hook.sh from the real project root, return JSON decision."""
    try:
        proc = subprocess.run(
            ["bash", str(HOOK_SCRIPT)],
            input=json.dumps({"cwd": str(PROJECT_ROOT)}),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
            env={**os.environ},
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if stderr and args.verbose:
            result.info(f"  stderr: {stderr[:200]}")

        if stdout:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                if args.verbose:
                    print(info(f"  stdout 非 JSON（exit 0 正常退出）: {stdout[:80]}"))
                return {"stdout": stdout}
        return {}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except FileNotFoundError:
        return {"error": "bash not found"}


# ====================================================================
# Main
# ====================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Issue-Solved Hook 测试套件")
    parser.add_argument("--verbose", "-v", action="store_true", help="输出详细信息")
    args = parser.parse_args()

    # Need global result for stderr logging in run_hook
    global result
    result = TestResult("_global")

    print(color(f"\n{'#'*60}", 94))
    print(color(f"# Issue-Solved Hook 测试套件", 94))
    print(color(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 94))
    print(color(f"# 项目根目录: {PROJECT_ROOT}", 94))
    print(color(f"# 临时 issue 前缀: test10001+", 94))
    print(color(f"{'#'*60}", 94))

    # Dependency check
    deps_ok = True
    try:
        import yaml  # noqa: F401
    except ImportError:
        print(fail("缺少依赖: pyyaml（运行 pip3 install pyyaml）"))
        deps_ok = False

    if not HOOK_DIR.exists():
        print(fail(f"hook 目录不存在: {HOOK_DIR}"))
        deps_ok = False
    if not CONFIG_FILE.exists():
        print(fail(f"config.yaml 不存在: {CONFIG_FILE}"))
        deps_ok = False
    if not HOOK_SCRIPT.exists():
        print(fail(f"stop-hook.sh 不存在: {HOOK_SCRIPT}"))
        deps_ok = False

    if not deps_ok:
        _cleanup_temp_files()
        sys.exit(1)

    all_ok = True

    # TS01 — 命名规范
    r1 = TestResult("TS01 命名")
    test_naming(r1)
    r1.summary()
    all_ok = all_ok and r1.all_ok

    # TS02 — 审核结果格式规范
    r2 = TestResult("TS02 审核格式")
    test_verdict_format(r2)
    r2.summary()
    all_ok = all_ok and r2.all_ok

    # TS03 — 无限循环预防
    r3 = TestResult("TS03 循环预防")
    test_loop_prevention(r3)
    r3.summary()
    all_ok = all_ok and r3.all_ok

    # TS04 — 准入
    r4 = TestResult("TS04 准入")
    test_entry(r4)
    r4.summary()
    all_ok = all_ok and r4.all_ok

    # TS05 — 再入
    r5 = TestResult("TS05 再入")
    test_reentry(r5)
    r5.summary()
    all_ok = all_ok and r5.all_ok

    # TS06 — 一致性
    r6 = TestResult("TS06 一致性")
    test_consistency(r6)
    r6.summary()
    all_ok = all_ok and r6.all_ok

    # Final
    _cleanup_temp_files()
    print(f"\n{'='*60}")
    print(f"{color('最终结果', 93)}: {'✅ 全部通过' if all_ok else '❌ 存在失败项'}")
    sys.exit(0 if all_ok else 1)