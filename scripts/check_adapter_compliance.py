#!/usr/bin/env python
"""Adapter 合规检查脚本

按照 spec/adapter.md 的要求，检查项目 adapter.py 是否符合规范：
1. adapter 只做加载和暴露，不应包含业务方法
2. 应该只有访问器 + _load_* 方法
3. 不应出现业务方法名（build_*、normalize_*、get_verifiable_tools 等）
4. 多轮项目的 SessionTranslator 满足 spec/mock/protocol.md 6.2 三道约束（往返、禁 LLM、确定性）

Usage:
    python scripts/check_adapter_compliance.py [--project PROJECT_ID] [--static-only]
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Any, List, Tuple

# 允许的方法名（访问器 + _load_* + 属性）
ALLOWED_METHODS = frozenset({
    # 访问器
    'live', 'mock', 'judge', 'attribute',
    # 加载方法
    '_load_live', '_load_mock', '_load_judge', '_load_attribute',
    '_load_live_draft', '_load_attribute_draft',
    # 初始化和属性
    '__init__', '__init_subclass__',
    # 属性访问器
    'field_patterns', 'metadata_fields',
})

# 禁止的业务方法名（按 adapter.md 规范）
FORBIDDEN_BUSINESS_METHODS = frozenset({
    # Judge 相关
    'build_judge_context', 'build_intent_frame', 'normalize_judge_result',
    'reconcile_judge_result', 'pre_judge_result',
    # Attribute 相关
    'build_attribute_context', 'normalize_attribute_result',
    'apply_attribution_probes', 'attribution_probes',
    # Live 相关
    'build_request', 'extract_output', 'application_boundary',
    'call_or_prepare', 'provided_output_raw',
    # Tools 相关
    'get_verifiable_tools', 'protocol_tools', 'get_runtime_checks',
    # Mock 相关
    'build_mock_cases', 'build_mock_datasets',
    # 状态机
    'state_executors', 'trace_state_graph', 'collect_state_evidence',
    # 其他业务方法
    'to_run_trace', 'project_fields', 'build_execution_trace',
    '_blocked_attribute_result', '_patch_chinese_text_fields',
    '_target_value_unit_probe', '_find_target_nbev_wan',
})


class AdapterChecker(ast.NodeVisitor):
    """检查 adapter.py 是否符合规范"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.violations: List[Tuple[int, str, str]] = []  # (line, method_name, reason)
        self.class_name = ""

    def visit_ClassDef(self, node: ast.ClassDef):
        # 只检查 Adapter 类
        if node.name == 'Adapter':
            self.class_name = node.name
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    self._check_method(item)
        self.generic_visit(node)

    def _check_method(self, node: ast.FunctionDef):
        method_name = node.name

        # 检查是否是允许的方法
        if method_name in ALLOWED_METHODS:
            return

        # 检查是否是禁止的业务方法
        if method_name in FORBIDDEN_BUSINESS_METHODS:
            self.violations.append((
                node.lineno,
                method_name,
                "禁止的业务方法，应迁移到 project_logic.py"
            ))
            return

        # 检查是否以 _ 开头的内部方法
        if method_name.startswith('_') and not method_name.startswith('_load'):
            # 内部方法需要检查是否是业务逻辑
            # 允许的内部方法：_hashable_value, _jsonable_value 等工具方法
            allowed_internal = {
                '_hashable_value', '_jsonable_value', '_list',
                '_application_boundary_from_trace', '_reference_contract',
                '_source_config_paths', '_capability_manifest',
                '_value_mappings', '_enhanced_rules',
            }
            if method_name not in allowed_internal:
                self.violations.append((
                    node.lineno,
                    method_name,
                    "内部方法，可能是业务逻辑，建议迁移到 project_logic.py"
                ))


