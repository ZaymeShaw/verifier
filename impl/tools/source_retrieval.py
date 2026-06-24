"""
通用 Tool 协议：源码文件检索。

与 field_retrieval.py 平行。提供 SourceFileProvider 协议 + 默认项目级 provider，
供 attribute agent 按需读取项目 source_* 文档（避免在 user prompt 中全量加载）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Optional, Dict, List, Any

MAX_SOURCE_FILE_BYTES = 64000
SOURCE_READABLE_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".txt", ".cfg", ".toml", ".prompt"}
DEFAULT_AGGREGATE_BYTE_BUDGET = 192_000


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
    默认 provider：基于 ProjectSpec.documents + adapter + source_config_paths。
    与 attribute._load_source_code_evidence() 逻辑对齐，但延迟读取。
    """

    def __init__(self, spec, project_attribute_context: Optional[dict] = None,
                 aggregate_byte_budget: int = DEFAULT_AGGREGATE_BYTE_BUDGET):
        self.spec = spec
        self.project_attribute_context = project_attribute_context or {}
        self.aggregate_byte_budget = aggregate_byte_budget
        self._bytes_returned = 0
        self._catalog: Optional[List[Dict[str, Any]]] = None
        self._content_cache: Dict[str, str] = {}

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
                    # Enhanced description to highlight file type
                    desc = f"adapter source config: {key}"
                    if "prompt" in p.name.lower():
                        desc = f"🔍 LLM PROMPT FILE: {key} - contains prompt templates and few-shot examples"
                    elif "config" in p.name.lower() or "constant" in p.name.lower():
                        desc = f"⚙️ CONFIG FILE: {key} - contains enums, mappings, and thresholds"
                    elif "intent" in p.name.lower() and p.suffix == ".py":
                        desc = f"📋 INTENT DEFINITION: {key} - contains intent schemas and types"
                    entries[f"config:{key}"] = {
                        "key": f"config:{key}",
                        "path": str(p),
                        "description": desc,
                    }

        # 2. project documents (source_* prefixed)
        for doc_key, doc_rel in (self.spec.documents or {}).items():
            if not doc_key.startswith("source_"):
                continue
            p = Path(project_root or ".") / str(doc_rel)
            if not p.exists() or p.suffix not in SOURCE_READABLE_SUFFIXES:
                continue
            entries[f"project_doc:{doc_key}"] = {
                "key": f"project_doc:{doc_key}",
                "path": str(p),
                "description": f"project document: {doc_key}",
            }

        # 3. adapter.py itself
        if self.spec.adapter and project_root:
            adapter_path = project_root / self.spec.adapter
            if adapter_path.exists():
                entries[f"project_adapter:{self.spec.adapter}"] = {
                    "key": f"project_adapter:{self.spec.adapter}",
                    "path": str(adapter_path),
                    "description": "project adapter implementation",
                }

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
