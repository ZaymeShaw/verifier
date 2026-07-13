from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ProjectSpec:
    # 项目配置入口：描述一个被测项目的 adapter、文档、API 和前端扩展。
    project_id: str
    name: str
    description: str = ""
    adapter: str = "adapter.py"
    # 项目专属字段定义提供者（可选）：项目若实现了 field provider，在此声明
    # 模块路径（相对 spec.root，如 "field_provider.py"）和类名（如 "ClientSearchFieldDefinitionProvider"）。
    # judge/attribute agent 通过此声明动态加载，核心代码不硬编码 project_id 分支。
    field_provider_module: str = ""
    field_provider_class: str = ""
    capabilities: List[str] = field(default_factory=list)
    common: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)
    documents: Dict[str, str] = field(default_factory=dict)
    api: Dict[str, Any] = field(default_factory=dict)
    application: Dict[str, Any] = field(default_factory=dict)
    frontend_extensions: Dict[str, Any] = field(default_factory=dict)
    # spec/apitool_discover.md: API endpoint 自动发现配置（可选）。
    # 配置 source_roots + framework 后，启动时通用引擎扫描业务系统源码，
    # 自动构建 VerifiableTool 注册到 ToolRegistry。不配置则跳过，完全兼容现有项目。
    endpoint_discovery: Dict[str, Any] = field(default_factory=dict)
    attribute_draft: Dict[str, Any] = field(default_factory=dict)
    judge_draft: Dict[str, Any] = field(default_factory=dict)
    root: str = ""
    source_project: str = ""  # 用户侧项目目录（绝对路径），LLM 可据此查找需求材料


@dataclass
class ProjectAnalysis:
    # analysis agent 的项目理解结果：供 mock/judge/attribute/frontend 构建复用。
    project_id: str
    api: Dict[str, Any] = field(default_factory=dict)
    application: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    documents: Dict[str, str] = field(default_factory=dict)
    mock_guidance: str = ""
    evaluation_guidance: str = ""
    attribution_guidance: str = ""
    analysis_handoff: Dict[str, Any] = field(default_factory=dict)
    frontend_build_handoff: Dict[str, Any] = field(default_factory=dict)
    judge_handoff: Dict[str, Any] = field(default_factory=dict)
    attribute_handoff: Dict[str, Any] = field(default_factory=dict)
    quality_flags: List[str] = field(default_factory=list)