def _strip_volatile(value: Any, volatile: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {k: _strip_volatile(v, volatile) for k, v in value.items() if k not in volatile}
    if isinstance(value, list):
        return [_strip_volatile(item, volatile) for item in value]
    return value


def check_session_translator(project_id: str) -> List[Tuple[int, str, str]]:
    """spec/mock/protocol.md 6.2 三道自动约束：往返不变式、禁 LLM、确定性。

    实现了 SessionTranslator 的项目必须受约束。
    运行期检查，行号统一为 0。
    """
    from unittest.mock import patch

    from impl.core.project_loader import load_adapter, load_project
    from impl.core.session import SessionState, SessionTranslator, UserMessage
    from scripts.trace_canonicalize import VOLATILE_FIELDS

    spec = load_project(project_id)
    mock = load_adapter(spec).mock()
    if not isinstance(mock, SessionTranslator):
        return []

    violations: List[Tuple[int, str, str]] = []
    volatile = frozenset(VOLATILE_FIELDS.get(project_id, []))
    samples = [
        UserMessage(type="text", text="保额不低于50万的保单"),
        UserMessage(type="text", text="  带空格 和 English 123  "),
    ]
    session_id = "compliance-session"
    empty_state = SessionState(session_id=session_id, turn_index=1, transcript=[], last_request=None)

    def llm_forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("request_from_user_message must not call the LLM client")

    with patch("impl.core.llm_client.LlmClient.__init__", llm_forbidden), patch(
        "impl.core.llm_client.LlmClient.complete_json", llm_forbidden, create=True
    ), patch("impl.core.llm_client.LlmClient.complete", llm_forbidden, create=True):
        for message in samples:
            try:
                first = mock.request_from_user_message(message, empty_state)
            except AssertionError as exc:
                violations.append((0, "request_from_user_message", f"禁 LLM 约束违反：{exc}"))
                return violations
            except Exception as exc:
                violations.append((0, "request_from_user_message", f"首轮翻译失败：{exc}"))
                return violations
            back = mock.user_message_from_request(first)
            if back.identity() != message.identity():
                violations.append((0, "user_message_from_request", f"往返不变式违反：{message.identity()} → {back.identity()}"))
            again = mock.request_from_user_message(message, empty_state)
            if _strip_volatile(first, volatile) != _strip_volatile(again, volatile):
                violations.append((0, "request_from_user_message", "确定性违反：同 (message, state) 两次结果不同"))

            # 带历史的第二轮
            state = SessionState(
                session_id=session_id,
                turn_index=2,
                transcript=[
                    {"role": "user", "content": message.text, "request": first},
                    {"role": "assistant", "content": "stage=clarify", "extracted_output": {"stage": "clarify", "message": "请补充条件"}},
                ],
                last_request=first,
            )
            follow = UserMessage(type="text", text="50万以上")
            try:
                second = mock.request_from_user_message(follow, state)
            except AssertionError as exc:
                violations.append((0, "request_from_user_message", f"禁 LLM 约束违反（第二轮）：{exc}"))
                continue
            except Exception as exc:
                violations.append((0, "request_from_user_message", f"第二轮翻译失败：{exc}"))
                continue
            if mock.user_message_from_request(second).identity() != follow.identity():
                violations.append((0, "user_message_from_request", "往返不变式违反（第二轮）"))
            if _strip_volatile(second, volatile) != _strip_volatile(mock.request_from_user_message(follow, state), volatile):
                violations.append((0, "request_from_user_message", "确定性违反（第二轮）"))
            checker = getattr(getattr(mock, "live_schema", None), "check", None)
            if checker is not None and hasattr(checker, "request_errors"):
                for label, request in (("首轮", first), ("第二轮", second)):
                    errors = checker.request_errors(request)
                    if errors:
                        violations.append((0, "request_from_user_message", f"{label}请求体不符合 REQUEST_SCHEMA：{errors}"))
    return violations


def check_adapter(project_id: str) -> List[Tuple[int, str, str]]:
    """检查指定项目的 adapter.py"""
    adapter_path = Path(f"impl/projects/{project_id}/adapter.py")

    if not adapter_path.exists():
        return [(0, "", f"adapter.py 不存在: {adapter_path}")]

    with open(adapter_path) as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [(e.lineno or 0, "", f"语法错误: {e.msg}")]

    checker = AdapterChecker(project_id)
    checker.visit(tree)

    return checker.violations


def main():
    parser = argparse.ArgumentParser(description="检查 adapter 合规性")
    parser.add_argument("--project", help="检查指定项目，默认检查所有项目")
    parser.add_argument("--static-only", action="store_true", help="只做 adapter.py 静态检查，跳过 protocol.md 6.2 运行期约束")
    args = parser.parse_args()

    # 获取所有项目
    projects_dir = Path("impl/projects")
    if args.project:
        projects = [args.project]
    else:
        projects = [p.name for p in projects_dir.iterdir() if p.is_dir() and (p / "adapter.py").exists()]

    all_violations = {}
    for project_id in projects:
        violations = check_adapter(project_id)
        if not args.static_only:
            violations = violations + check_session_translator(project_id)
        if violations:
            all_violations[project_id] = violations

    # 输出结果
    if all_violations:
        print("❌ 发现违规项:\n")
        for project_id, violations in all_violations.items():
            print(f"项目 {project_id}:")
            for line, method_name, reason in violations:
                if method_name:
                    print(f"  行 {line}: {method_name} - {reason}")
                else:
                    print(f"  行 {line}: {reason}")
            print()
        sys.exit(1)
    else:
        print("✅ 所有项目 adapter 均符合规范")
        sys.exit(0)


if __name__ == "__main__":
    main()
