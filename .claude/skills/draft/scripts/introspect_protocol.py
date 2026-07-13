"""协议自省脚本：动态解析 *_protocol.py，输出 ProjectXxx 方法表。

draft 实现者不需要预先知道扩展点清单，调用本脚本读取当前协议文件即可拿到：
- 模板方法（@final / 在 _FORBIDDEN_OVERRIDES 中，不可覆盖）
- 内部方法（_ 前缀，不可覆盖）
- 必须实现的扩展点（@abstractmethod）
- 可选覆盖的扩展点（普通方法，无 _ 前缀，非 @abstractmethod，非 __init_subclass__/__init__ 等魔法方法）

输出 JSON，供 draft skill 在生成 draft 实现时按图施工。

用法（解释器取 `impl/config.yaml` 的 `python.executable`）：
    <python.executable> .claude/skills/draft/scripts/introspect_protocol.py <protocol_file>
    <python.executable> .claude/skills/draft/scripts/introspect_protocol.py impl/core/judge_protocol.py
    <python.executable> .claude/skills/draft/scripts/introspect_protocol.py impl/core/judge_protocol.py impl/core/attribute_protocol.py
"""
from __future__ import annotations
import argparse
import ast
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


MAGIC_METHODS = {
    "__init__", "__init_subclass__", "__new__", "__del__",
    "__repr__", "__str__", "__eq__", "__hash__", "__bool__",
    "__getattribute__", "__setattr__", "__delattr__", "__dir__",
    "__class__", "__subclasshook__", "__instancecheck__",
    "__abstractmethods__", "__abstractmethod__", "__dict__",
    "_abc_impl", "__module__", "__qualname__", "__doc__",
}


@dataclass
class MethodInfo:
    name: str
    kind: str  # template | internal | abstract | optional | other
    signature: str  # def foo(self, a: int) -> str
    docstring: Optional[str] = None
    forbidden: bool = False  # 是否在 _FORBIDDEN_OVERRIDES 中


@dataclass
class ClassInfo:
    name: str
    bases: list[str] = field(default_factory=list)
    is_protocol: bool = False  # _XxxProtocol
    is_project: bool = False   # ProjectXxx
    forbidden_overrides: list[str] = field(default_factory=list)
    methods: list[MethodInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "bases": self.bases,
            "is_protocol": self.is_protocol,
            "is_project": self.is_project,
            "forbidden_overrides": self.forbidden_overrides,
            "methods": [asdict(m) for m in self.methods],
        }


def _is_protocol_class(name: str) -> bool:
    return name.startswith("_") and name.endswith("Protocol")


def _is_project_class(name: str) -> bool:
    return name.startswith("Project")


