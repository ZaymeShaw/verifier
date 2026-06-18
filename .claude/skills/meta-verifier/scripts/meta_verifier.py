from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List
import os
import re
import shutil
import subprocess
import time
import uuid


class RouteType(str, Enum):
    PROJECT_EXPLORATION = "project_exploration"
    TARGETED_VERIFICATION = "targeted_verification"
    ISSUE_REPRODUCTION = "issue_reproduction"
    PERSONA_CRITIQUE = "persona_critique"
    BROWSER_EVIDENCE = "browser_evidence"
    CODE_LOCALIZATION = "code_localization"
    OUTPUT_QUALITY_REVIEW = "output_quality_review"


class FindingCategory(str, Enum):
    FUNCTIONAL_DEFECT = "functional_defect"
    REPRODUCTION_RECORD = "reproduction_record"
    ALGORITHM_CAPABILITY_PROBLEM = "algorithm_capability_problem"
    DESIGN_ARCHITECTURE_DEFECT = "design_architecture_defect"
    UNMET_USER_NEED = "unmet_user_need"


class VisibleLayer(str, Enum):
    FRONTEND = "frontend"
    BROWSER = "browser"
    API = "api"
    CODE = "code"
    SKILL = "skill"
    PROTOCOL = "protocol"
    DEMAND_DOC = "demand_doc"
    DATA = "data"
    GENERATED_OUTPUT = "generated_output"


