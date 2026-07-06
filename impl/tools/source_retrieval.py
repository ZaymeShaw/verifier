"""
通用 Tool 协议：源码文件检索（辅助 tool，已降级）。

⚠️ 降级说明（spec/tool2.md）：
此 tool 是"信息搬运"而非"可执行验证"，不作为归因主力。归因主力是各项目 adapter
在 get_verifiable_tools() 里提供的可执行验证 tool（execute_fn 真能跑、能产出 actual）。
本 tool 仅作为兜底辅助，供 judge/attr 在没有项目级源码验证 tool 时按需读取源码文件。

与 field_retrieval.py 平行。提供 SourceFileProvider 协议 + 默认项目级 provider，
供 attribute agent 按需读取项目 source_* 文档、原业务系统源码（application.external_repo /
endpoint_discovery.source_roots / 绝对路径 source_* 文档），避免在 user prompt 中全量加载。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, Optional, Dict, List, Any

MAX_SOURCE_FILE_BYTES = 64000
SOURCE_READABLE_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".txt", ".cfg", ".toml", ".prompt"}
DEFAULT_AGGREGATE_BYTE_BUDGET = 192_000
# 原业务系统 repo walk 上限：避免大仓 catalog 失控
MAX_CATALOG_ENTRIES = 80
MAX_WALK_DEPTH = 6
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
    默认实现 ProjectSourceFileProvider 已经覆盖 spec.documents + source_config_paths + adapter。
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


class ProjectSourceFileProvider:
    """
    默认 provider：基于 ProjectSpec.documents + adapter + source_config_paths + 原业务系统路径。

    与 attribute._load_source_code_evidence() 逻辑对齐，但延迟读取。
    新增原业务系统路径来源（project.yaml 中定位）：
    - application.external_repo     → 原业务系统仓库根目录
    - endpoint_discovery.source_roots → 原业务系统源码入口根列表
    - 绝对路径形式的 source_* 文档    → 直读（如 source_field_definitions 等）
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
        project_root = Path(self.spec.root) if self.spec.root else None
        entries: Dict[str, Dict[str, Any]] = {}

        # 1. source_config_paths from adapter
        config_paths = self.project_attribute_context.get("source_config_paths") or {}
        if isinstance(config_paths, dict):
            for key, path_str in config_paths.items():
                p = Path(path_str)
                if not p.exists() and project_root:
                    p = project_root / path_str
                if p.exists() and p.suffix in SOURCE_READABLE_SUFFIXES:
                    entries[f"config:{key}"] = {
                        "key": f"config:{key}",
                        "path": str(p),
                        "description": self._describe_business_file(p, f"adapter config: {key}"),
                    }

        # 2. project documents (source_* prefixed)
        for doc_key, doc_rel in (self.spec.documents or {}).items():
            if not doc_key.startswith("source_"):
                continue
            doc_path = Path(str(doc_rel))
            if doc_path.is_absolute():
                p = doc_path
            elif project_root:
                p = project_root / str(doc_rel)
            else:
                p = doc_path
            if not p.exists() or p.suffix not in SOURCE_READABLE_SUFFIXES:
                continue
            entries[f"project_doc:{doc_key}"] = {
                "key": f"project_doc:{doc_key}",
                "path": str(p),
                "description": self._describe_business_file(p, f"project document: {doc_key}"),
            }

        # 3. adapter.py itself
        if self.spec.adapter and project_root:
            adapter_path = project_root / self.spec.adapter
            if adapter_path.exists():
                entries[f"project_adapter:{self.spec.adapter}"] = {
                    "key": f"project_adapter:{self.spec.adapter}",
                    "path": str(adapter_path),
                    "description": "project adapter implementation (测评侧归一化层，非原业务系统根因落点)",
                }

        # 4. 原业务系统：application.external_repo (如 marketing-planning 的仓库根)
        application = dict(getattr(self.spec, "application", None) or {})
        external_repo = application.get("external_repo")
        if external_repo and Path(external_repo).exists():
            self._walk_business_repo(entries, Path(external_repo), "ext_repo", priority=True)

        # 5. 原业务系统：endpoint_discovery.source_roots (如 client_search 的 llm_client_search_0513/...)
        endpoint_cfg = dict(getattr(self.spec, "endpoint_discovery", None) or {})
        source_roots = endpoint_cfg.get("source_roots") or []
        for rel in source_roots:
            p = Path(str(rel))
            if not p.is_absolute() and project_root:
                p = (project_root / p).resolve()
            if p.exists():
                self._walk_business_repo(entries, p, "endpoint_src", priority=True)

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

        if self._bytes_returned >= self.aggregate_byte_budget:
            return (f"[budget_exhausted: aggregate byte budget {self.aggregate_byte_budget:,} "
                    f"reached across {len(self._content_cache)} file(s). Stop calling this tool "
                    f"and rely on already-read files; if attribution is still incomplete, "
                    f"finalise with incomplete_reason.]")

        catalog = self.list_files()
        entry = next((e for e in catalog if e["key"] == file_key), None)
        if entry is None:
            return None

        try:
            content = Path(entry["path"]).read_text(encoding="utf-8", errors="ignore")
            remaining = self.aggregate_byte_budget - self._bytes_returned
            truncated = content[:min(MAX_SOURCE_FILE_BYTES, remaining)]
            self._bytes_returned += len(truncated)
            self._content_cache[file_key] = truncated
            return truncated
        except Exception:
            return None


def create_source_file_search_tool(provider: SourceFileProvider):
    """
    协议通用：创建源码文件检索 tool。

    Args:
        provider: 源码文件提供者

    Returns:
        search_source_file 函数（用于 Agno Agent tools）
    """

    def search_source_file(file_key: str) -> str:
        """
        Retrieve a specific source file's content from the project.

        Use this when you need to inspect actual source code, configs, or
        prompts during attribution. The user prompt contains a
        `source_file_catalog` listing all available files and their keys.

        Args:
            file_key: The file key from source_file_catalog (e.g.,
                      "project_doc:source_enhanced_rules", "config:source_field_definitions",
                      "project_adapter:adapter.py")

        Returns:
            File content (capped at 64k chars), or "File not found" if key invalid.
        """
        try:
            content = provider.read_file(file_key)
            if content is None:
                return f"File '{file_key}' not found in catalog"
            return content
        except Exception as e:
            return f"Error retrieving file '{file_key}': {str(e)}"

    search_source_file.__name__ = "search_source_file"
    search_source_file.__doc__ = (
        "Retrieve a specific source file's content from the project source catalog. "
        "Use this when you need to inspect source code, configs, or prompts during "
        "attribution. The user prompt contains a source_file_catalog listing all "
        "available files and their keys."
    )

    return search_source_file
