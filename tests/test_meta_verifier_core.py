import importlib.util
import os
from pathlib import Path
import sys
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "meta-verifier" / "scripts" / "meta_verifier.py"
spec = importlib.util.spec_from_file_location("meta_verifier_skill", MODULE_PATH)
meta_verifier_skill = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["meta_verifier_skill"] = meta_verifier_skill
spec.loader.exec_module(meta_verifier_skill)

FindingCategory = meta_verifier_skill.FindingCategory
MetaVerifierChecklistItem = meta_verifier_skill.MetaVerifierChecklistItem
MetaVerifierEvidence = meta_verifier_skill.MetaVerifierEvidence
MetaVerifierFinding = meta_verifier_skill.MetaVerifierFinding
MetaVerifierIntentRouter = meta_verifier_skill.MetaVerifierIntentRouter
MetaVerifierReport = meta_verifier_skill.MetaVerifierReport
MetaVerifierRun = meta_verifier_skill.MetaVerifierRun
MetaVerifierProjectDiscovery = meta_verifier_skill.MetaVerifierProjectDiscovery
MetaVerifierReportBuilder = meta_verifier_skill.MetaVerifierReportBuilder
MetaVerifierGoalDecomposer = meta_verifier_skill.MetaVerifierGoalDecomposer
MetaVerifierVisibilityScopeDetector = meta_verifier_skill.MetaVerifierVisibilityScopeDetector
MetaVerifierDemandCoverageAuditor = meta_verifier_skill.MetaVerifierDemandCoverageAuditor
RouteType = meta_verifier_skill.RouteType


