from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping

from ..config_schema import ConfigValueSource, EnvironmentRegistry
from ..path_contract import PathResolver, PathRoots, PathScope


@dataclass(frozen=True)
class RoleAssetMapping:
    asset_id: str
    kind: str
    enabled: bool
    roles: List[str]
    production_path: str
    candidate_path: str = ""
    replace: bool = False
    logical_production_path: str = ""
    logical_candidate_path: str = ""


@dataclass
class ProjectSpec:
    # 项目配置入口：描述一个被测项目的 adapter、文档、API 和前端扩展。
    project_id: str
    name: str
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    # Canonical schema-v1 sections. Consumers read these sections or the precise
    # accessors below; ProjectSpec does not rebuild legacy-shaped config views.
    schema_version: int = 1
    project: Dict[str, Any] = field(default_factory=dict)
    runtime: Dict[str, Any] = field(default_factory=dict)
    verifier: Dict[str, Any] = field(default_factory=dict)
    environment: EnvironmentRegistry | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    config_sources: Mapping[str, ConfigValueSource] = field(default_factory=dict)
    missing_required: tuple[str, ...] = ()
    path_roots: PathRoots | None = None
    path_resolver: PathResolver | None = None

    def require(self, field_prefix: str = "") -> None:
        missing = [
            path for path in self.missing_required
            if not field_prefix or path == field_prefix or path.startswith(f"{field_prefix}.")
        ]
        if missing:
            from ..config_schema import ConfigError

            raise ConfigError(
                f"missing required project configuration for {self.project_id}: {', '.join(missing)}"
            )

    @property
    def ready(self) -> List[str]:
        return list(self.runtime.get("ready") or [])

    @property
    def interaction_mode(self) -> str:
        interaction = self.runtime.get("interaction") or {}
        return str(interaction.get("mode") or "single_turn")

    @property
    def runtime_mode(self) -> str:
        return str(self.runtime.get("mode") or "")

    @property
    def attribution_enabled(self) -> bool:
        attribution = self.verifier.get("attribution") or {}
        return attribution.get("enabled") is True

    @property
    def local_deployment_enabled(self) -> bool:
        local = self.runtime.get("local_deployment") or {}
        return local.get("enabled") is True

    @property
    def presentation(self) -> Dict[str, Any]:
        return dict(self.verifier.get("presentation") or {})

    @property
    def document_paths(self) -> Dict[str, str]:
        resources = self.project.get("resources") or {}
        return {
            str(key): str(value)
            for key, value in (resources.get("documents") or {}).items()
        }

    @property
    def mock_cases(self) -> Dict[str, Any]:
        return dict(self.runtime.get("mock_cases") or {})

    @property
    def check_rules(self) -> Dict[str, Any]:
        return dict(self.verifier.get("check_rules") or {})

    @property
    def adapter_contract(self) -> Dict[str, Any]:
        return dict(self.runtime.get("adapter") or {})

    @property
    def application_contract(self) -> Dict[str, Any]:
        return dict(self.runtime.get("application") or {})

    @property
    def batch_persistence_contract(self) -> Dict[str, Any]:
        return dict(self.runtime.get("batch_persistence") or {})

    @property
    def judge_boundary_contract(self) -> Dict[str, Any]:
        return dict(((self.verifier.get("judge") or {}).get("boundary") or {}))

    @property
    def attribution_trace_contract(self) -> Dict[str, Any]:
        return dict(((self.verifier.get("attribution") or {}).get("trace") or {}))

    @property
    def frontend_view_contract(self) -> Dict[str, Any]:
        return dict(((self.verifier.get("presentation") or {}).get("frontend_view") or {}))

    @property
    def check_evidence_contract(self) -> Dict[str, Any]:
        return dict(((self.verifier.get("check_rules") or {}).get("evidence") or {}))

    @property
    def endpoint_discovery_config(self) -> Dict[str, Any]:
        return dict(self.verifier.get("endpoint_discovery") or {})

    @property
    def field_provider_config(self) -> Dict[str, Any]:
        return dict(self.verifier.get("field_provider") or {})

    def verifier_extra_value(self, field_id: str, default: Any = None) -> Any:
        item = (self.verifier.get("extra") or {}).get(field_id)
        if not isinstance(item, dict) or "value" not in item:
            return default
        return item["value"]

    def verifier_extra_values(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        for field_id, item in (self.verifier.get("extra") or {}).items():
            if isinstance(item, dict) and "value" in item:
                values[str(field_id)] = item["value"]
        return values

    @property
    def scenarios(self) -> List[str]:
        scenarios = self.verifier.get("scenarios") or {}
        return list(scenarios.get("allowed") or [])

    @property
    def interactive_scenarios(self) -> List[str]:
        scenarios = self.verifier.get("scenarios") or {}
        return list(scenarios.get("interactive") or [])

    @property
    def mock_scenarios(self) -> List[str]:
        mock_cases = self.runtime.get("mock_cases") or {}
        return list(mock_cases.get("default_scenarios") or [])

    @property
    def intent_labels(self) -> List[str]:
        taxonomies = self.project.get("taxonomies") or {}
        intent = taxonomies.get("intent") or {}
        return list(intent.get("labels") or [])

    @property
    def intent_descriptions(self) -> Dict[str, str]:
        taxonomies = self.project.get("taxonomies") or {}
        intent = taxonomies.get("intent") or {}
        return {
            str(key): str(value)
            for key, value in (intent.get("descriptions") or {}).items()
        }

    @property
    def judge_score_dimensions(self) -> List[str]:
        judge = self.verifier.get("judge") or {}
        return list(judge.get("score_dimensions") or [])

    @property
    def judge_error_taxonomy(self) -> List[str]:
        judge = self.verifier.get("judge") or {}
        return list(judge.get("error_taxonomy") or [])

    @property
    def core_forbidden_markers(self) -> List[str]:
        return list(self.check_rules.get("core_forbidden_markers") or [])

    @property
    def primary_stream(self) -> Dict[str, Any]:
        return dict(self.service("primary").get("stream") or {})

    @property
    def stream_event_aliases(self) -> Dict[str, List[str]]:
        return {
            str(key): [str(item) for item in value]
            for key, value in (self.primary_stream.get("event_aliases") or {}).items()
        }

    @property
    def stream_terminal_events(self) -> List[str]:
        return list(self.primary_stream.get("terminal_events") or [])

    def service(self, service_id: str = "primary") -> Dict[str, Any]:
        services = self.runtime.get("services") or {}
        if service_id == "primary":
            return dict(services.get("primary") or {})
        return dict((services.get("dependencies") or {}).get(service_id) or {})

    def require_service(self, service_id: str = "primary") -> Dict[str, Any]:
        service = self.service(service_id)
        missing = [
            field_name
            for field_name in ("base_url", "endpoint", "method", "timeout_seconds")
            if service.get(field_name) in (None, "")
        ]
        if missing:
            from ..config_schema import ConfigError

            raise ConfigError(
                f"project {self.project_id} service {service_id} is missing configured fields: {', '.join(missing)}"
            )
        return service

    def role_draft(self, role: str) -> Dict[str, Any]:
        role_config = (self.verifier.get("roles") or {}).get(role) or {}
        return dict(role_config.get("draft") or {})

    def asset_mappings(self) -> List[RoleAssetMapping]:
        return [
            RoleAssetMapping(
                asset_id=str(item["asset_id"]),
                kind=str(item["kind"]),
                enabled=item.get("enabled") is True,
                roles=[str(role) for role in item.get("roles") or []],
                production_path=str(item["production_path"]),
                candidate_path=str(item.get("candidate_path") or ""),
                replace=item.get("replace") is True,
                logical_production_path=str(item["production_path"]),
                logical_candidate_path=str(item.get("candidate_path") or ""),
            )
            for item in self.verifier.get("assets") or []
        ]

    def role_tool_call_limit(self, role: str) -> int | None:
        role_config = (self.verifier.get("roles") or {}).get(role) or {}
        draft = role_config.get("draft") or {}
        if draft.get("enabled") is True and draft.get("tool_call_limit") is not None:
            return int(draft["tool_call_limit"])
        if role_config.get("tool_call_limit") is not None:
            return int(role_config["tool_call_limit"])
        return None

    def source_path(self, path_id: str = "") -> str:
        source = ((self.project.get("resources") or {}).get("source") or {})
        if not path_id:
            return str(self.source_root_path())
        logical = str((source.get("paths") or {}).get(path_id) or "")
        if not logical:
            return ""
        if self.path_resolver is None:
            raise RuntimeError(f"project {self.project_id} has no PathResolver")
        return str(
            self.path_resolver.resolve(
                logical,
                field_path=f"project.resources.source.paths.{path_id}",
                allowed_scopes={PathScope.BUSINESS_SOURCE},
            ).physical
        )

    def source_root_path(self, *, must_exist: bool = True) -> Path:
        if self.path_resolver is None:
            raise RuntimeError(f"project {self.project_id} has no PathResolver")
        return self.resolve_path(
            "business://.",
            field_path="project.resources.source.repository",
            allowed_scopes={PathScope.BUSINESS_SOURCE},
            expected_type="directory",
            must_exist=must_exist,
        )

    def project_package_path(
        self,
        location: str = ".",
        *,
        field_path: str = "project.package",
        expected_type: str = "any",
        must_exist: bool = True,
    ) -> Path:
        normalized = str(location or ".").lstrip("/")
        if self.path_resolver is None:
            raise RuntimeError(f"project {self.project_id} has no PathResolver")
        return self.resolve_path(
            f"project://{normalized}",
            field_path=field_path,
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            expected_type=expected_type,
            must_exist=must_exist,
        )

    @property
    def has_business_source(self) -> bool:
        return bool(self.path_roots and self.path_roots.business_source is not None)

    def verifier_root_path(self) -> Path:
        if self.path_roots is None:
            raise RuntimeError(f"project {self.project_id} has no PathRoots")
        return self.path_roots.root_for(
            PathScope.VERIFIER_REPO,
            field_path="runtime.paths.verifier_repo",
        )

    def artifact_package_path(
        self,
        location: str = ".",
        *,
        field_path: str = "runtime.paths.artifact_package",
        expected_type: str = "any",
        must_exist: bool = True,
    ) -> Path:
        normalized = str(location or ".").lstrip("/")
        return self.resolve_path(
            f"artifact://{normalized}",
            field_path=field_path,
            allowed_scopes={PathScope.ARTIFACT_PACKAGE},
            expected_type=expected_type,
            must_exist=must_exist,
        )

    def adapter_path(self) -> Path:
        return self.project_package_path(
            "adapter.py",
            field_path="verifier.adapter",
            expected_type="file",
        )

    def local_start_script_path(self) -> Path:
        return self.project_package_path(
            "scripts/start.sh",
            field_path="runtime.local_deployment.start_script",
            expected_type="executable",
        )

    def endpoint_manifest_path(self, *, must_exist: bool = True) -> Path:
        return self.project_package_path(
            "tools/api_discover/_manifest.json",
            field_path="endpoint_discovery.manifest",
            expected_type="file" if must_exist else "any",
            must_exist=must_exist,
        )

    def investigation_validation_receipt_path(
        self, role: str, *, must_exist: bool = True
    ) -> Path:
        return self.project_package_path(
            f"draft/.state/{role}/investigation-validation.json",
            field_path=f"investigation.{role}.validation_receipt",
            expected_type="file" if must_exist else "any",
            must_exist=must_exist,
        )

    def resolve_path(
        self,
        logical: str,
        *,
        field_path: str,
        allowed_scopes: set[PathScope],
        expected_type: str = "any",
        must_exist: bool = True,
    ) -> Path:
        if self.path_resolver is None:
            raise RuntimeError(f"project {self.project_id} has no PathResolver")
        return self.path_resolver.resolve(
            logical,
            field_path=field_path,
            allowed_scopes=allowed_scopes,
            expected_type=expected_type,
            must_exist=must_exist,
        ).physical

    def project_document_path(self, key: str, *, must_exist: bool = True) -> Path | None:
        logical = str(
            ((((self.project.get("resources") or {}).get("documents") or {}).get(key)) or "")
        )
        if not logical:
            return None
        return self.resolve_path(
            logical,
            field_path=f"project.resources.documents.{key}",
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            expected_type="file",
            must_exist=must_exist,
        )

    def role_draft_path(self, role: str, *, must_exist: bool = True) -> Path | None:
        logical = str((((self.verifier.get("roles") or {}).get(role) or {}).get("draft") or {}).get("module") or "")
        if not logical:
            return None
        return self.resolve_path(
            logical,
            field_path=f"verifier.roles.{role}.draft.module",
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            expected_type="file",
            must_exist=must_exist,
        )

    def field_provider_path(self) -> Path | None:
        logical = str(((self.verifier.get("field_provider") or {}).get("module") or ""))
        if not logical:
            return None
        return self.resolve_path(
            logical,
            field_path="verifier.field_provider.module",
            allowed_scopes={PathScope.PROJECT_PACKAGE},
            expected_type="file",
        )

    def endpoint_source_paths(self) -> List[Path]:
        logical_roots = list((self.verifier.get("endpoint_discovery") or {}).get("source_roots") or [])
        return [
            self.resolve_path(
                str(logical),
                field_path=f"verifier.endpoint_discovery.source_roots[{index}]",
                allowed_scopes={PathScope.BUSINESS_SOURCE},
                expected_type="directory",
            )
            for index, logical in enumerate(logical_roots)
        ]


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
