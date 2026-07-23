"""Attribute protocol: investigation, Finalization, independent review, public result."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from typing import final as typing_final

from impl.core.protocol_base import check_forbidden_overrides
from impl.core.schema import AttributeResult, JudgeResult, ProjectSpec, RunTrace, normalize_attribute_result, to_dict
from impl.core.summary import summary_from_attribution


def _failed_expectation_ids(judge: JudgeResult) -> list[str]:
    from impl.core.attribute import failed_expectation_ids
    return failed_expectation_ids(judge)


def _judge_status(judge: JudgeResult) -> str:
    from impl.core.attribute import judge_status
    return judge_status(judge)


class _AttributeProtocol(ABC):
    _FORBIDDEN_OVERRIDES = frozenset({
        "attribute_failure",
        "_run_llm_attribute",
        "_validate_attribute_output",
        "_run_probes",
        "_run_attribute_review",
    })

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        check_forbidden_overrides(cls, cls._FORBIDDEN_OVERRIDES)

    @typing_final
    def attribute_failure(self, trace: RunTrace, judge_result: JudgeResult) -> AttributeResult:
        context = self.build_context(trace, judge_result)
        if not isinstance(context, dict):
            raise TypeError("ProjectAttribute.build_context() must return a dict")
        environment = getattr(self, "_attribute_execution_environment", None)
        if environment is not None:
            context = environment.assemble(context)
        context["probe_results"] = self._run_probes(trace, judge_result)
        register_dynamic = context.get("_attribute_register_dynamic_materials")
        if callable(register_dynamic):
            context["dynamic_context_units"] = register_dynamic({
                "runtime_checks": context.get("runtime_checks"),
                "probe_results": context.get("probe_results"),
            })

        failed_ids = _failed_expectation_ids(judge_result)
        if _judge_status(judge_result) == "fulfilled":
            result = AttributeResult(trace.trace_id, trace.project_id, str(trace.case_id or ""))
            result.summary = summary_from_attribution(to_dict(result), failed_ids, judge_status="fulfilled")
            return result

        review_enabled = bool(context.get("_attribute_review_enabled"))
        custom_main = self.__class__.run_attribute_round is not _AttributeProtocol.run_attribute_round
        draft_enabled = self.spec.role_draft("attribute").get("enabled") is True
        if custom_main and not draft_enabled:
            raise TypeError("run_attribute_round may only be overridden by an enabled attribute draft")

        last_issues: list[dict[str, Any]] = []
        for round_number in (1, 2):
            context["_attribute_round"] = round_number
            raw = self.run_attribute_round(trace, judge_result, context)
            candidate = self._validate_attribute_output(raw, context, judge_result)
            candidate_snapshot = normalize_attribute_result(to_dict(candidate))
            if candidate_snapshot is None:
                raise ValueError("failed to snapshot Attribute result before project normalization")
            normalized = self.normalize_result(trace, judge_result, candidate)
            self._assert_normalize_subset(candidate_snapshot, normalized)
            candidate = self._validate_attribute_output(normalized, context, judge_result)

            if not candidate.findings or not review_enabled:
                candidate.summary = summary_from_attribution(to_dict(candidate), failed_ids, judge_status=_judge_status(judge_result))
                return candidate
            review = self._run_attribute_review(trace, judge_result, candidate, context, round_number)
            context.setdefault("_attribute_review_audit", []).append({
                "round": round_number,
                "finding_ids": [finding.finding_id for finding in candidate.findings],
                "passed": review.get("passed") is True,
                "issues": list(review.get("issues") or []),
                "infrastructure_error": str(review.get("infrastructure_error") or ""),
            })
            infrastructure_error = str(review.get("infrastructure_error") or "").strip()
            if infrastructure_error:
                unresolved = AttributeResult(
                    trace_id=trace.trace_id,
                    project_id=trace.project_id,
                    case_id=str(trace.case_id or ""),
                    unresolved_reason=f"归因独立审查未完成，现有结论不能作为正式归因。{infrastructure_error}",
                )
                unresolved.summary = summary_from_attribution(
                    to_dict(unresolved), failed_ids, judge_status=_judge_status(judge_result)
                )
                return unresolved
            if review.get("passed") is True:
                candidate.summary = summary_from_attribution(to_dict(candidate), failed_ids, judge_status=_judge_status(judge_result))
                return candidate
            last_issues = list(review.get("issues") or [])
            if round_number == 1:
                context["review_issues"] = last_issues
                continue

        reason = "独立 Reviewer 两轮均未确认现有 evidence 足以证明归因结论。"
        if last_issues:
            problems = [str(item.get("problem") or "").strip() for item in last_issues if isinstance(item, dict)]
            if any(problems):
                reason += " " + "；".join(item for item in problems if item)
        unresolved = AttributeResult(
            trace_id=trace.trace_id,
            project_id=trace.project_id,
            case_id=str(trace.case_id or ""),
            unresolved_reason=reason,
        )
        unresolved.summary = summary_from_attribution(to_dict(unresolved), failed_ids, judge_status=_judge_status(judge_result))
        return unresolved

    def _run_probes(self, trace: RunTrace, judge_result: JudgeResult) -> List[Dict[str, Any]]:
        probe_fn = self.probes()
        if not probe_fn:
            return []
        try:
            results = probe_fn(trace, judge_result)
            return results if isinstance(results, list) else []
        except Exception as exc:
            return [{"probe_error": str(exc), "probe_status": "failed"}]

    def _run_llm_attribute(self, trace: RunTrace, judge_result: JudgeResult, context: Dict[str, Any]) -> AttributeResult:
        from impl.core.attribute import attribute_failure
        return attribute_failure(self.spec, trace, judge_result, project_attribute_context=context)

    def _run_attribute_review(
        self,
        trace: RunTrace,
        judge_result: JudgeResult,
        result: AttributeResult,
        context: Dict[str, Any],
        round_number: int,
    ) -> Dict[str, Any]:
        from impl.core.attribute_reviewer import review_attribute_result
        return review_attribute_result(
            spec=self.spec,
            trace=trace,
            judge=judge_result,
            result=result,
            project_context=context,
            round_number=round_number,
        )

    def _validate_attribute_output(
        self,
        result: AttributeResult,
        context: Optional[Dict[str, Any]] = None,
        judge_result: Optional[JudgeResult] = None,
    ) -> AttributeResult:
        result = normalize_attribute_result(result)
        if result is None:
            raise ValueError("attribute output is None or invalid")
        allowed = set(_failed_expectation_ids(judge_result)) if judge_result else set()
        seen_findings: set[str] = set()
        for finding in result.findings:
            if not finding.finding_id or finding.finding_id in seen_findings:
                raise ValueError("finding_id must be non-empty and unique")
            seen_findings.add(finding.finding_id)
            if not finding.conclusion.strip() or not finding.affected_expectation_ids:
                raise ValueError("finding conclusion and affected_expectation_ids are required")
            if allowed and not set(finding.affected_expectation_ids).issubset(allowed):
                raise ValueError("finding may only cover not_fulfilled expectations")
            if not finding.evidence:
                raise ValueError("every finding requires finalized evidence")
            for evidence in finding.evidence:
                metadata = evidence.metadata or {}
                if evidence.source != "context_unit" or evidence.payload is not None:
                    raise ValueError("Attribute evidence must reference ContextUnit with empty payload")
                if not evidence.ref_id or not evidence.location or not evidence.summary.strip():
                    raise ValueError("EvidenceRef identity, ContextUnit location and reason are required")
                if not metadata.get("source_hash") or metadata.get("trace_id") != result.trace_id:
                    raise ValueError("EvidenceRef source hash and trace boundary are required")
                if str(metadata.get("case_id") or "") != str(result.case_id or ""):
                    raise ValueError("EvidenceRef crosses case boundary")
        covered = {item for finding in result.findings for item in finding.affected_expectation_ids}
        if allowed - covered and result.findings and not result.unresolved_reason.strip():
            raise ValueError("partial attribution requires unresolved_reason")
        if not result.findings and _judge_status(judge_result) != "fulfilled" and not result.unresolved_reason.strip():
            raise ValueError("unresolved attribution requires unresolved_reason")
        return result

    @staticmethod
    def _assert_normalize_subset(before: AttributeResult, after: AttributeResult) -> None:
        """Project normalization cannot manufacture post-Finalization facts."""
        if after is None:
            raise ValueError("normalize_result returned None")
        originals = {finding.finding_id: finding for finding in before.findings}
        for finding in after.findings:
            original = originals.get(finding.finding_id)
            if original is None:
                raise ValueError("normalize_result may not add findings")
            if finding.conclusion != original.conclusion:
                raise ValueError("normalize_result may not add or rewrite conclusions")
            if not set(finding.affected_expectation_ids).issubset(original.affected_expectation_ids):
                raise ValueError("normalize_result may not expand expectation coverage")
            original_evidence = {item.ref_id: to_dict(item) for item in original.evidence}
            for evidence in finding.evidence:
                if original_evidence.get(evidence.ref_id) != to_dict(evidence):
                    raise ValueError("normalize_result may not add or rewrite EvidenceRef")
        if after.unresolved_reason != before.unresolved_reason:
            raise ValueError("normalize_result may not add or rewrite unresolved_reason")

    def run_attribute_round(self, trace: RunTrace, judge_result: JudgeResult, context: Dict[str, Any]) -> AttributeResult:
        return self._run_llm_attribute(trace, judge_result, context)

    @abstractmethod
    def build_context(self, trace: RunTrace, judge_result: JudgeResult) -> Dict[str, Any]:
        """Return project-specific tools, checks and concise case constraints."""
        raise NotImplementedError

    def probes(self) -> Optional[Callable[[RunTrace, JudgeResult], List[Dict[str, Any]]]]:
        return None

    def normalize_result(self, trace: RunTrace, judge_result: JudgeResult, result: AttributeResult) -> AttributeResult:
        """May only sort, deduplicate, delete or narrow the common result."""
        return result


class ProjectAttribute(_AttributeProtocol):
    def __init__(self, spec: ProjectSpec):
        self.spec = spec
        self.live_schema = None
        if spec is not None:
            from impl.core.mock_agent import load_live_schema
            self.live_schema = load_live_schema(spec.project_id)
        self._attribute_execution_environment = None

    def configure_execution_environment(self, environment: Any) -> None:
        self._attribute_execution_environment = environment
