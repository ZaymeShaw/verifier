from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable
from unittest.mock import patch

import impl.core.pipeline as pipeline
from impl.core.adapter_v2 import ProjectAdapter
from impl.core.attribute_protocol import ProjectAttribute
from impl.core.judge_protocol import ProjectJudge
from impl.core.live_protocol import ProvidedOutputLive
from impl.core.mock_protocol import ProjectMock
from impl.core.schema import normalize_multi_turn_trace_summary
from impl.core.schema.attribute import AttributeResult
from impl.core.schema.check import CheckReport
from impl.core.schema.cluster import ClusterSummary
from impl.core.schema.fixture import load_fixture
from impl.core.schema.frontend import FrontendViewModel
from impl.core.schema.judge import JudgeResult
from impl.core.schema.mock import MockCase, SingleTurnCase
from impl.core.schema.project import ProjectAnalysis, ProjectSpec
from impl.core.schema.trace import RunTrace


class FixtureLive(ProvidedOutputLive):
    def deliver_provided(self, case, request):
        return case.output or {}

    def extract_output(self, raw_response, request):
        return raw_response if isinstance(raw_response, dict) else {}


class FixtureMock(ProjectMock):
    def build_user_intent(self, scenario):
        return {"scenario": scenario, "query": "fixture"}


class FixtureJudge(ProjectJudge):
    def build_context(self, trace):
        return {}


class FixtureAttribute(ProjectAttribute):
    def build_context(self, trace, judge_result):
        return {}


class FixtureAdapter(ProjectAdapter):
    def _load_live(self):
        return FixtureLive(self.spec)

    def _load_mock(self):
        return FixtureMock(self.spec)

    def _load_judge(self):
        return FixtureJudge(self.spec)

    def _load_attribute(self):
        return FixtureAttribute(self.spec)


@dataclass(frozen=True)
class FixtureCheck:
    name: str
    target: str
    why: str
    run: Callable[[], object]


def _spec() -> ProjectSpec:
    return load_fixture(ProjectSpec)


def _adapter() -> FixtureAdapter:
    return FixtureAdapter(_spec())


def _trace() -> RunTrace:
    return load_fixture(RunTrace)


def _judge() -> JudgeResult:
    return load_fixture(JudgeResult)


def _attribute() -> AttributeResult:
    return load_fixture(AttributeResult)


def _cluster() -> ClusterSummary:
    return load_fixture(ClusterSummary)


def _check() -> CheckReport:
    return load_fixture(CheckReport)


def _view() -> FrontendViewModel:
    return load_fixture(FrontendViewModel)


@contextmanager
def _patched_project_runtime():
    adapter = _adapter()
    with patch.object(pipeline, "load_project", return_value=_spec()), \
        patch.object(pipeline, "load_adapter", return_value=adapter), \
        patch.object(pipeline, "analyze_project", return_value=load_fixture(ProjectAnalysis)):
        yield adapter


# fixture-check intentionally targets the project core chain, not every helper.
# It asks: can standard fixtures flow through live -> trace -> judge -> attribute -> cluster/check/view/table boundaries?


def _case_from_input() -> object:
    return pipeline._case_from_input("fixture_project", load_fixture(SingleTurnCase))


def _multi_turn_trace_summary() -> object:
    trace = _trace()
    trace.interaction_mode = "interactive_intent"
    trace.conversation_transcript = [{"role": "user", "content": "fixture"}]
    return normalize_multi_turn_trace_summary({
        "trace_id": trace.trace_id,
        "project_id": trace.project_id,
        "session_id": trace.session_id,
        "input": trace.input,
        "turn_traces": [trace],
        "conversation_transcript": trace.conversation_transcript,
        "stop_reason": trace.stop_reason,
        "final_output": trace.extracted_output,
    })


def _live_run() -> object:
    with _patched_project_runtime():
        case = load_fixture(SingleTurnCase, as_dict=True)
        return pipeline.live_run("fixture_project", case)


def _judge_chain_step() -> object:
    with _patched_project_runtime(), patch.object(FixtureJudge, "judge_trace", return_value=_judge()):
        return pipeline.judge("fixture_project", _trace())


def _attribute_chain_step() -> object:
    with _patched_project_runtime(), patch.object(FixtureAttribute, "_run_llm_attribute", return_value=_attribute()):
        return pipeline.attribute("fixture_project", _trace(), _judge())


def _incomplete_state_attribute_result() -> object:
    return pipeline.incomplete_state_attribute_result(_trace(), load_fixture(JudgeResult, scenario="incorrect"))


def _cluster_chain_step() -> object:
    return pipeline.cluster("fixture_project", [_attribute()])


def _check_chain_step() -> object:
    with _patched_project_runtime():
        return pipeline.check("fixture_project", _trace(), _judge(), _attribute(), _cluster())