class MetaVerifierCoreTest(unittest.TestCase):
    # --- Router ---
    def test_empty_input_routes_to_persona_critique(self):
        decision = MetaVerifierIntentRouter().route("")
        self.assertEqual(decision.primary_route, RouteType.PERSONA_CRITIQUE)

    def test_page_button_request_routes_to_targeted_verification(self):
        decision = MetaVerifierIntentRouter().route("验证 8020 前端所有核心按钮和主要链路")
        self.assertEqual(decision.primary_route, RouteType.TARGETED_VERIFICATION)
        self.assertEqual(decision.confidence, "high")

    def test_issue_description_routes_to_reproduction(self):
        decision = MetaVerifierIntentRouter().route("summary 页批量归因点击后没有结果，帮我复现定位")
        self.assertEqual(decision.primary_route, RouteType.ISSUE_REPRODUCTION)

    def test_business_goal_routes_to_persona_critique(self):
        decision = MetaVerifierIntentRouter().route("这个系统能不能帮助营销负责人制定增长计划")
        self.assertEqual(decision.primary_route, RouteType.PERSONA_CRITIQUE)

    # --- Discovery ---
    def test_project_discovery_dynamically_discovers_frontend_and_generates_checklist(self):
        root = MODULE_PATH.parents[4]
        checklist = MetaVerifierProjectDiscovery(root).generate_checklist("验证项目前端")
        sources = {item.source for item in checklist}
        self.assertTrue(any(s.endswith(".html") for s in sources))
        self.assertTrue(any(item.target_type == "frontend_page" for item in checklist))
        self.assertTrue(all(item.source for item in checklist))
        self.assertTrue(all(item.acceptance_question for item in checklist))

    def test_project_discovery_builds_browser_plan_from_discovered_pages(self):
        root = MODULE_PATH.parents[4]
        checklist = MetaVerifierProjectDiscovery(root).generate_checklist("验证项目前端")
        plan = MetaVerifierProjectDiscovery(root).build_browser_plan(checklist)
        self.assertTrue(len(plan) > 0)
        self.assertTrue(any(step["type"] == "open" for step in plan))

    # --- Goal / Visibility ---
    def test_goal_decomposer_creates_requirements_with_outcomes_and_probes(self):
        route = MetaVerifierIntentRouter().route("这个系统能不能帮助营销负责人制定增长计划")
        coverage = MetaVerifierVisibilityScopeDetector(MODULE_PATH.parents[4]).detect(route)
        requirements = MetaVerifierGoalDecomposer().decompose("这个系统能不能帮助营销负责人制定增长计划", route, coverage)
        self.assertTrue(any(item.user_outcome for item in requirements))
        self.assertTrue(any(item.requires_higher_level_probe for item in requirements))
        self.assertTrue(all(item.required_layers for item in requirements))

    def test_visibility_detector_reports_layers_with_confidence_impact(self):
        route = MetaVerifierIntentRouter().route("验证 8020 前端所有核心按钮")
        coverage = MetaVerifierVisibilityScopeDetector(MODULE_PATH.parents[4]).detect(route)
        self.assertIn("frontend", coverage.visible_layers)
        self.assertIn("browser", coverage.visible_layers)
        self.assertTrue(coverage.visibility_scope)
        self.assertIsInstance(coverage.confidence_impact, list)

    def test_checklist_generation_carries_goal_requirements_and_layers(self):
        root = MODULE_PATH.parents[4]
        route = MetaVerifierIntentRouter().route("这个系统能不能帮助营销负责人制定增长计划")
        coverage = MetaVerifierVisibilityScopeDetector(root).detect(route)
        requirements = MetaVerifierGoalDecomposer().decompose("这个系统能不能帮助营销负责人制定增长计划", route, coverage)
        checklist = MetaVerifierProjectDiscovery(root).generate_checklist(
            "这个系统能不能帮助营销负责人制定增长计划",
            goal_requirements=requirements,
            layer_coverage=coverage,
        )
        requirement_ids = {item.requirement_id for item in checklist}
        self.assertTrue({item.requirement_id for item in requirements}.issubset(requirement_ids))
        self.assertTrue(any(item.evidence_rule == "browser_required" for item in checklist))
        self.assertTrue(any(item.target_type == "higher_level_probe" for item in checklist))

    # --- Audit gates ---
    def test_planned_run_audit_fails_when_checklist_lacks_source_or_requirement(self):
        run = MetaVerifierRun.from_dict({
            "run_id": "run-audit-1",
            "raw_user_request": "验证 8020 前端",
            "route": {"primary_route": "targeted_verification", "supporting_routes": ["browser_evidence"]},
            "goal_requirements": [{"requirement_id": "R1", "summary": "验证前端链路", "user_outcome": "用户能完成前端验证", "required_layers": ["frontend", "browser"], "requires_browser_evidence": True}],
            "layer_coverage": {"visible_layers": ["frontend", "browser"], "visibility_scope": "frontend-only"},
            "checklist": [{"item_id": "C1", "target": "shallow button check"}],
        })
        audit = MetaVerifierDemandCoverageAuditor().audit_planned_run(run)
        categories = {item.category for item in audit}
        self.assertIn("missing_source_backed_checklist", categories)
        self.assertIn("missing_requirement_link", categories)

    def test_planned_run_audit_requires_browser_plan_for_frontend_route(self):
        run = MetaVerifierRun.from_dict({
            "run_id": "run-audit-2",
            "raw_user_request": "验证 8020 前端",
            "route": {"primary_route": "targeted_verification", "supporting_routes": ["browser_evidence"]},
            "goal_requirements": [{"requirement_id": "R1", "summary": "执行真实浏览器链路", "required_layers": ["frontend", "browser"], "requires_browser_evidence": True}],
            "layer_coverage": {"visible_layers": ["frontend", "browser"], "visibility_scope": "frontend-only"},
            "checklist": [{"item_id": "C1", "target": "summary batch button", "source": "impl/frontend/summary.html#batchRunButton", "requirement_id": "R1", "layers": ["frontend", "browser"], "evidence_rule": "browser_required"}],
        })
        audit = MetaVerifierDemandCoverageAuditor().audit_planned_run(run)
        self.assertIn("missing_browser_evidence_plan", {item.category for item in audit})

    def test_completed_run_audit_flags_unsupported_confirmed_finding(self):
        run = MetaVerifierRun.from_dict({
            "run_id": "run-audit-3",
            "raw_user_request": "验证 8020 前端",
            "route": {"primary_route": "targeted_verification", "supporting_routes": ["browser_evidence"]},
            "goal_requirements": [{"requirement_id": "R1", "summary": "验证", "required_layers": ["frontend"]}],
            "layer_coverage": {"visible_layers": ["frontend", "browser"], "visibility_scope": "frontend-only"},
            "checklist": [{"item_id": "C1", "target": "summary", "source": "impl/frontend/summary.html", "requirement_id": "R1"}],
            "findings": [{"finding_id": "F1", "category": "functional_defect", "severity": "high", "user_impact": "失败", "evidence_refs": ["missing"]}],
        })
        audit = MetaVerifierDemandCoverageAuditor().audit_completed_run(run)
        self.assertIn("unsupported_confirmed_finding", {item.category for item in audit})

    def test_completed_run_audit_flags_pass_theater_without_probe(self):
        run = MetaVerifierRun.from_dict({
            "run_id": "run-audit-4",
            "raw_user_request": "这个系统能不能帮助营销负责人制定增长计划",
            "route": {"primary_route": "persona_critique", "supporting_routes": ["project_exploration"]},
            "goal_requirements": [{"requirement_id": "R1", "summary": "需求目标", "required_layers": ["demand_doc"], "requires_higher_level_probe": True}],
            "layer_coverage": {"visible_layers": ["demand_doc"], "visibility_scope": "skill-only"},
            "checklist": [{"item_id": "C1", "target": "page loads", "source": "impl/demand/meta-verifier.md", "requirement_id": "R1"}],
        })
        audit = MetaVerifierDemandCoverageAuditor().audit_completed_run(run)
        self.assertIn("pass_theater_risk", {item.category for item in audit})

    # --- Report ---
    def test_report_builder_outputs_actionable_sections(self):
        run = MetaVerifierRun.from_dict({
            "run_id": "run-1",
            "raw_user_request": "验证 8020 前端",
            "route": {"primary_route": "targeted_verification", "supporting_routes": ["browser_evidence"]},
            "goal_requirements": [{"requirement_id": "R1", "summary": "验证前端", "user_outcome": "用户完成验证", "required_layers": ["frontend", "browser"]}],
            "layer_coverage": {"visible_layers": ["frontend", "browser"], "invisible_layers": ["api"], "visibility_scope": "frontend-only", "confidence_impact": ["api layer not visible"]},
            "audit_results": [{"status": "warn", "category": "invisible_layer_risk", "message": "api layer not visible"}],
            "checklist": [{"item_id": "C1", "target": "index load", "source": "impl/frontend/index.html"}],
            "evidence": [{"evidence_id": "E1", "source": "browser", "page_state": {"title": "Index"}}],
            "findings": [{"finding_id": "F1", "category": "functional_defect", "severity": "high", "user_impact": "按钮无法点击", "evidence_refs": ["E1"]}],
        })
        report = MetaVerifierReportBuilder().build(run)
        data = report.to_dict()
        self.assertEqual(data["user_goal"], "验证 8020 前端")
        self.assertEqual(data["summary_by_category"]["functional_defect"], 1)
        self.assertEqual(data["goal_requirements"][0]["requirement_id"], "R1")
        self.assertEqual(data["layer_coverage"]["visibility_scope"], "frontend-only")
        self.assertIn("api layer not visible", data["confidence_impact"])


if __name__ == "__main__":
    unittest.main()