def _decorator_names(decorator_list) -> list[str]:
    names: list[str] = []
    for dec in decorator_list:
        if isinstance(dec, ast.Name):
            names.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            parts = []
            cur = dec
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            names.append(".".join(reversed(parts)))
        elif isinstance(dec, ast.Call):
            fn = dec.func
            if isinstance(fn, ast.Name):
                names.append(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.append(fn.attr)
    return names


def _format_signature(node: ast.FunctionDef) -> str:
    args = node.args
    parts: list[str] = []

    if args.args:
        for a in args.args:
            parts.append(_format_arg(a))
    if args.vararg:
        parts.append("*" + _format_arg(args.vararg))
    if args.kwonlyargs:
        if not args.vararg:
            parts.append("*")
        for a in args.kwonlyargs:
            parts.append(_format_arg(a))
    if args.kwarg:
        parts.append("**" + _format_arg(args.kwarg))

    returns = ""
    if node.returns:
        returns = " -> " + ast.unparse(node.returns)

    return f"def {node.name}({', '.join(parts)}){returns}"


def _format_arg(arg: ast.arg) -> str:
    if arg.annotation:
        return f"{arg.arg}: {ast.unparse(arg.annotation)}"
    return arg.arg


def _classify_method(
    node: ast.FunctionDef,
    is_protocol: bool,
    forbidden_set: set[str],
) -> str:
    if node.name in MAGIC_METHODS:
        return "other"

    decorators = _decorator_names(node.decorator_list)
    is_abstract = "abstractmethod" in decorators
    is_final = "final" in decorators or "typing_final" in decorators

    if is_final and not node.name.startswith("_"):
        return "template"
    if node.name in forbidden_set and not node.name.startswith("_"):
        return "template"
    if is_abstract:
        return "abstract"
    if node.name.startswith("_"):
        return "internal"

    if is_protocol:
        return "optional"

    # ProjectXxx 子类中可能是父类抽象方法的具体实现，由调用方比对判定
    return "optional"


def parse_class(node: ast.ClassDef) -> ClassInfo:
    info = ClassInfo(name=node.name)
    info.bases = [ast.unparse(b) for b in node.bases]
    info.is_protocol = _is_protocol_class(node.name)
    info.is_project = _is_project_class(node.name)

    forbidden_set: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "_FORBIDDEN_OVERRIDES":
                    if isinstance(stmt.value, ast.Call):
                        for arg in stmt.value.args:
                            if isinstance(arg, ast.Set):
                                for elt in arg.elts:
                                    if isinstance(elt, ast.Constant):
                                        forbidden_set.add(str(elt.value))
                    elif isinstance(stmt.value, ast.Set):
                        for elt in stmt.value.elts:
                            if isinstance(elt, ast.Constant):
                                forbidden_set.add(str(elt.value))
    info.forbidden_overrides = sorted(forbidden_set)

    for stmt in node.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(stmt, ast.AsyncFunctionDef):
            continue
        kind = _classify_method(stmt, info.is_protocol, forbidden_set)
        if kind == "other":
            continue
        info.methods.append(MethodInfo(
            name=stmt.name,
            kind=kind,
            signature=_format_signature(stmt),
            docstring=ast.get_docstring(stmt),
            forbidden=stmt.name in forbidden_set,
        ))

    return info


def parse_protocol_file(path: Path) -> list[ClassInfo]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    classes: list[ClassInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(parse_class(node))
    return classes


def build_method_table(classes: list[ClassInfo]) -> dict:
    """合并协议层和操作层信息，输出 draft 实现者需要的方法表。

    输出结构：
    {
      "protocol_class": "_JudgeProtocol",
      "project_class": "ProjectJudge",
      "template_methods": [...],          # 不可覆盖
      "internal_methods": [...],          # _ 前缀，不可覆盖
      "abstract_methods": [...],          # @abstractmethod，draft 必须实现
      "optional_methods": [...],          # 普通扩展点，可选覆盖
      "forbidden_overrides": [...],
    }
    """
    protocol_cls = next((c for c in classes if c.is_protocol), None)
    project_cls = next((c for c in classes if c.is_project), None)

    if not protocol_cls:
        return {"error": "未找到 _XxxProtocol 类"}

    # 操作层可能被进一步子类化（如 live 的 RealServiceLive / ProvidedOutputLive），
    # 子类中标注 @abstractmethod 的方法也算 draft 必须实现。
    # 用 AST 重建继承关系，找出 ProjectXxx 的所有子类。
    project_subclasses: list[ClassInfo] = []
    if project_cls:
        project_subclasses = [
            c for c in classes
            if c is not project_cls and project_cls.name in c.bases
        ]

    # 收集子类中标注 @abstractmethod 的方法名
    subclass_abstract_names: dict[str, MethodInfo] = {}
    for sub in project_subclasses:
        for m in sub.methods:
            if m.kind == "abstract":
                subclass_abstract_names[m.name] = m

    # 合并 ProjectXxx 自身的方法 + 子类新增的方法
    project_method_names: dict[str, MethodInfo] = {}
    if project_cls:
        for m in project_cls.methods:
            project_method_names[m.name] = m
    for name, m in subclass_abstract_names.items():
        if name not in project_method_names:
            project_method_names[name] = m
        else:
            # 子类标注 @abstractmethod，提升原 kind
            project_method_names[name].kind = "abstract"

    template_methods: list[dict] = []
    internal_methods: list[dict] = []
    abstract_methods: list[dict] = []
    optional_methods: list[dict] = []

    seen: set[str] = set()
    for m in protocol_cls.methods:
        if m.name in seen:
            continue
        seen.add(m.name)
        # 如果操作层子类把某个方法标了 @abstractmethod，提升为 abstract
        effective_kind = m.kind
        if m.name in subclass_abstract_names and m.kind == "optional":
            effective_kind = "abstract"
        entry = {
            "name": m.name,
            "signature": m.signature,
            "docstring": m.docstring,
            "forbidden": m.forbidden,
        }
        if effective_kind == "template":
            template_methods.append(entry)
        elif effective_kind == "internal":
            internal_methods.append(entry)
        elif effective_kind == "abstract":
            abstract_methods.append(entry)
        elif effective_kind == "optional":
            optional_methods.append(entry)

    # 操作层新增的 @abstractmethod（如 RealServiceLive.deliver_real）
    for name, m in project_method_names.items():
        if name in seen:
            continue
        seen.add(name)
        entry = {
            "name": m.name,
            "signature": m.signature,
            "docstring": m.docstring,
            "forbidden": m.forbidden,
        }
        if m.kind == "abstract":
            abstract_methods.append(entry)
        elif m.kind == "optional":
            optional_methods.append(entry)
        elif m.kind == "template":
            template_methods.append(entry)
        elif m.kind == "internal":
            internal_methods.append(entry)

    return {
        "protocol_class": protocol_cls.name,
        "project_class": project_cls.name if project_cls else None,
        "project_subclasses": [
            {
                "name": sub.name,
                "bases": sub.bases,
                "abstract_methods": [m.name for m in sub.methods if m.kind == "abstract"],
            }
            for sub in project_subclasses
        ],
        "template_methods": template_methods,
        "internal_methods": internal_methods,
        "abstract_methods": abstract_methods,
        "optional_methods": optional_methods,
        "forbidden_overrides": protocol_cls.forbidden_overrides,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="解析 *_protocol.py 输出 draft 实现所需的方法表")
    parser.add_argument("paths", nargs="+", type=Path, help="协议文件路径")
    parser.add_argument("--pretty", action="store_true", help="格式化输出")
    args = parser.parse_args(argv)

    result: dict[str, dict] = {}
    for path in args.paths:
        if not path.exists():
            result[str(path)] = {"error": f"文件不存在: {path}"}
            continue
        classes = parse_protocol_file(path)
        result[path.stem] = build_method_table(classes)

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