def _frontend_view_chain_step() -> object:
    with _patched_project_runtime():
        return pipeline.frontend_view("fixture_project", _trace(), _judge(), _attribute(), _cluster(), _check())


def _mock_spec_chain_step() -> object:
    with _patched_project_runtime():
        return pipeline.mock_spec("fixture_project")


def _mock_cases_chain_step() -> object:
    with _patched_project_runtime():
        return pipeline.mock_cases("fixture_project")


def _mock_datasets_chain_step() -> object:
    with _patched_project_runtime():
        return pipeline.mock_datasets("fixture_project")


def _run_payload() -> object:
    return pipeline._run_payload(_trace(), _judge(), _attribute(), _cluster(), _check(), _view())


def _batch_run_empty() -> object:
    with _patched_project_runtime():
        return pipeline.batch_run("fixture_project", [])


def _batch_run_with_patched_case() -> object:
    run = _run_payload()
    with _patched_project_runtime(), patch.object(pipeline, "_batch_case", return_value=run):
        return pipeline.batch_run("fixture_project", [load_fixture(MockCase, as_dict=True, project_id="fixture_project")], concurrency=1)


def _run_chain_with_patched_steps() -> object:
    with _patched_project_runtime(), \
        patch.object(pipeline, "live_run", return_value=_trace()), \
        patch.object(pipeline, "judge", return_value=_judge()), \
        patch.object(pipeline, "attribute", return_value=_attribute()), \
        patch.object(pipeline, "cluster", return_value=_cluster()), \
        patch.object(pipeline, "check", return_value=_check()), \
        patch.object(pipeline, "frontend_view", return_value=_view()):
        return pipeline.run_chain("fixture_project", load_fixture(SingleTurnCase))


FIXTURE_CHECKS = [
    FixtureCheck("pipeline.case_from_input", "impl.core.pipeline._case_from_input", "case 输入进入核心链路前先规范成 SingleTurnCase。", _case_from_input),
    FixtureCheck("schema.multi_turn_trace_summary", "impl.core.schema.normalize_multi_turn_trace_summary", "多轮 trace 汇总结构是 issue4/issue5 的关键链路。", _multi_turn_trace_summary),
    FixtureCheck("pipeline.live_run", "impl.core.pipeline.live_run", "project case -> RunTrace，是核心链路第一段。", _live_run),
    FixtureCheck("pipeline.judge", "impl.core.pipeline.judge", "RunTrace -> JudgeResult，是评估链路入口。", _judge_chain_step),
    FixtureCheck("pipeline.attribute", "impl.core.pipeline.attribute", "Trace/Judge -> AttributeResult，是归因链路入口。", _attribute_chain_step),
    FixtureCheck("pipeline.incomplete_attribute", "impl.core.pipeline.incomplete_state_attribute_result", "状态机未完成时必须保留结构化归因结果。", _incomplete_state_attribute_result),
    FixtureCheck("pipeline.cluster", "impl.core.pipeline.cluster", "AttributeResult[] -> ClusterSummary，是批量归因聚合段。", _cluster_chain_step),
    FixtureCheck("pipeline.check", "impl.core.pipeline.check", "Trace/Judge/Attribute/Cluster -> CheckReport，是一致性审查段。", _check_chain_step),
    FixtureCheck("pipeline.frontend_view", "impl.core.pipeline.frontend_view", "链路结果 -> FrontendViewModel，是展示边界。", _frontend_view_chain_step),
    FixtureCheck("pipeline.mock_spec", "impl.core.pipeline.mock_spec", "项目分析 -> MockSpec，是 mock 构建入口。", _mock_spec_chain_step),
    FixtureCheck("pipeline.mock_cases", "impl.core.pipeline.mock_cases", "adapter mock cases -> 标准 case payload。", _mock_cases_chain_step),
    FixtureCheck("pipeline.mock_datasets", "impl.core.pipeline.mock_datasets", "adapter mock datasets -> 标准 dataset payload。", _mock_datasets_chain_step),
    FixtureCheck("pipeline.run_payload", "impl.core.pipeline._run_payload", "trace/judge/attribute/check/view/table 被组装成 run payload。", _run_payload),
    FixtureCheck("pipeline.batch_run_empty", "impl.core.pipeline.batch_run:empty", "空批次也要产出 BatchRunResult/check/table。", _batch_run_empty),
    FixtureCheck("pipeline.batch_run", "impl.core.pipeline.batch_run", "多 case 批处理聚合 runs/cluster/check/table。", _batch_run_with_patched_case),
    FixtureCheck("pipeline.run_chain", "impl.core.pipeline.run_chain", "完整核心链路编排：live -> judge -> attribute -> cluster -> check -> view -> table。", _run_chain_with_patched_steps),
]