@dataclass
class MetaVerifierGoalRequirement:
    requirement_id: str
    summary: str
    user_outcome: str = ""
    acceptance_question: str = ""
    required_layers: List[str] = field(default_factory=list)
    requires_browser_evidence: bool = False
    requires_higher_level_probe: bool = False
    project_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierGoalRequirement":
        return cls(
            requirement_id=str(data.get("requirement_id") or data.get("id") or uuid.uuid4()),
            summary=str(data.get("summary", "")),
            user_outcome=str(data.get("user_outcome", "")),
            acceptance_question=str(data.get("acceptance_question", "")),
            required_layers=list(data.get("required_layers", [])),
            requires_browser_evidence=bool(data.get("requires_browser_evidence", False)),
            requires_higher_level_probe=bool(data.get("requires_higher_level_probe", False)),
            project_metadata=dict(data.get("project_metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class MetaVerifierLayerCoverage:
    visible_layers: List[str] = field(default_factory=list)
    invisible_layers: List[str] = field(default_factory=list)
    visibility_scope: str = "unknown"
    confidence_impact: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierLayerCoverage":
        return cls(
            visible_layers=list(data.get("visible_layers", [])),
            invisible_layers=list(data.get("invisible_layers", [])),
            visibility_scope=str(data.get("visibility_scope", "unknown")),
            confidence_impact=list(data.get("confidence_impact", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class MetaVerifierAuditResult:
    status: str
    category: str
    message: str
    severity: str = "medium"
    requirement_id: str = ""
    checklist_item_id: str = ""
    evidence_id: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierAuditResult":
        return cls(
            status=str(data.get("status", "warn")),
            category=str(data.get("category", "")),
            message=str(data.get("message", "")),
            severity=str(data.get("severity", "medium")),
            requirement_id=str(data.get("requirement_id", "")),
            checklist_item_id=str(data.get("checklist_item_id", "")),
            evidence_id=str(data.get("evidence_id", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _route(value: str | RouteType) -> RouteType:
    return value if isinstance(value, RouteType) else RouteType(str(value))


def _category(value: str | FindingCategory) -> FindingCategory:
    return value if isinstance(value, FindingCategory) else FindingCategory(str(value))


@dataclass
class MetaVerifierRouteDecision:
    primary_route: RouteType
    supporting_routes: List[RouteType] = field(default_factory=list)
    target_scope: str = ""
    inferred_persona: str = "挑剔的需求方用户"
    confidence: str = "medium"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierRouteDecision":
        return cls(
            primary_route=_route(data.get("primary_route", RouteType.PERSONA_CRITIQUE.value)),
            supporting_routes=[_route(item) for item in data.get("supporting_routes", [])],
            target_scope=str(data.get("target_scope", "")),
            inferred_persona=str(data.get("inferred_persona", "挑剔的需求方用户")),
            confidence=str(data.get("confidence", "medium")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_route": self.primary_route.value,
            "supporting_routes": [item.value for item in self.supporting_routes],
            "target_scope": self.target_scope,
            "inferred_persona": self.inferred_persona,
            "confidence": self.confidence,
        }


class MetaVerifierIntentRouter:
    def route(self, raw_user_request: str, visible_context: Dict[str, Any] | None = None) -> MetaVerifierRouteDecision:
        request = (raw_user_request or "").strip()
        lowered = request.lower()
        if not request:
            return MetaVerifierRouteDecision(
                primary_route=RouteType.PERSONA_CRITIQUE,
                supporting_routes=[RouteType.PROJECT_EXPLORATION, RouteType.BROWSER_EVIDENCE],
                target_scope="current project",
                confidence="high",
            )

        issue_words = ("问题", "报错", "没反应", "不对", "失败", "复现", "定位", "error", "fail")
        target_words = ("测试", "验证", "按钮", "页面", "链路", "核心", "控件", "page", "button")
        goal_words = ("能不能帮助", "是否满足", "合不合理", "需求方", "用户目标", "业务目标", "制定", "计划")

        if any(word in lowered or word in request for word in issue_words):
            return MetaVerifierRouteDecision(
                primary_route=RouteType.ISSUE_REPRODUCTION,
                supporting_routes=[RouteType.BROWSER_EVIDENCE, RouteType.CODE_LOCALIZATION],
                target_scope=request,
                confidence="high",
            )
        if any(word in lowered or word in request for word in target_words):
            return MetaVerifierRouteDecision(
                primary_route=RouteType.TARGETED_VERIFICATION,
                supporting_routes=[RouteType.PROJECT_EXPLORATION, RouteType.BROWSER_EVIDENCE, RouteType.PERSONA_CRITIQUE],
                target_scope=request,
                confidence="high",
            )
        if any(word in lowered or word in request for word in goal_words):
            return MetaVerifierRouteDecision(
                primary_route=RouteType.PERSONA_CRITIQUE,
                supporting_routes=[RouteType.PROJECT_EXPLORATION, RouteType.OUTPUT_QUALITY_REVIEW],
                target_scope=request,
                confidence="high",
            )
        return MetaVerifierRouteDecision(
            primary_route=RouteType.PERSONA_CRITIQUE,
            supporting_routes=[RouteType.PROJECT_EXPLORATION, RouteType.BROWSER_EVIDENCE],
            target_scope=request,
            confidence="medium",
        )


@dataclass
class MetaVerifierChecklistItem:
    item_id: str
    target: str
    target_type: str = ""
    source: str = ""
    priority: str = "medium"
    expected_evidence: List[str] = field(default_factory=list)
    user_path: List[str] = field(default_factory=list)
    acceptance_question: str = ""
    browser_action_hints: List[Dict[str, Any]] = field(default_factory=list)
    requirement_id: str = ""
    layers: List[str] = field(default_factory=list)
    evidence_required: bool = True
    evidence_rule: str = ""
    source_kind: str = ""
    project_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierChecklistItem":
        return cls(
            item_id=str(data.get("item_id") or data.get("id") or uuid.uuid4()),
            target=str(data.get("target", "")),
            target_type=str(data.get("target_type", "")),
            source=str(data.get("source", "")),
            priority=str(data.get("priority", "medium")),
            expected_evidence=list(data.get("expected_evidence", [])),
            user_path=list(data.get("user_path", [])),
            acceptance_question=str(data.get("acceptance_question", "")),
            browser_action_hints=list(data.get("browser_action_hints", [])),
            requirement_id=str(data.get("requirement_id", "")),
            layers=list(data.get("layers", [])),
            evidence_required=bool(data.get("evidence_required", True)),
            evidence_rule=str(data.get("evidence_rule", "")),
            source_kind=str(data.get("source_kind", "")),
            project_metadata=dict(data.get("project_metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class MetaVerifierEvidence:
    evidence_id: str
    source: str
    action_trace: List[Dict[str, Any]] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    html_snapshots: List[str] = field(default_factory=list)
    console_logs: List[Any] = field(default_factory=list)
    page_state: Dict[str, Any] = field(default_factory=dict)
    artifact_refs: List[str] = field(default_factory=list)
    reviewer_critique: Dict[str, Any] = field(default_factory=dict)
    timing: Dict[str, Any] = field(default_factory=dict)
    covered_layers: List[str] = field(default_factory=list)
    error_message: str = ""
    project_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierEvidence":
        return cls(
            evidence_id=str(data.get("evidence_id") or data.get("id") or uuid.uuid4()),
            source=str(data.get("source", "")),
            action_trace=list(data.get("action_trace", [])),
            screenshots=list(data.get("screenshots", [])),
            html_snapshots=list(data.get("html_snapshots", [])),
            console_logs=list(data.get("console_logs", [])),
            page_state=dict(data.get("page_state", {})),
            artifact_refs=list(data.get("artifact_refs", [])),
            reviewer_critique=dict(data.get("reviewer_critique", {})),
            timing=dict(data.get("timing", {})),
            covered_layers=list(data.get("covered_layers", [])),
            error_message=str(data.get("error_message", "")),
            project_metadata=dict(data.get("project_metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class MetaVerifierFinding:
    finding_id: str
    category: FindingCategory
    severity: str
    user_impact: str
    source_checklist_item: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    reproduction_steps: List[str] = field(default_factory=list)
    suspected_areas: List[str] = field(default_factory=list)
    recommendation: str = ""
    evidence_status: str = "confirmed"
    project_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierFinding":
        return cls(
            finding_id=str(data.get("finding_id") or data.get("id") or uuid.uuid4()),
            category=_category(data.get("category", FindingCategory.FUNCTIONAL_DEFECT.value)),
            severity=str(data.get("severity", "medium")),
            user_impact=str(data.get("user_impact", "")),
            source_checklist_item=str(data.get("source_checklist_item", "")),
            evidence_refs=list(data.get("evidence_refs", [])),
            reproduction_steps=list(data.get("reproduction_steps", [])),
            suspected_areas=list(data.get("suspected_areas", [])),
            recommendation=str(data.get("recommendation", "")),
            evidence_status=str(data.get("evidence_status", "confirmed")),
            project_metadata=dict(data.get("project_metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.__dict__)
        data["category"] = self.category.value
        return data


@dataclass
class MetaVerifierReport:
    run_id: str
    user_goal: str = ""
    route: MetaVerifierRouteDecision | None = None
    checklist: List[MetaVerifierChecklistItem] = field(default_factory=list)
    evidence: List[MetaVerifierEvidence] = field(default_factory=list)
    findings: List[MetaVerifierFinding] = field(default_factory=list)
    persona_critiques: List[MetaVerifierFinding] = field(default_factory=list)
    can_user_complete_goal: str = "unknown"
    biggest_risks: List[str] = field(default_factory=list)
    next_investigations: List[str] = field(default_factory=list)
    project_metadata: Dict[str, Any] = field(default_factory=dict)
    goal_requirements: List[MetaVerifierGoalRequirement] = field(default_factory=list)
    layer_coverage: MetaVerifierLayerCoverage = field(default_factory=MetaVerifierLayerCoverage)
    audit_summary: List[MetaVerifierAuditResult] = field(default_factory=list)
    confidence_impact: List[str] = field(default_factory=list)
    unverified_areas: List[str] = field(default_factory=list)
    higher_level_probes: List[str] = field(default_factory=list)

    def summary_by_category(self) -> Dict[str, int]:
        summary = {category.value: 0 for category in FindingCategory}
        for finding in [*self.findings, *self.persona_critiques]:
            summary[finding.category.value] += 1
        return summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_goal": self.user_goal,
            "route": self.route.to_dict() if self.route else None,
            "checklist": [item.to_dict() for item in self.checklist],
            "evidence": [item.to_dict() for item in self.evidence],
            "findings": [item.to_dict() for item in self.findings],
            "persona_critiques": [item.to_dict() for item in self.persona_critiques],
            "summary_by_category": self.summary_by_category(),
            "can_user_complete_goal": self.can_user_complete_goal,
            "biggest_risks": list(self.biggest_risks),
            "next_investigations": list(self.next_investigations),
            "project_metadata": dict(self.project_metadata),
            "goal_requirements": [item.to_dict() for item in self.goal_requirements],
            "layer_coverage": self.layer_coverage.to_dict(),
            "audit_summary": [item.to_dict() for item in self.audit_summary],
            "confidence_impact": list(self.confidence_impact),
            "unverified_areas": list(self.unverified_areas),
            "higher_level_probes": list(self.higher_level_probes),
        }


class MetaVerifierVisibilityScopeDetector:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)

    def detect(self, route: MetaVerifierRouteDecision) -> MetaVerifierLayerCoverage:
        artifacts = MetaVerifierProjectDiscovery(self.project_root).discover_artifacts()
        visible = set()
        if artifacts.get("frontend_pages"):
            visible.update({VisibleLayer.FRONTEND.value, VisibleLayer.BROWSER.value, VisibleLayer.GENERATED_OUTPUT.value})
        if artifacts.get("demand_docs"):
            visible.add(VisibleLayer.DEMAND_DOC.value)
        if artifacts.get("protocol_docs"):
            visible.add(VisibleLayer.PROTOCOL.value)
        if artifacts.get("skill_docs"):
            visible.add(VisibleLayer.SKILL.value)
        if artifacts.get("project_configs"):
            visible.update({VisibleLayer.DATA.value, VisibleLayer.API.value, VisibleLayer.CODE.value})
        all_layers = {layer.value for layer in VisibleLayer}
        invisible = sorted(all_layers - visible)
        if {VisibleLayer.CODE.value, VisibleLayer.API.value, VisibleLayer.FRONTEND.value}.issubset(visible):
            scope = "full_repo"
        elif VisibleLayer.FRONTEND.value in visible:
            scope = "frontend-visible"
        elif VisibleLayer.API.value in visible:
            scope = "api-visible"
        elif VisibleLayer.SKILL.value in visible:
            scope = "skill-visible"
        else:
            scope = "black-box"
        confidence = [f"{layer} layer not visible; related conclusions must be downgraded or labeled as hypothesis" for layer in invisible]
        return MetaVerifierLayerCoverage(sorted(visible), invisible, scope, confidence)


class MetaVerifierGoalDecomposer:
    def decompose(self, raw_user_request: str, route: MetaVerifierRouteDecision, layer_coverage: MetaVerifierLayerCoverage) -> List[MetaVerifierGoalRequirement]:
        request = raw_user_request or route.target_scope or "current project"
        has_browser = VisibleLayer.BROWSER.value in layer_coverage.visible_layers
        if route.primary_route == RouteType.ISSUE_REPRODUCTION:
            return [
                MetaVerifierGoalRequirement("R1", "复现用户报告的问题", "用户能看到问题是否真实存在", "能否用最短用户路径复现该问题？", [VisibleLayer.FRONTEND.value, VisibleLayer.BROWSER.value], has_browser),
                MetaVerifierGoalRequirement("R2", "定位可见产生机制", "开发能基于证据继续修复", "复现结果能否关联到可见代码/API/协议机制？", [VisibleLayer.CODE.value, VisibleLayer.API.value, VisibleLayer.PROTOCOL.value]),
            ]
        if route.primary_route == RouteType.TARGETED_VERIFICATION:
            return [
                MetaVerifierGoalRequirement("R1", "验证目标页面或链路可达", "用户能进入目标功能", "用户能否打开目标页面并看到关键控件？", [VisibleLayer.FRONTEND.value, VisibleLayer.BROWSER.value], has_browser),
                MetaVerifierGoalRequirement("R2", "执行真实用户交互并观察结果", "用户能完成点击/输入/等待结果", "真实浏览器操作是否产生符合预期的用户可见结果？", [VisibleLayer.FRONTEND.value, VisibleLayer.BROWSER.value, VisibleLayer.GENERATED_OUTPUT.value], has_browser),
                MetaVerifierGoalRequirement("R3", "验证可见结果的产生机制", "开发能确认不是展示层补丁", "可见结果是否与代码/API/协议机制一致且无 stale/split-brain/overfit？", [VisibleLayer.CODE.value, VisibleLayer.API.value, VisibleLayer.PROTOCOL.value]),
            ]
        return [
            MetaVerifierGoalRequirement("R1", f"判断需求方目标是否可完成：{request}", "需求方用户能完成真实工作或做出决策", "系统输出是否足以让用户完成真实工作或决策？", [VisibleLayer.DEMAND_DOC.value, VisibleLayer.GENERATED_OUTPUT.value], has_browser, True),
            MetaVerifierGoalRequirement("R2", "审查业务/算法/架构高阶缺口", "迭代方获得有意义的问题反馈", "即使页面可点击，是否仍存在业务、算法或架构层面的 unmet need？", [VisibleLayer.PROTOCOL.value, VisibleLayer.CODE.value, VisibleLayer.DATA.value], False, True),
        ]


class MetaVerifierFindingValidator:
    def validate_confirmed_findings(self, findings: List[MetaVerifierFinding], evidence: List[MetaVerifierEvidence], checklist: List[MetaVerifierChecklistItem]) -> List[MetaVerifierAuditResult]:
        results: List[MetaVerifierAuditResult] = []
        evidence_by_id = {item.evidence_id: item for item in evidence}
        checklist_by_id = {item.item_id: item for item in checklist}
        for finding in findings:
            if finding.evidence_status != "confirmed" or finding.project_metadata.get("source") == "demand_side_reviewer":
                results.append(MetaVerifierAuditResult("fail", "unsupported_confirmed_finding", f"{finding.finding_id} is not supported by confirmed execution evidence", "high", evidence_id=",".join(finding.evidence_refs)))
                continue
            if not finding.evidence_refs or any(ref not in evidence_by_id for ref in finding.evidence_refs):
                results.append(MetaVerifierAuditResult("fail", "unsupported_confirmed_finding", f"{finding.finding_id} has missing or unresolved evidence_refs", "high", evidence_id=",".join(finding.evidence_refs)))
                continue
            checklist_item = checklist_by_id.get(finding.source_checklist_item)
            if checklist_item and checklist_item.evidence_rule == "browser_required":
                if not any(evidence_by_id[ref].source == "browser" or VisibleLayer.BROWSER.value in evidence_by_id[ref].covered_layers for ref in finding.evidence_refs):
                    results.append(MetaVerifierAuditResult("fail", "missing_browser_evidence", f"{finding.finding_id} needs browser evidence", "high", checklist_item_id=checklist_item.item_id))
        return results


class MetaVerifierDemandCoverageAuditor:
    def audit_planned_run(self, run: "MetaVerifierRun") -> List[MetaVerifierAuditResult]:
        results: List[MetaVerifierAuditResult] = []
        if not run.goal_requirements:
            results.append(MetaVerifierAuditResult("fail", "missing_goal_decomposition", "run has no decomposed goal requirements", "high"))
        if not run.layer_coverage.visible_layers and not run.layer_coverage.invisible_layers:
            results.append(MetaVerifierAuditResult("fail", "missing_layer_mapping", "run has no visible/invisible layer coverage", "high"))
        requirement_ids = {item.requirement_id for item in run.goal_requirements}
        for item in run.checklist:
            if not item.source:
                results.append(MetaVerifierAuditResult("fail", "missing_source_backed_checklist", f"{item.item_id} has no source", "high", checklist_item_id=item.item_id))
            if requirement_ids and item.requirement_id not in requirement_ids:
                results.append(MetaVerifierAuditResult("fail", "missing_requirement_link", f"{item.item_id} is not linked to a goal requirement", "high", checklist_item_id=item.item_id))
        needs_browser = any(item.requires_browser_evidence for item in run.goal_requirements) or RouteType.BROWSER_EVIDENCE in run.route.supporting_routes
        has_browser_check = any(item.evidence_rule == "browser_required" or VisibleLayer.BROWSER.value in item.layers for item in run.checklist)
        if needs_browser and (not has_browser_check or not run.browser_plan):
            results.append(MetaVerifierAuditResult("fail", "missing_browser_evidence_plan", "browser-visible route lacks browser-required checklist coverage or browser plan", "high"))
        needs_probe = any(item.requires_higher_level_probe for item in run.goal_requirements)
        has_probe = any(item.project_metadata.get("higher_level_probe") or item.target_type == "higher_level_probe" for item in run.checklist)
        if needs_probe and not has_probe:
            results.append(MetaVerifierAuditResult("fail", "missing_higher_level_probe", "broad demand-side route lacks higher-level probe checklist item", "high"))
        return results

    def audit_completed_run(self, run: "MetaVerifierRun") -> List[MetaVerifierAuditResult]:
        results = MetaVerifierFindingValidator().validate_confirmed_findings(run.findings, run.evidence, run.checklist)
        evidence_by_id = {item.evidence_id: item for item in run.evidence}
        for item in run.checklist:
            if item.evidence_rule == "browser_required":
                has_browser = any(ev.source == "browser" or VisibleLayer.BROWSER.value in ev.covered_layers for ev in evidence_by_id.values())
                if not has_browser:
                    results.append(MetaVerifierAuditResult("fail", "missing_browser_evidence", f"{item.item_id} requires browser evidence", "high", checklist_item_id=item.item_id))
        needs_probe = any(item.requires_higher_level_probe for item in run.goal_requirements)
        has_probe_evidence = any(ev.project_metadata.get("higher_level_probe") for ev in run.evidence)
        if needs_probe and not run.findings and not has_probe_evidence:
            results.append(MetaVerifierAuditResult("warn", "pass_theater_risk", "no confirmed findings without executed higher-level demand-side probe", "high"))
        if run.layer_coverage.invisible_layers and not run.layer_coverage.confidence_impact:
            results.append(MetaVerifierAuditResult("warn", "invisible_layer_risk", "invisible layers are not reflected in confidence impact", "medium"))
        return results


class MetaVerifierReviewerPromptBuilder:
    def build(self, run: MetaVerifierRun) -> str:
        target_url = run.target_url or ""
        persona = run.persona.get("role", "挑剔的需求方用户")
        goal = run.raw_user_request or run.route.target_scope or "验证当前项目"

        sections = [
            f"## 你的角色",
            f"你是 **{persona}**。你的任务是**亲自使用这个系统**来完成一个真实目标，不是远远看着 checklist 打勾。",
            "",
            f"## 你的目标",
            f"你要完成的事：**{goal}**",
            f"把这个目标当成你真的要解决的问题。如果系统帮不了你，那就是系统的问题。",
            "",
        ]

        if run.checklist:
            sections.extend([
                "## 你可能关心的方面（来自项目分析，不是硬性 checklist）",
                "以下是一些参考点，但你的主要任务是使用系统完成目标，不是逐项打勾：",
                *[f"- {item.target}（为什么关心：{item.acceptance_question or '用户目标相关'}）" for item in run.checklist],
                "",
            ])

        sections.extend([
            f"## 系统入口",
            f"当前系统入口: {target_url}",
            "如果入口是网页，**你必须用浏览器工具打开它**，不要只看代码或文档就下结论。",
            "如果入口是 API / CLI，用对应的工具发送真实请求或执行真实命令。",
            "",
            "## 使用方式",
            "1. 打开系统入口，用自己的话理解这个系统是干什么的。",
            "2. 以你的角色和目标，开始使用系统。像真实用户一样操作：点击、输入、等待、看结果。",
            "3. 记录你做的每一步和系统的实际反应。",
            "4. 对比你期望的结果和实际结果。任何偏差都是潜在问题。",
            "5. 完成一次主要路径后，尝试边界情况：奇怪的输入、快速连点、中途刷新、错误恢复等。",
            "",
            "## 你要找的问题类型",
            "- 功能缺陷：按钮无效、页面报错、结果不出现、状态丢失。",
            "- 算法能力问题：输出看起来对但实际不对、不可行动、过于泛化、不接地气。",
            "- 设计/架构缺陷：流程割裂、数据不一致、两个页面显示不同结果、操作路径不合理。",
            "- 用户目标缺口：你能点通所有按钮，但你最初的目标还是没完成。",
            "",
            "## 输出要求",
            "只输出你**实际使用后**发现的问题。不要写\"系统设计良好\"之类的废话。",
            "",
            "每条发现用以下格式：",
            "```",
            "问题：<一句话描述>",
            "类型：functional_defect | algorithm_capability_problem | design_architecture_defect | unmet_user_need",
            "严重度：high | medium | low",
            "用户影响：<这个问题的实际后果>",
            "复现步骤：<你做过的操作，别人能照着复现>",
            "实际结果：<系统实际给的反应>",
            "期望结果：<你期望系统给的反应>",
            "证据：<你从浏览器截图/log/API 响应中看到的具体内容>",
            "```",
            "",
            "## 铁律",
            "- 没有亲自操作的判断不能写 confirmed，只能标注 hypothesis。",
            "- 如果系统整体上没有帮你完成目标，那就是 unmet_user_need，不管按钮能不能点。",
            "- 宁可多写几条具体问题，不要写\"系统基本可用\"之类的话。",
        ])

        return "\n".join(sections)


class MetaVerifierReviewerLauncher:
    def __init__(self, prompt_builder: MetaVerifierReviewerPromptBuilder | None = None):
        self.prompt_builder = prompt_builder or MetaVerifierReviewerPromptBuilder()

    def build_request(self, run: MetaVerifierRun) -> Dict[str, Any]:
        return {
            "reviewer_id": f"demand-side-user-{run.run_id}",
            "subagent_type": "general-purpose",
            "description": "Demanding user drives the system to accomplish a real goal",
            "prompt": self.prompt_builder.build(run),
            "expected_output": "Structured findings from actual system usage: problem, type, severity, user impact, reproduction steps, actual result, expected result, evidence",
            "merge_as_unverified_critique": True,
        }


class MetaVerifierReportBuilder:
    def build(self, run: MetaVerifierRun) -> MetaVerifierReport:
        report = MetaVerifierReport(
            run_id=run.run_id,
            user_goal=run.raw_user_request,
            route=run.route,
            checklist=list(run.checklist),
            evidence=list(run.evidence),
            findings=list(run.findings),
            project_metadata=dict(run.project_metadata),
            goal_requirements=list(run.goal_requirements),
            layer_coverage=run.layer_coverage,
            audit_summary=list(run.audit_results),
            confidence_impact=list(run.layer_coverage.confidence_impact),
            unverified_areas=list(run.layer_coverage.invisible_layers),
            higher_level_probes=[item.summary for item in run.goal_requirements if item.requires_higher_level_probe],
        )
        report.can_user_complete_goal = "no" if run.findings else "unknown"
        report.biggest_risks = [
            f"{finding.severity}:{finding.category.value}:{finding.user_impact}"
            for finding in run.findings
        ]
        checklist_by_id = {item.item_id: item for item in run.checklist}
        default_checklist_item = run.checklist[0].item_id if len(run.checklist) == 1 else ""
        report.next_investigations = [
            f"修复 {finding.finding_id} 后复验 {finding.source_checklist_item or default_checklist_item}"
            for finding in run.findings
            if (finding.source_checklist_item in checklist_by_id) or (not finding.source_checklist_item and default_checklist_item)
        ]
        if run.findings and not report.next_investigations:
            report.next_investigations = ["根据 confirmed findings 的 evidence_refs 复验对应用户路径"]
        return report


class MetaVerifierReviewerMerge:
    def merge(self, report: MetaVerifierReport, reviewer_findings: List[Dict[str, Any]], reviewer_id: str) -> MetaVerifierReport:
        for item in reviewer_findings:
            metadata = dict(item.get("project_metadata", {}))
            metadata.update({"reviewer_id": reviewer_id, "source": "demand_side_reviewer"})
            report.persona_critiques.append(
                MetaVerifierFinding(
                    finding_id=str(item.get("finding_id") or item.get("id") or uuid.uuid4()),
                    category=_category(item.get("category", FindingCategory.UNMET_USER_NEED.value)),
                    severity=str(item.get("severity", "medium")),
                    user_impact=str(item.get("user_impact", "")),
                    source_checklist_item=str(item.get("source_checklist_item", "")),
                    evidence_refs=list(item.get("evidence_refs", [])),
                    reproduction_steps=list(item.get("reproduction_steps", [])),
                    suspected_areas=list(item.get("suspected_areas", [])),
                    recommendation=str(item.get("recommendation", "")),
                    evidence_status="unverified_reviewer_critique",
                    project_metadata=metadata,
                )
            )
        return report


class MetaVerifierBrowserEvidenceExecutor:
    def __init__(self, driver_factory: Callable[[], Any] | None = None):
        self.driver_factory = driver_factory or self._default_driver_factory

    def _default_driver_factory(self) -> Any:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        with self._compatible_chromedriver_path():
            return webdriver.Chrome(options=options)

    def _compatible_chromedriver_path(self):
        executor = self

        class CompatibleChromeDriverPath:
            def __init__(self):
                self.original_path = os.environ.get("PATH", "")

            def __enter__(self):
                chromedriver = shutil.which("chromedriver")
                if chromedriver and not executor._chromedriver_is_compatible(chromedriver):
                    bad_dir = str(Path(chromedriver).resolve().parent)
                    path_parts = [part for part in self.original_path.split(os.pathsep) if part and str(Path(part).resolve()) != bad_dir]
                    os.environ["PATH"] = os.pathsep.join(path_parts)
                return self

            def __exit__(self, exc_type, exc, tb):
                os.environ["PATH"] = self.original_path
                return False

        return CompatibleChromeDriverPath()

    def _chromedriver_is_compatible(self, chromedriver: str) -> bool:
        driver_major = self._chromedriver_major_version(chromedriver)
        browser_major = self._chrome_major_version()
        return not driver_major or not browser_major or driver_major == browser_major

    def _chromedriver_major_version(self, chromedriver: str) -> str:
        try:
            result = subprocess.run([chromedriver, "--version"], check=False, capture_output=True, text=True, timeout=5)
        except Exception:
            return ""
        match = re.search(r"ChromeDriver\s+(\d+)", result.stdout or result.stderr or "")
        return match.group(1) if match else ""

    def _chrome_major_version(self) -> str:
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            shutil.which("google-chrome") or "",
            shutil.which("chromium") or "",
            shutil.which("chromium-browser") or "",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                result = subprocess.run([candidate, "--version"], check=False, capture_output=True, text=True, timeout=5)
            except Exception:
                continue
            match = re.search(r"(\d+)\.\d+\.\d+\.\d+", result.stdout or result.stderr or "")
            if match:
                return match.group(1)
        return ""

    def run_plan(self, checklist_item_id: str, start_url: str, actions: List[Dict[str, Any]]) -> tuple[MetaVerifierEvidence, List[MetaVerifierFinding]]:
        evidence = MetaVerifierEvidence(evidence_id=str(uuid.uuid4()), source="browser")
        findings: List[MetaVerifierFinding] = []
        driver = None
        started = time.time()
        try:
            driver = self.driver_factory()
            for action in actions:
                trace_item = self._execute_action(driver, start_url, action)
                evidence.action_trace.append(trace_item)
                if trace_item["status"] == "failed":
                    findings.append(self._finding_from_failed_action(checklist_item_id, trace_item))
                    break
            evidence.page_state = self._page_state(driver)
            evidence.html_snapshots = [str(getattr(driver, "page_source", ""))]
        except Exception as exc:
            evidence.error_message = str(exc)
            findings.append(
                MetaVerifierFinding(
                    finding_id=str(uuid.uuid4()),
                    category=FindingCategory.FUNCTIONAL_DEFECT,
                    severity="high",
                    user_impact=f"浏览器证据执行失败：{exc}",
                    source_checklist_item=checklist_item_id,
                    evidence_refs=[evidence.evidence_id],
                    suspected_areas=["browser_evidence_executor"],
                    recommendation="检查浏览器启动、页面可达性或操作计划。",
                )
            )
        finally:
            evidence.timing = {"duration_seconds": round(time.time() - started, 3)}
            if driver is not None and hasattr(driver, "quit"):
                driver.quit()
        return evidence, findings

    def _execute_action(self, driver: Any, start_url: str, action: Dict[str, Any]) -> Dict[str, Any]:
        action_type = str(action.get("type", ""))
        trace_item = {"type": action_type, "status": "passed"}
        if "selector" in action:
            trace_item["selector"] = action.get("selector")
        if "target" in action:
            trace_item["target"] = action.get("target")
        try:
            if action_type == "open":
                driver.get(str(action.get("target") or start_url))
            elif action_type == "click":
                driver.find_element("css selector", str(action.get("selector"))).click()
            elif action_type == "type":
                element = driver.find_element("css selector", str(action.get("selector")))
                if hasattr(element, "clear"):
                    element.clear()
                element.send_keys(str(action.get("value", "")))
            elif action_type == "wait":
                time.sleep(float(action.get("seconds", 0)))
            elif action_type == "assert_text":
                text = str(action.get("text", ""))
                if text not in str(getattr(driver, "page_source", "")):
                    raise AssertionError(f"text not found: {text}")
            else:
                raise ValueError(f"unsupported browser action: {action_type}")
        except Exception as exc:
            trace_item["status"] = "failed"
            trace_item["error_message"] = str(exc)
        return trace_item

    def _page_state(self, driver: Any) -> Dict[str, Any]:
        return {
            "url": str(getattr(driver, "current_url", "")),
            "title": str(getattr(driver, "title", "")),
        }

    def _finding_from_failed_action(self, checklist_item_id: str, trace_item: Dict[str, Any]) -> MetaVerifierFinding:
        selector = trace_item.get("selector") or trace_item.get("target") or trace_item.get("type", "browser action")
        return MetaVerifierFinding(
            finding_id=str(uuid.uuid4()),
            category=FindingCategory.FUNCTIONAL_DEFECT,
            severity="high",
            user_impact=f"用户操作 {selector} 失败：{trace_item.get('error_message', '')}",
            source_checklist_item=checklist_item_id,
            suspected_areas=["browser_interaction", str(selector)],
            recommendation="根据失败 selector、页面状态和操作链路定位前端交互问题。",
        )


@dataclass
class MetaVerifierExtension:
    project_id: str = ""
    discovery_hints: Dict[str, Any] = field(default_factory=dict)
    selector_aliases: Dict[str, str] = field(default_factory=dict)
    persona_prompts: List[str] = field(default_factory=list)
    business_goals: List[str] = field(default_factory=list)
    algorithm_acceptance_criteria: List[str] = field(default_factory=list)
    custom_finding_classifiers: Dict[str, str] = field(default_factory=dict)
    project_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierExtension":
        return cls(
            project_id=str(data.get("project_id", "")),
            discovery_hints=dict(data.get("discovery_hints", {})),
            selector_aliases=dict(data.get("selector_aliases", {})),
            persona_prompts=list(data.get("persona_prompts", [])),
            business_goals=list(data.get("business_goals", [])),
            algorithm_acceptance_criteria=list(data.get("algorithm_acceptance_criteria", [])),
            custom_finding_classifiers=dict(data.get("custom_finding_classifiers", {})),
            project_metadata=dict(data.get("project_metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class MetaVerifierProjectDiscovery:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)

    def _exists(self, relative_path: str) -> bool:
        return (self.project_root / relative_path).exists()

    def _read_text(self, relative_path: str) -> str:
        path = self.project_root / relative_path
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def discover_artifacts(self) -> Dict[str, List[str]]:
        root = self.project_root
        found: Dict[str, List[str]] = {
            "frontend_pages": [],
            "demand_docs": [],
            "protocol_docs": [],
            "project_configs": [],
            "skill_docs": [],
            "readme": [],
            "api_routes": [],
        }

        for path in sorted(root.rglob("*.html")):
            rel = str(path.relative_to(root))
            if any(skip in rel for skip in ["node_modules", ".git", "__pycache__", ".cache", "site-packages", ".claude/worktrees", "tool-results"]):
                continue
            found["frontend_pages"].append(rel)

        for path in sorted(root.rglob("*.md")):
            rel = str(path.relative_to(root))
            if any(skip in rel for skip in ["node_modules", ".git", "__pycache__", ".cache", "site-packages", ".claude/worktrees", "tool-results"]):
                continue
            parts = rel.split("/")
            if any(kw in p.lower() for p in parts for kw in ["demand", "requirement"]) or "需求" in rel:
                found["demand_docs"].append(rel)
            elif any(kw in p.lower() for p in parts for kw in ["protocol"]) or "协议" in rel:
                found["protocol_docs"].append(rel)
            elif any("skill" in p.lower() for p in parts) or ".claude/skills" in rel:
                found["skill_docs"].append(rel)
            elif rel.lower() in {"readme.md", "readme.md"} or "readme" in rel.lower():
                found["readme"].append(rel)

        for path in sorted(root.rglob("project.yaml")):
            rel = str(path.relative_to(root))
            if any(skip in rel for skip in ["node_modules", ".git", "__pycache__"]):
                continue
            found["project_configs"].append(rel)

        for ext in ["*.py", "*.js", "*.ts", "*.go", "*.java"]:
            for path in sorted(root.rglob(ext)):
                rel = str(path.relative_to(root))
                if any(skip in rel for skip in ["node_modules", ".git", "__pycache__", ".cache", "site-packages", ".claude/worktrees", "tool-results", "tests/", "test_"]):
                    continue
                if "api" in rel.lower() or "route" in rel.lower() or "server" in rel.lower() or "app" in rel.lower():
                    found["api_routes"].append(rel)

        return {k: v for k, v in found.items() if v}

    def generate_checklist(
        self,
        raw_user_request: str = "",
        goal_requirements: List[MetaVerifierGoalRequirement] | None = None,
        layer_coverage: MetaVerifierLayerCoverage | None = None,
    ) -> List[MetaVerifierChecklistItem]:
        artifacts = self.discover_artifacts()
        checklist: List[MetaVerifierChecklistItem] = []
        item_number = 1
        requirements = list(goal_requirements or [])
        requirement_cursor = 0
        coverage = layer_coverage or MetaVerifierLayerCoverage()

        def source_kind_for(source: str, target_type: str) -> str:
            if target_type in ("demand_doc", "protocol_doc", "frontend_page", "frontend_control", "frontend_chain", "higher_level_probe"):
                return target_type
            if source.endswith(".html"):
                return "frontend_page" if "#" not in source else "frontend_control"
            if source.endswith(".yaml") or source.endswith(".yml"):
                return "project_config"
            if source.endswith(".md"):
                if "protocol" in source.lower() or "协议" in source:
                    return "protocol_doc"
                if "demand" in source.lower() or "requirement" in source.lower() or "需求" in source:
                    return "demand_doc"
                if "skill" in source.lower():
                    return "skill_doc"
                if "readme" in source.lower():
                    return "readme"
            return target_type or "artifact"

        def requirement_for(target_type: str, layers: List[str]) -> MetaVerifierGoalRequirement | None:
            nonlocal requirement_cursor
            if not requirements:
                return None
            if target_type == "higher_level_probe":
                for requirement in requirements:
                    if requirement.requires_higher_level_probe:
                        return requirement
            if VisibleLayer.BROWSER.value in layers:
                for requirement in requirements:
                    if requirement.requires_browser_evidence:
                        return requirement
            chosen = requirements[requirement_cursor % len(requirements)]
            requirement_cursor += 1
            return chosen

        def add(
            target: str,
            target_type: str,
            source: str,
            priority: str,
            expected_evidence: List[str],
            user_path: List[str] | None = None,
            hints: List[Dict[str, Any]] | None = None,
            layers: List[str] | None = None,
            requirement: MetaVerifierGoalRequirement | None = None,
            metadata: Dict[str, Any] | None = None,
        ) -> None:
            nonlocal item_number
            item_layers = list(layers or [])
            if not item_layers:
                if source.endswith(".html"):
                    item_layers = [VisibleLayer.FRONTEND.value, VisibleLayer.BROWSER.value, VisibleLayer.GENERATED_OUTPUT.value]
                elif target_type == "demand_doc":
                    item_layers = [VisibleLayer.DEMAND_DOC.value]
                elif target_type == "protocol_doc":
                    item_layers = [VisibleLayer.PROTOCOL.value]
            linked_requirement = requirement or requirement_for(target_type, item_layers)
            project_metadata = {"raw_user_request": raw_user_request}
            project_metadata.update(metadata or {})
            checklist.append(
                MetaVerifierChecklistItem(
                    item_id=f"C{item_number}",
                    target=target,
                    target_type=target_type,
                    source=source,
                    priority=priority,
                    expected_evidence=expected_evidence,
                    user_path=list(user_path or []),
                    browser_action_hints=list(hints or []),
                    acceptance_question=(linked_requirement.acceptance_question if linked_requirement else f"用户能否完成：{target}？"),
                    requirement_id=linked_requirement.requirement_id if linked_requirement else "",
                    layers=item_layers,
                    evidence_required=bool(expected_evidence),
                    evidence_rule="browser_required" if VisibleLayer.BROWSER.value in item_layers else "artifact_or_code_required",
                    source_kind=source_kind_for(source, target_type),
                    project_metadata=project_metadata,
                )
            )
            item_number += 1

        for page_path in artifacts.get("frontend_pages", []):
            page_name = page_path.rsplit("/", 1)[-1].replace(".html", "")
            add(
                f"frontend page: {page_name}",
                "frontend_page",
                page_path,
                "high",
                ["page_state", "html_snapshot"],
                [f"打开 {page_name} 页面", "确认关键元素可见"],
                [{"type": "navigate", "target": page_path}],
            )

            page_text = self._read_text(page_path)
            for match in re.finditer(r"""onclick\s*=\s*["']?\s*(\w+)\s*\(""", page_text):
                func_name = match.group(1)
                add(
                    f"{page_name} control: {func_name}",
                    "frontend_control",
                    f"{page_path}#{func_name}",
                    "high",
                    ["action_trace", "page_state", "user_visible_result"],
                    [f"打开 {page_name}", f"触发 {func_name}", "观察结果"],
                    [{"type": "click", "function": func_name}],
                )

        for api_path in artifacts.get("api_routes", []):
            add(
                f"API route: {api_path}",
                "api_route",
                api_path,
                "medium",
                ["code_evidence", "artifact_evidence"],
                ["检查 API 路由定义", "确认端点可达"],
            )

        for path in artifacts.get("readme", []):
            add(
                "project overview from README",
                "readme",
                path,
                "high",
                ["artifact_evidence"],
                ["读取 README 了解项目目标和入口"],
            )

        for path in artifacts.get("demand_docs", []):
            add(
                "demand-side goal satisfaction",
                "demand_doc",
                path,
                "high",
                ["artifact_evidence", "persona_critique"],
                ["读取需求文档", "以需求方目标审视系统输出"],
            )

        for path in artifacts.get("protocol_docs", []):
            add(
                "protocol boundary alignment",
                "protocol_doc",
                path,
                "medium",
                ["artifact_evidence", "code_evidence"],
                ["读取协议", "检查实现与协议边界一致性"],
            )

        for path in artifacts.get("skill_docs", []):
            add(
                "skill implementation review",
                "skill_doc",
                path,
                "medium",
                ["artifact_evidence"],
                ["读取 skill 文档", "检查 skill 实现是否与声明一致"],
            )

        for requirement in requirements:
            if requirement.requires_higher_level_probe:
                demand_sources = artifacts.get("demand_docs") or artifacts.get("readme") or ["."]
                add(
                    requirement.summary,
                    "higher_level_probe",
                    demand_sources[0],
                    "high",
                    ["artifact_evidence", "persona_critique", "mechanism_review"],
                    ["从需求方目标出发", "审查业务/算法/架构缺口", "记录对下一轮迭代有用的问题"],
                    layers=[layer for layer in requirement.required_layers if layer in coverage.visible_layers] or list(requirement.required_layers),
                    requirement=requirement,
                    metadata={"higher_level_probe": True},
                )

        return checklist

    def build_browser_plan(self, checklist: List[MetaVerifierChecklistItem], base_url: str = "") -> List[Dict[str, Any]]:
        items_by_page: Dict[str, List[MetaVerifierChecklistItem]] = {}
        for item in checklist:
            if item.source.endswith(".html") and "#" not in item.source:
                items_by_page.setdefault(item.source, [])
            elif "#" in item.source:
                page = item.source.split("#")[0]
                items_by_page.setdefault(page, []).append(item)

        plan: List[Dict[str, Any]] = []

        for page_path, page_items in sorted(items_by_page.items()):
            if not page_path.endswith(".html"):
                continue

            page_text = self._read_text(page_path)
            url = page_path
            if base_url:
                page_name = page_path.rsplit("/", 1)[-1] if "/" in page_path else page_path
                url = f"{base_url.rstrip('/')}/{page_name}"
            plan.append({"type": "open", "target": url})

            for text_match in re.finditer(r">([^<]{2,30})<", page_text):
                text = text_match.group(1).strip()
                if text and len(text) >= 2:
                    plan.append({"type": "assert_text", "text": text})
                    break

            for item in page_items:
                func = item.source.split("#")[-1] if "#" in item.source else ""
                if func:
                    plan.append({"type": "click", "selector": f"[onclick*=\"{func}\"]"})

            for input_match in re.finditer(r'<input[^>]+id="([^"]+)"', page_text):
                input_id = input_match.group(1)
                plan.append({"type": "type", "selector": f"#{input_id}", "value": ""})
                break

        return plan


@dataclass
class MetaVerifierRun:
    run_id: str
    raw_user_request: str = ""
    target_url: str = ""
    project_scope: Dict[str, Any] = field(default_factory=dict)
    route: MetaVerifierRouteDecision = field(default_factory=lambda: MetaVerifierIntentRouter().route(""))
    persona: Dict[str, Any] = field(default_factory=dict)
    checklist: List[MetaVerifierChecklistItem] = field(default_factory=list)
    browser_plan: List[Dict[str, Any]] = field(default_factory=list)
    findings: List[MetaVerifierFinding] = field(default_factory=list)
    evidence: List[MetaVerifierEvidence] = field(default_factory=list)
    final_summary: Dict[str, Any] = field(default_factory=dict)
    project_metadata: Dict[str, Any] = field(default_factory=dict)
    goal_requirements: List[MetaVerifierGoalRequirement] = field(default_factory=list)
    layer_coverage: MetaVerifierLayerCoverage = field(default_factory=MetaVerifierLayerCoverage)
    audit_results: List[MetaVerifierAuditResult] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaVerifierRun":
        route_data = data.get("route")
        raw_request = str(data.get("raw_user_request", ""))
        return cls(
            run_id=str(data.get("run_id") or data.get("id") or uuid.uuid4()),
            raw_user_request=raw_request,
            target_url=str(data.get("target_url", "")),
            project_scope=dict(data.get("project_scope", {})),
            route=MetaVerifierRouteDecision.from_dict(route_data) if isinstance(route_data, dict) else MetaVerifierIntentRouter().route(raw_request),
            persona=dict(data.get("persona", {})),
            checklist=[MetaVerifierChecklistItem.from_dict(item) for item in data.get("checklist", [])],
            browser_plan=list(data.get("browser_plan", [])),
            findings=[MetaVerifierFinding.from_dict(item) for item in data.get("findings", [])],
            evidence=[MetaVerifierEvidence.from_dict(item) for item in data.get("evidence", [])],
            final_summary=dict(data.get("final_summary", {})),
            project_metadata=dict(data.get("project_metadata", {})),
            goal_requirements=[MetaVerifierGoalRequirement.from_dict(item) for item in data.get("goal_requirements", [])],
            layer_coverage=MetaVerifierLayerCoverage.from_dict(data.get("layer_coverage", {})),
            audit_results=[MetaVerifierAuditResult.from_dict(item) for item in data.get("audit_results", [])],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "raw_user_request": self.raw_user_request,
            "target_url": self.target_url,
            "project_scope": dict(self.project_scope),
            "route": self.route.to_dict(),
            "persona": dict(self.persona),
            "checklist": [item.to_dict() for item in self.checklist],
            "browser_plan": list(self.browser_plan),
            "findings": [item.to_dict() for item in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "final_summary": dict(self.final_summary),
            "project_metadata": dict(self.project_metadata),
            "goal_requirements": [item.to_dict() for item in self.goal_requirements],
            "layer_coverage": self.layer_coverage.to_dict(),
            "audit_results": [item.to_dict() for item in self.audit_results],
        }
