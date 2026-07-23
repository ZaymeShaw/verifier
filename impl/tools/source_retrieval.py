"""
通用 Tool 协议：源码函数/符号检索。

本模块提供 SourceFileProvider 协议 + 默认项目级 provider，并输出统一的 VerifiableTool：
- source_list_symbols：列出 Python 文件中的函数/方法清单
- source_read_functions：按 qualified_name 读取函数片段，或读取非 Python 文档/配置文本

整文件读取仅作为非 Python 文件或函数片段不足时的兜底，避免在 user prompt 中全量加载源码。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Protocol, Optional, Dict, List, Any

from impl.tools.protocol import ToolResult, VerifiableTool

MAX_SOURCE_FILE_BYTES = 64000
MAX_SOURCE_FUNCTION_BYTES = 24_000
MAX_SOURCE_FULL_FILE_BYTES = 24_000
SOURCE_READABLE_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".txt", ".cfg", ".toml", ".prompt"}
DEFAULT_AGGREGATE_BYTE_BUDGET = 192_000
# 原业务系统 repo walk 上限：避免大仓 catalog 失控
MAX_CATALOG_ENTRIES = 80
MAX_WALK_DEPTH = 6
MAX_SEARCH_RESULTS = 40
MAX_SEARCH_LINE_CHARS = 500
MAX_SEARCH_CONTEXT_LINES = 20
# 原业务系统 walk 排除目录
EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git", "venv", ".venv", "env", "dist", "build", "logs", "docs", "test", "tests", "migrations", ".claude", "docs_BAK", "archive", "backup", "fixtures", "data", "assets", "static", ".mypy_cache", ".pytest_cache", ".ruff_cache", "egg-info", ".eggs", "tmp", "temp", "output", "result", "checkpoint", "bin", "obj", "target", "vendor", "third_party", "thirdparty"}

# 原业务系统关键词文件：优先纳入 catalog，加重点描述
BUSINESS_KEYWORD_DESCRIPTIONS = {
    "prompt": "🔍 BUSINESS PROMPT FILE - contains prompt templates, few-shot examples, and system instructions",
    "intent": "📋 BUSINESS INTENT DEFINITION - contains intent schemas, types, and routing rules",
    "config": "⚙️ BUSINESS CONFIG FILE - contains enums, mappings, constants, and thresholds",
    "constant": "⚙️ BUSINESS CONSTANT FILE - contains enums, mappings, and value definitions",
    "field_definition": "📐 BUSINESS FIELD DEFINITION - contains field schemas, operators, and value types",
    "field_enums": "📐 BUSINESS FIELD ENUMS - contains valid enum values for search/client fields",
    "value_mapping": "📐 BUSINESS VALUE MAPPING - contains field value normalization rules",
    "enhanced_rule": "📐 BUSINESS ENHANCED RULES - contains field derivation and enhancement logic",
    "enum": "⚙️ BUSINESS ENUM DEFINITION - contains valid value enumerations",
    "mapping": "📐 BUSINESS MAPPING - contains field/value mapping rules",
    "route": "🌐 BUSINESS API ROUTE - contains endpoint definitions and request handlers",
    "template": "🔍 BUSINESS TEMPLATE - contains output templates and formatting rules",
    "agent": "🤖 BUSINESS AGENT - contains agent logic, orchestration, and decision flow",
    "orchestrat": "🤖 BUSINESS ORCHESTRATOR - contains multi-agent orchestration and routing",
    "dispatch": "🤖 BUSINESS DISPATCHER - contains intent dispatch and routing logic",
    "planning": "📋 BUSINESS PLANNING - contains planning logic, stage dispatch, and card generation",
    "sse": "📡 BUSINESS SSE HANDLER - contains streaming event generation and protocol handling",
    "session": "🔄 BUSINESS SESSION - contains session management, merge, and isolation logic",
    "clarify": "🔄 BUSINESS CLARIFICATION - contains multi-turn field clarification logic",
    "search": "🔎 BUSINESS SEARCH - contains search query construction and result parsing",
    "query": "🔎 BUSINESS QUERY - contains query parsing, normalization, and rewriting",
    "parse": "🔎 BUSINESS PARSER - contains input parsing and normalization logic",
    "filter": "🔎 BUSINESS FILTER - contains search filter construction and validation",
    "condition": "🔎 BUSINESS CONDITION - contains search condition building and optimization",
    "evaluate": "📊 BUSINESS EVALUATOR - contains output evaluation and scoring logic",
    "judge": "📊 BUSINESS JUDGE - contains judgment and verification logic",
}
# 原业务系统高优先级关键词：命中这些目录名时优先 walk 更深
BUSINESS_PRIORITY_DIRS = {"src", "main", "python", "app", "api", "service", "core", "handler", "agent", "prompt", "config", "domain", "logic", "engine", "parser", "planner", "orchestrator", "dispatcher", "router", "server", "application", "business", "model", "evaluation", "search", "query", "filter", "session", "intent", "planning", "clarification", "sse", "stream", "chunk", "dispatch", "workflow", "pipeline", "stage", "run", "executor", "strategy", "decision", "generator", "assembler", "normalizer", "extractor", "validator", "resolver", "matcher", "ranker", "scorer"}


class SourceFileProvider(Protocol):
    """
    协议：源码文件提供者。

    每个项目可以实现自己的 provider，提供文件清单和按需读取。
    默认实现 ProjectSourceFileProvider 已经覆盖规范 documents + source_config_paths + adapter。
    """

    def list_files(self) -> List[Dict[str, Any]]:
        """
        返回可用文件清单（不包含文件内容）。

        每项包含：
        - key: 文件唯一 key（用于 read_file 调用）
        - path: 实际文件路径
        - size_chars: 文件内容字符数（受 MAX_SOURCE_FILE_BYTES 限制）
        - description: 一句话描述（可选）
        """
        ...

    def read_file(self, file_key: str) -> Optional[str]:
        """
        按需读取指定文件内容（受 MAX_SOURCE_FILE_BYTES 限制）。

        Args:
            file_key: list_files() 返回的 key

        Returns:
            文件内容字符串；key 不存在则返回 None。
        """
        ...

    def read_functions(self, file_key: str, function_names: List[str]) -> Optional[str]:
        """
        按需读取指定 Python 文件中的若干函数/方法源码片段。

        Args:
            file_key: list_files() 返回的 key
            function_names: 需要读取的函数名，支持 Class.method 或 method/function

        Returns:
            匹配函数源码片段；key 不存在则返回 None。
        """
        ...

    def list_symbols(self, file_key: str) -> Optional[List[Dict[str, Any]]]:
        """
        列出指定 Python 文件中的函数/方法符号摘要。

        Args:
            file_key: list_files() 返回的 key

        Returns:
            符号摘要列表；key 不存在则返回 None。
        """
        ...


class ProjectSourceFileProvider:
    """
    默认 provider：基于 ProjectSpec 规范资源访问器、adapter 和项目 source_config_paths。

    与 attribute._load_source_code_evidence() 逻辑对齐，但延迟读取。
    业务源码来源由 project.yaml 的规范字段及逻辑路径确定：
    - project.resources.source.repository → 原业务系统仓库根目录
    - verifier.endpoint_discovery.source_roots → 原业务系统源码入口根列表
    - project.resources.documents → project:// 范围内的项目文档
    """

    def __init__(self, spec, project_attribute_context: Optional[dict] = None,
                 aggregate_byte_budget: int = DEFAULT_AGGREGATE_BYTE_BUDGET):
        self.spec = spec
        self.project_attribute_context = project_attribute_context or {}
        self.aggregate_byte_budget = aggregate_byte_budget
        self._bytes_returned = 0
        self._catalog: Optional[List[Dict[str, Any]]] = None
        self._content_cache: Dict[str, str] = {}
        self._walk_count = 0  # 计数 walk 纳入的文件，防 catalog 溢出

    def _build_catalog(self) -> List[Dict[str, Any]]:
        package_accessor = getattr(self.spec, "project_package_path", None)
        source_accessor = getattr(self.spec, "source_root_path", None)
        endpoint_accessor = getattr(self.spec, "endpoint_source_paths", None)
        document_accessor = getattr(self.spec, "project_document_path", None)
        if not all(callable(item) for item in (
            package_accessor,
            source_accessor,
            endpoint_accessor,
            document_accessor,
        )):
            raise RuntimeError("source retrieval requires resolver-backed ProjectSpec accessors")
        entries: Dict[str, Dict[str, Any]] = {}
        walked_business_roots: set[Path] = set()

        def walk_business_root(path: Path, prefix: str) -> None:
            """Expose one physical business root once, even when YAML aliases it."""
            resolved = path.resolve()
            if resolved in walked_business_roots:
                return
            walked_business_roots.add(resolved)
            self._walk_business_repo(entries, resolved, prefix, priority=True)

        # 1. source_config_paths from adapter
        config_paths = self.project_attribute_context.get("source_config_paths") or {}
        if isinstance(config_paths, dict):
            for key, path_str in config_paths.items():
                p = Path(path_str)
                if not p.is_absolute():
                    p = package_accessor(
                        str(path_str),
                        field_path=f"attribute.source_config_paths.{key}",
                        expected_type="any",
                        must_exist=False,
                    )
                if p.exists() and p.suffix in SOURCE_READABLE_SUFFIXES:
                    entries[f"config:{key}"] = {
                        "key": f"config:{key}",
                        "path": str(p),
                        "description": self._describe_business_file(p, f"adapter config: {key}"),
                    }

        # 2. project documents (source_* prefixed)
        for doc_key in self.spec.document_paths:
            if not doc_key.startswith("source_"):
                continue
            p = document_accessor(doc_key, must_exist=False)
            if p is None:
                continue
            if not p.exists() or p.suffix not in SOURCE_READABLE_SUFFIXES:
                continue
            entries[f"project_doc:{doc_key}"] = {
                "key": f"project_doc:{doc_key}",
                "path": str(p),
                "description": self._describe_business_file(p, f"project document: {doc_key}"),
            }

        # 3. adapter.py itself
        adapter_path = package_accessor(
            "adapter.py",
            field_path="verifier.adapter",
            expected_type="file",
            must_exist=False,
        )
        if adapter_path.exists():
            entries["project_adapter:adapter.py"] = {
                "key": "project_adapter:adapter.py",
                "path": str(adapter_path),
                "description": "project adapter implementation (测评侧归一化层，非原业务系统根因落点)",
            }

        # 4. 业务源码的唯一运行时入口来自 ProjectSpec 的 canonical source。
        source_project = None
        if getattr(self.spec, "has_business_source", False):
            source_project = source_accessor()
            if source_project.exists():
                walk_business_root(source_project, "source_project")

        # 5. 原业务系统：endpoint_discovery.source_roots (如 client_search 的 llm_client_search_0513/...)
        for p in endpoint_accessor():
            if p.exists():
                walk_business_root(p, "endpoint_src")

        # Compute size_chars for each entry
        catalog = []
        for entry in entries.values():
            try:
                size = Path(entry["path"]).stat().st_size
                entry["size_chars"] = min(size, MAX_SOURCE_FILE_BYTES)
            except Exception:
                entry["size_chars"] = 0
            catalog.append(entry)

        return catalog

    @staticmethod
    def _describe_business_file(p: Path, fallback: str) -> str:
        """根据文件名关键词生成业务化描述，命中原业务系统关键词则加重点标记。"""
        name_lower = p.name.lower()
        for keyword, desc in BUSINESS_KEYWORD_DESCRIPTIONS.items():
            if keyword in name_lower:
                return desc
        return fallback

    def _walk_business_repo(self, entries: dict, root: Path, prefix: str, priority: bool = False, depth: int = 0):
        """受控 walk 原业务系统仓库，将可读源码文件纳入 catalog。

        Args:
            entries: 累积的 catalog dict
            root: walk 根目录
            prefix: 文件 key 前缀 (如 "ext_repo" / "endpoint_src")
            priority: 是否优先排序（priority 目录先 walk，非 priority 后 walk）
            depth: 当前递归深度
        """
        if depth > MAX_WALK_DEPTH or self._walk_count >= MAX_CATALOG_ENTRIES:
            return
        try:
            items = sorted(os.scandir(root), key=lambda x: (not x.is_dir(), x.name))
        except (PermissionError, OSError):
            return

        dirs = []
        files = []
        for item in items:
            if item.is_dir():
                if item.name.startswith(".") or item.name in EXCLUDE_DIRS:
                    continue
                dirs.append(item)
            elif item.is_file():
                files.append(item)

        # 优先 walk 业务关键词目录
        priority_dirs = [d for d in dirs if d.name in BUSINESS_PRIORITY_DIRS]
        other_dirs = [d for d in dirs if d.name not in BUSINESS_PRIORITY_DIRS]

        # 先收文件
        for f in files:
            if self._walk_count >= MAX_CATALOG_ENTRIES:
                return
            if not f.name.endswith(tuple(SOURCE_READABLE_SUFFIXES)):
                continue
            if f.name.startswith("."):
                continue
            # prefix 已包含递归目录，不能只使用文件名，否则同名源码会静默覆盖。
            key = f"{prefix}:{f.name}"
            if key in entries:
                continue
            entries[key] = {
                "key": key,
                "path": f.path,
                "description": self._describe_business_file(Path(f.path), f"{prefix} source file: {f.name}"),
            }
            self._walk_count += 1

        # 再递归子目录：优先 walk 业务关键词目录
        walk_order = (priority_dirs + other_dirs) if priority else (other_dirs + priority_dirs)
        for d in walk_order:
            if self._walk_count >= MAX_CATALOG_ENTRIES:
                return
            self._walk_business_repo(entries, Path(d.path), f"{prefix}/{d.name}", priority, depth + 1)

    def list_files(self) -> List[Dict[str, Any]]:
        if self._catalog is None:
            self._catalog = self._build_catalog()
        return self._catalog

    def read_file(self, file_key: str) -> Optional[str]:
        if file_key in self._content_cache:
            return self._content_cache[file_key]

        budget_error = self._reserve_budget(0)
        if budget_error:
            return budget_error

        entry = self._catalog_entry(file_key)
        if entry is None:
            return None

        try:
            path = Path(entry["path"])
            file_bytes = path.stat().st_size
            if file_bytes > MAX_SOURCE_FULL_FILE_BYTES:
                return (
                    f"[full_file_too_large: '{file_key}' is {file_bytes} bytes, above the "
                    f"{MAX_SOURCE_FULL_FILE_BYTES}-byte bounded evidence limit; use "
                    "source.search_text with an exact query, small max_results and context_lines.]"
                )
            content = path.read_text(encoding="utf-8", errors="ignore")
            return self._cache_content(file_key, content, MAX_SOURCE_FILE_BYTES)
        except Exception:
            return None

    def read_functions(self, file_key: str, function_names: List[str]) -> Optional[str]:
        entry = self._catalog_entry(file_key)
        if entry is None:
            return None

        path = Path(entry["path"])
        if path.suffix != ".py":
            return f"[function_extract_unsupported: '{file_key}' is not a Python source file; use full_file=true only if necessary.]"

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            snippets = extract_python_functions(content, function_names)
        except Exception as e:
            return f"[function_extract_error: {str(e)}]"

        if not snippets:
            requested = ", ".join(function_names)
            return f"[functions_not_found: {requested}]"

        cache_key = f"{file_key}::functions::{','.join(function_names)}"
        return self._cache_content(cache_key, "\n\n".join(snippets), MAX_SOURCE_FUNCTION_BYTES)

    def list_symbols(self, file_key: str) -> Optional[List[Dict[str, Any]]]:
        entry = self._catalog_entry(file_key)
        if entry is None:
            return None

        path = Path(entry["path"])
        if path.suffix != ".py":
            return []

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            return extract_python_symbols(content)
        except Exception:
            return []

    def search_text(
        self,
        query: str,
        *,
        file_keys: Optional[List[str]] = None,
        max_results: int = MAX_SEARCH_RESULTS,
        context_lines: int = 0,
    ) -> List[Dict[str, Any]]:
        """Search authorized catalog files and return bounded, line-addressable matches."""
        needle = str(query or "").strip()
        if not needle:
            return []
        requested = set(str(item) for item in (file_keys or []) if str(item))
        limit = max(1, min(int(max_results or MAX_SEARCH_RESULTS), MAX_SEARCH_RESULTS))
        context = max(0, min(int(context_lines or 0), MAX_SEARCH_CONTEXT_LINES))
        matches: List[Dict[str, Any]] = []
        for entry in self.list_files():
            if requested and entry["key"] not in requested:
                continue
            try:
                path = Path(entry["path"])
                content = path.read_text(encoding="utf-8", errors="ignore")[:MAX_SOURCE_FILE_BYTES]
            except Exception:
                continue
            lines = content.splitlines()
            for line_number, line in enumerate(lines, start=1):
                if needle.casefold() not in line.casefold():
                    continue
                start_line = max(1, line_number - context)
                end_line = min(len(lines), line_number + context)
                excerpt = "\n".join(lines[start_line - 1:end_line])
                matches.append({
                    "file_key": entry["key"],
                    "line": line_number,
                    "start_line": start_line,
                    "end_line": end_line,
                    "text": excerpt[:MAX_SEARCH_LINE_CHARS * max(1, 1 + context * 2)],
                })
                if len(matches) >= limit:
                    return matches
        return matches

    def _catalog_entry(self, file_key: str) -> Optional[Dict[str, Any]]:
        catalog = self.list_files()
        return next((e for e in catalog if e["key"] == file_key), None)

    def _reserve_budget(self, requested_bytes: int) -> Optional[str]:
        if self._bytes_returned + requested_bytes <= self.aggregate_byte_budget:
            return None
        return (f"[budget_exhausted: aggregate byte budget {self.aggregate_byte_budget:,} "
                f"reached across {len(self._content_cache)} file(s). Stop calling this tool "
                f"and rely on already-read files; if attribution is still incomplete, "
                f"finalise with incomplete_reason.]")

    def _cache_content(self, cache_key: str, content: str, byte_limit: int) -> str:
        remaining = self.aggregate_byte_budget - self._bytes_returned
        truncated = content[:min(byte_limit, remaining)]
        budget_error = self._reserve_budget(len(truncated))
        if budget_error:
            return budget_error
        self._bytes_returned += len(truncated)
        self._content_cache[cache_key] = truncated
        return truncated


def extract_python_functions(content: str, function_names: List[str]) -> List[str]:
    requested = {name.strip() for name in function_names if name and name.strip()}
    if not requested:
        return []

    lines = content.splitlines()
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    snippets: List[str] = []
    parents = _python_parent_map(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        qualified_name = _qualified_function_name(node, parents)
        if node.name not in requested and qualified_name not in requested:
            continue
        end_lineno = getattr(node, "end_lineno", node.lineno)
        header = f"# {qualified_name} (lines {node.lineno}-{end_lineno})"
        snippet = "\n".join(lines[node.lineno - 1:end_lineno])
        snippets.append(f"{header}\n{snippet}")
    return snippets


def extract_python_symbols(content: str) -> List[Dict[str, Any]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    parents = _python_parent_map(tree)
    symbols: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node) or ""
        end_lineno = getattr(node, "end_lineno", node.lineno)
        symbols.append({
            "name": node.name,
            "qualified_name": _qualified_function_name(node, parents),
            "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
            "line": node.lineno,
            "end_line": end_lineno,
            "args": [arg.arg for arg in node.args.args],
            "doc": doc.splitlines()[0][:200] if doc else "",
        })
    return sorted(symbols, key=lambda item: item["line"])


def _python_parent_map(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    parents: Dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _qualified_function_name(target: ast.AST, parents: Dict[ast.AST, ast.AST]) -> str:
    class_names = []
    node = parents.get(target)
    while node is not None:
        if isinstance(node, ast.ClassDef):
            class_names.append(node.name)
        node = parents.get(node)
    if isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef)) and class_names:
        return f"{'.'.join(reversed(class_names))}.{target.name}"
    return getattr(target, "name", "")


def create_source_retrieval_tools(provider: SourceFileProvider) -> List[VerifiableTool]:
    def list_source_symbols(**kwargs: Any) -> ToolResult:
        file_key = str(kwargs.get("file_key") or "")
        symbols = provider.list_symbols(file_key)
        if symbols is None:
            return ToolResult(
                tool_id="source.list_symbols",
                tool_type="source_retrieval",
                status="failed",
                error=f"file not found in catalog: {file_key}",
            )
        return ToolResult(
            tool_id="source.list_symbols",
            tool_type="source_retrieval",
            status="succeeded" if symbols else "inconclusive",
            actual={"file_key": file_key, "symbols": symbols},
            evidence=f"listed {len(symbols)} Python function symbols from {file_key}",
        )

    def read_source_functions(**kwargs: Any) -> ToolResult:
        file_key = str(kwargs.get("file_key") or "")
        function_names = kwargs.get("function_names") or []
        full_file = bool(kwargs.get("full_file") or False)
        if function_names:
            content = provider.read_functions(file_key, [str(name) for name in function_names])
        elif full_file:
            content = provider.read_file(file_key)
        else:
            return ToolResult(
                tool_id="source.read_functions",
                tool_type="source_retrieval",
                status="inconclusive",
                error="function_names is required unless full_file=true",
                evidence="function_names is empty and full_file is false; no source text was retrieved",
            )
        if content is None:
            return ToolResult(
                tool_id="source.read_functions",
                tool_type="source_retrieval",
                status="failed",
                error=f"file not found in catalog: {file_key}",
            )
        status = "inconclusive" if content.startswith("[") else "succeeded"
        return ToolResult(
            tool_id="source.read_functions",
            tool_type="source_retrieval",
            status=status,
            actual={"file_key": file_key, "content": content},
            evidence=f"retrieved source snippets from {file_key}",
        )

    list_source_symbols.__name__ = "source_list_symbols"
    read_source_functions.__name__ = "source_read_functions"
    return [
        VerifiableTool(
            tool_id="source.list_symbols",
            description="列出指定 Python 源文件中的函数/方法符号摘要。输入 source_file_catalog 中的 file_key，输出 name、qualified_name、kind、line/end_line、args 和 doc 摘要；该工具只提供源码结构索引，不验证运行时行为、业务配置或根因结论。",
            applicable_scenario="attr",
            parameters={
                "type": "object",
                "properties": {
                    "file_key": {"type": "string", "description": "必填。source_file_catalog 中的文件 key，必须原样使用 catalog 提供的 key，不要传文件路径；catalog 条目的来源和描述决定该文件能提供哪类证据。"},
                },
                "required": ["file_key"],
            },
            execute_fn=list_source_symbols,
        ),
        VerifiableTool(
            tool_id="source.read_functions",
            description=f"读取指定源码文件的函数/方法片段，或在文件类型不支持函数抽取时读取不超过 {MAX_SOURCE_FULL_FILE_BYTES} 字节的小文件。更大的配置、文档或历史 probe 必须使用 source.search_text 获取有界片段。输入 source_file_catalog 的 file_key、可选 function_names 或 full_file，输出源码/文档文本片段；该工具提供实现机制证据，不执行系统、不验证当前行为，也不替代 API、字段能力或规则类工具的证据。",
            applicable_scenario="attr",
            parameters={
                "type": "object",
                "properties": {
                    "file_key": {"type": "string", "description": "必填。source_file_catalog 中的文件 key，必须原样使用 catalog 提供的 key，不要传文件路径；catalog 条目的来源和描述决定该文件能提供哪类证据。"},
                    "function_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要读取的函数/方法名列表，支持普通函数名或 qualified_name（如 ClassName.method_name）；名称必须来自已有符号信息、文件内容线索或当前任务证据，不要凭空猜测。",
                    },
                    "full_file": {"type": "boolean", "description": f"是否读取整文件内容。默认 false；仅用于不超过 {MAX_SOURCE_FULL_FILE_BYTES} 字节、且无法用函数或有界文本搜索表达的小文件。大文件会被拒绝。"},
                },
                "required": ["file_key"],
            },
            execute_fn=read_source_functions,
        ),
    ]


def create_source_search_tools(provider: ProjectSourceFileProvider) -> List[VerifiableTool]:
    """Attribute-only discovery tool layered on the shared authorized source provider."""

    def search_source_text(**kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        file_keys = kwargs.get("file_keys") or []
        if not query:
            return ToolResult(
                tool_id="source.search_text",
                tool_type="source_retrieval",
                status="failed",
                error="query is required",
            )
        matches = provider.search_text(
            query,
            file_keys=[str(item) for item in file_keys],
            max_results=int(kwargs.get("max_results") or MAX_SEARCH_RESULTS),
            context_lines=int(kwargs.get("context_lines") or 0),
        )
        return ToolResult(
            tool_id="source.search_text",
            tool_type="source_retrieval",
            status="succeeded" if matches else "inconclusive",
            actual={"query": query, "matches": matches},
            evidence=f"searched authorized source catalog for {query!r}; found {len(matches)} matches",
            missing_evidence=[] if matches else ["no authorized catalog line contains the requested text"],
        )

    search_source_text.__name__ = "source_search_text"
    return [VerifiableTool(
        tool_id="source.search_text",
        description="在 ProjectSpec 授权的业务源码、配置和文档 catalog 内搜索原始文本，返回 file_key、行号和可选的命中附近有界原文。配置/文档应优先用精确 query、较小 max_results 和 context_lines 获取最小充分片段，避免为了查看相邻字段而读取整文件。它用于发现未预先登记的技术位置；匹配内容只能证明文本存在，不能单独证明运行时根因。",
        applicable_scenario="attr",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "必填。要在授权文件中查找的精确原文、标识符、stage、字段或配置值；使用当前 case 证据中的具体词，不要用宽泛主题。"},
                "file_keys": {"type": "array", "items": {"type": "string"}, "description": "可选。仅搜索 source_file_catalog 中这些精确 file_key；留空时搜索整个授权 catalog。"},
                "max_results": {"type": "integer", "description": f"可选。最多返回的匹配行，公共上限为 {MAX_SEARCH_RESULTS}。"},
                "context_lines": {"type": "integer", "description": f"可选。每个命中前后附带的原文行数，默认 0，上限 {MAX_SEARCH_CONTEXT_LINES}。读取配置块时应配合精确 query 和较小 max_results 使用。"},
            },
            "required": ["query"],
        },
        execute_fn=search_source_text,
    )]
